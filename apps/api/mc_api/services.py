import re
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from mc_auth.api_keys import generate_api_key
from mc_auth.passwords import hash_password, password_is_acceptable, verify_password
from mc_auth.tokens import decode_token, issue_token
from mc_runtimes.factory import build_runtime
from mc_shared.crypto import encrypt_secret
from mc_shared.errors import PlatformError
from mc_shared.models import (
    ApiKey,
    ApiKeyModel,
    AuditLog,
    Deployment,
    Model,
    Organization,
    OrganizationUser,
    Project,
    ProjectModel,
    Runtime,
    UsageLog,
    User,
)

_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def require_slug(value: str) -> str:
    slug = value.strip().lower()
    if not _SLUG.match(slug):
        raise PlatformError("invalid_request", "Slug must use lowercase letters, numbers, and hyphens.", 422)
    return slug


def stamp(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


async def audit(session: AsyncSession, event_type: str, user_id: uuid.UUID | None, organization_id: uuid.UUID | None, metadata: dict | None = None) -> None:
    session.add(AuditLog(event_type=event_type, user_id=user_id, organization_id=organization_id, metadata_json=metadata or {}))


async def login(session: AsyncSession, email: str, password: str) -> dict:
    user = (await session.execute(select(User).where(User.email == email.lower()))).scalar_one_or_none()
    if user is None or not user.is_active or not verify_password(password, user.password_hash):
        raise PlatformError("invalid_request", "Invalid email or password.", 401)
    access, access_jti, ttl = issue_token(str(user.id), user.role, "access")
    refresh, refresh_jti, _refresh_ttl = issue_token(str(user.id), user.role, "refresh")
    await audit(session, "LOGIN_SUCCESS", user.id, None, {"email": user.email})
    await session.commit()
    return {
        "access_token": access,
        "refresh_token": refresh,
        "token_type": "bearer",
        "expires_in": ttl,
        "user": public_user(user),
        "access_jti": access_jti,
        "refresh_jti": refresh_jti,
    }


def public_user(user: User) -> dict:
    return {"id": str(user.id), "email": user.email, "username": user.username, "role": user.role, "is_active": user.is_active}


async def member_org_ids(session: AsyncSession, user: User) -> list[uuid.UUID] | None:
    if user.role == "SUPER_ADMIN":
        return None
    rows = (await session.execute(select(OrganizationUser.organization_id).where(OrganizationUser.user_id == user.id))).scalars().all()
    return list(rows)


async def assert_org(session: AsyncSession, user: User, organization_id: uuid.UUID) -> None:
    allowed = await member_org_ids(session, user)
    if allowed is None:
        return
    if organization_id not in allowed:
        raise PlatformError("invalid_request", "Organization was not found.", 404)


def assert_manager(user: User) -> None:
    if user.role not in {"SUPER_ADMIN", "ADMIN"}:
        raise PlatformError("invalid_request", "You do not have permission.", 403)


async def create_organization(session: AsyncSession, user: User, name: str, slug: str) -> Organization:
    assert_manager(user)
    org = Organization(name=name.strip(), slug=require_slug(slug))
    session.add(org)
    await session.flush()
    session.add(OrganizationUser(organization_id=org.id, user_id=user.id, role="owner"))
    await audit(session, "ORGANIZATION_CREATED", user.id, org.id, {"slug": org.slug})
    await session.commit()
    await session.refresh(org)
    return org


async def create_model(session: AsyncSession, user: User, fields: dict) -> Model:
    assert_manager(user)
    model = Model(
        name=fields["name"].strip(),
        slug=require_slug(fields["slug"]),
        display_name=fields.get("display_name") or fields["name"],
        description=fields.get("description") or "",
        model_family=fields.get("model_family") or "",
        model_type=fields.get("model_type") or "chat",
        provider_name=fields.get("provider_name") or "",
        license=fields.get("license") or "",
        license_url=fields.get("license_url") or "",
        parameter_count=fields.get("parameter_count") or "",
        context_window=fields.get("context_window") or 8192,
        max_output_tokens=fields.get("max_output_tokens") or 2048,
        supports_chat=fields.get("supports_chat", True),
        supports_streaming=fields.get("supports_streaming", True),
        supports_tools=fields.get("supports_tools", False),
        supports_structured_output=fields.get("supports_structured_output", False),
        supports_vision=bool(fields.get("supports_vision")),
        supports_audio=bool(fields.get("supports_audio")),
        supports_embeddings=bool(fields.get("supports_embeddings")),
        is_active=fields.get("is_active", True),
        is_public=bool(fields.get("is_public")),
    )
    session.add(model)
    await audit(session, "MODEL_CREATED", user.id, None, {"slug": model.slug})
    await session.commit()
    await session.refresh(model)
    return model


def public_model(model: Model, running: int = 0) -> dict:
    return {
        "id": str(model.id),
        "name": model.name,
        "slug": model.slug,
        "display_name": model.display_name,
        "description": model.description,
        "model_family": model.model_family,
        "model_type": model.model_type,
        "provider_name": model.provider_name,
        "license": model.license,
        "license_url": model.license_url,
        "parameter_count": model.parameter_count,
        "context_window": model.context_window,
        "max_output_tokens": model.max_output_tokens,
        "supports_chat": model.supports_chat,
        "supports_streaming": model.supports_streaming,
        "supports_tools": model.supports_tools,
        "supports_structured_output": model.supports_structured_output,
        "supports_vision": model.supports_vision,
        "supports_audio": model.supports_audio,
        "supports_embeddings": model.supports_embeddings,
        "is_active": model.is_active,
        "is_public": model.is_public,
        "running_deployments": running,
        "created_at": stamp(model.created_at),
        "updated_at": stamp(model.updated_at),
    }


async def create_runtime(session: AsyncSession, user: User, fields: dict) -> Runtime:
    assert_manager(user)
    await assert_org(session, user, fields["organization_id"])
    runtime = Runtime(
        organization_id=fields["organization_id"],
        name=fields["name"].strip(),
        slug=require_slug(fields["slug"]),
        type=fields["type"],
        endpoint=fields.get("endpoint") or "",
        api_key_encrypted=encrypt_secret(fields.get("api_key") or ""),
        gpu_enabled=bool(fields.get("gpu_enabled")),
        gpu_count=int(fields.get("gpu_count") or 0),
        configuration=fields.get("configuration") or {},
        status="offline",
        health_status="unknown",
    )
    if runtime.type not in {"local", "ollama", "vllm", "openai_compatible", "custom"}:
        raise PlatformError("invalid_request", "Runtime type is not supported.", 422)
    session.add(runtime)
    await session.commit()
    await session.refresh(runtime)
    return runtime


def public_runtime(runtime: Runtime, model_count: int = 0) -> dict:
    return {
        "id": str(runtime.id),
        "organization_id": str(runtime.organization_id),
        "name": runtime.name,
        "slug": runtime.slug,
        "type": runtime.type,
        "endpoint": runtime.endpoint,
        "status": runtime.status,
        "gpu_enabled": runtime.gpu_enabled,
        "gpu_count": runtime.gpu_count,
        "health_status": runtime.health_status,
        "last_health_check": stamp(runtime.last_health_check),
        "configuration": runtime.configuration or {},
        "model_count": model_count,
        "has_api_key": bool(runtime.api_key_encrypted),
    }


async def check_runtime_health(session: AsyncSession, runtime: Runtime) -> dict:
    result = await build_runtime(runtime).health_check(None)
    runtime.health_status = result["status"]
    runtime.status = "online" if result["status"] == "online" else "offline"
    runtime.last_health_check = datetime.now(UTC)
    await session.commit()
    return result


async def create_deployment(session: AsyncSession, user: User, fields: dict) -> Deployment:
    assert_manager(user)
    model = await session.get(Model, fields["model_id"])
    runtime = await session.get(Runtime, fields["runtime_id"])
    if model is None or runtime is None:
        raise PlatformError("invalid_request", "Model or runtime was not found.", 404)
    await assert_org(session, user, runtime.organization_id)
    deployment = Deployment(
        model_id=model.id,
        runtime_id=runtime.id,
        name=fields["name"].strip(),
        slug=require_slug(fields["slug"]),
        runtime_model_name=fields["runtime_model_name"].strip(),
        desired_status=fields.get("desired_status") or "running",
        status="running" if (fields.get("desired_status") or "running") == "running" else "stopped",
        replicas=int(fields.get("replicas") or 1),
        gpu_required=int(fields.get("gpu_required") or 0),
        gpu_memory_required=int(fields.get("gpu_memory_required") or 0),
        configuration=fields.get("configuration") or {},
        health_status="unknown",
    )
    session.add(deployment)
    await session.commit()
    await session.refresh(deployment)
    return deployment


def public_deployment(deployment: Deployment, runtime: Runtime | None = None) -> dict:
    return {
        "id": str(deployment.id),
        "model_id": str(deployment.model_id),
        "runtime_id": str(deployment.runtime_id),
        "name": deployment.name,
        "slug": deployment.slug,
        "runtime_model_name": deployment.runtime_model_name,
        "status": deployment.status,
        "desired_status": deployment.desired_status,
        "replicas": deployment.replicas,
        "gpu_required": deployment.gpu_required,
        "gpu_memory_required": deployment.gpu_memory_required,
        "configuration": deployment.configuration or {},
        "health_status": deployment.health_status,
        "last_health_check": stamp(deployment.last_health_check),
        "runtime_name": None if runtime is None else runtime.name,
        "runtime_type": None if runtime is None else runtime.type,
    }


async def issue_project_key(session: AsyncSession, user: User, project: Project, name: str, model_ids: list[uuid.UUID], expires_at: datetime | None, limits: dict) -> tuple[ApiKey, str]:
    assert_manager(user)
    await assert_org(session, user, project.organization_id)
    raw, prefix, digest = generate_api_key()
    record = ApiKey(
        project_id=project.id,
        name=name.strip(),
        key_prefix=prefix,
        key_hash=digest,
        expires_at=expires_at,
        rpm_limit=limits.get("rpm_limit"),
        tpm_limit=limits.get("tpm_limit"),
        daily_request_limit=limits.get("daily_request_limit"),
        monthly_request_limit=limits.get("monthly_request_limit"),
    )
    session.add(record)
    await session.flush()
    for model_id in model_ids:
        session.add(ApiKeyModel(api_key_id=record.id, model_id=model_id))
    await audit(session, "API_KEY_CREATED", user.id, project.organization_id, {"prefix": prefix})
    await session.commit()
    await session.refresh(record)
    return record, raw


async def dashboard(session: AsyncSession, organization_id: uuid.UUID) -> dict:
    usage = (
        await session.execute(
            select(
                func.count(UsageLog.id),
                func.coalesce(func.sum(UsageLog.total_tokens), 0),
                func.coalesce(func.sum(UsageLog.prompt_tokens), 0),
                func.coalesce(func.sum(UsageLog.completion_tokens), 0),
                func.coalesce(func.avg(UsageLog.latency_ms), 0),
            ).where(UsageLog.organization_id == organization_id)
        )
    ).one()
    errors = (
        await session.execute(
            select(func.count(UsageLog.id)).where(UsageLog.organization_id == organization_id, UsageLog.status_code >= 400)
        )
    ).scalar_one()
    total = int(usage[0] or 0)
    active_models = (await session.execute(select(func.count(Model.id)).where(Model.is_active.is_(True)))).scalar_one()
    active_deployments = (
        await session.execute(select(func.count(Deployment.id)).where(Deployment.status == "running"))
    ).scalar_one()
    project_ids = (await session.execute(select(Project.id).where(Project.organization_id == organization_id))).scalars().all()
    active_keys = 0
    if project_ids:
        active_keys = (
            await session.execute(
                select(func.count(ApiKey.id)).where(ApiKey.project_id.in_(project_ids), ApiKey.status == "active")
            )
        ).scalar_one()
    by_model = (
        await session.execute(
            select(Model.slug, func.count(UsageLog.id), func.coalesce(func.sum(UsageLog.total_tokens), 0))
            .join(Model, Model.id == UsageLog.model_id)
            .where(UsageLog.organization_id == organization_id)
            .group_by(Model.slug)
        )
    ).all()
    return {
        "total_requests": total,
        "total_tokens": int(usage[1] or 0),
        "input_tokens": int(usage[2] or 0),
        "output_tokens": int(usage[3] or 0),
        "active_models": int(active_models or 0),
        "active_deployments": int(active_deployments or 0),
        "active_api_keys": int(active_keys or 0),
        "average_latency_ms": float(usage[4] or 0),
        "error_rate": 0 if total == 0 else float(errors) / float(total),
        "requests_by_model": [{"model": row[0], "requests": int(row[1]), "tokens": int(row[2])} for row in by_model],
    }


async def bootstrap_admin(session: AsyncSession, email: str, password: str) -> None:
    if not email or not password or not password_is_acceptable(password):
        return
    existing = (await session.execute(select(User).where(User.role == "SUPER_ADMIN"))).scalar_one_or_none()
    if existing is not None:
        return
    user = User(
        email=email.lower(),
        username=email.split("@")[0][:64],
        password_hash=hash_password(password),
        role="SUPER_ADMIN",
        is_active=True,
    )
    session.add(user)
    await session.commit()
