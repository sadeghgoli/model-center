import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from mc_api.deps import current_user, revoke_jti
from mc_api.services import (
    assert_manager,
    assert_org,
    audit,
    check_runtime_health,
    create_deployment,
    create_model,
    create_organization,
    create_runtime,
    dashboard,
    issue_project_key,
    login,
    member_org_ids,
    public_deployment,
    public_model,
    public_runtime,
    public_user,
    require_slug,
)
from mc_auth.api_keys import generate_api_key
from mc_auth.tokens import decode_token, issue_token
from mc_gateway.gateway import authenticate_key, complete_chat, stream_chat
from mc_shared.db import get_session
from mc_shared.errors import PlatformError
from mc_shared.models import ApiKey, Deployment, Model, Organization, OrganizationUser, Project, ProjectModel, Runtime, User

router = APIRouter(prefix="/api/v1")


class LoginBody(BaseModel):
    email: str
    password: str = Field(min_length=1, max_length=128)


class RefreshBody(BaseModel):
    refresh_token: str


class OrgBody(BaseModel):
    name: str
    slug: str


class ProjectBody(BaseModel):
    organization_id: uuid.UUID
    name: str
    slug: str
    rpm_limit: int = 60
    tpm_limit: int = 100000
    daily_request_limit: int = 10000
    monthly_request_limit: int = 300000


class ModelBody(BaseModel):
    name: str
    slug: str
    display_name: str = ""
    description: str = ""
    model_family: str = ""
    model_type: str = "chat"
    provider_name: str = ""
    license: str = ""
    license_url: str = ""
    parameter_count: str = ""
    context_window: int = 8192
    max_output_tokens: int = 2048
    supports_chat: bool = True
    supports_streaming: bool = True
    supports_tools: bool = False
    supports_structured_output: bool = False
    supports_vision: bool = False
    supports_audio: bool = False
    supports_embeddings: bool = False
    is_active: bool = True
    is_public: bool = False


class RuntimeBody(BaseModel):
    organization_id: uuid.UUID
    name: str
    slug: str
    type: str
    endpoint: str = ""
    api_key: str = ""
    gpu_enabled: bool = False
    gpu_count: int = 0
    configuration: dict = Field(default_factory=dict)


class DeploymentBody(BaseModel):
    model_id: uuid.UUID
    runtime_id: uuid.UUID
    name: str
    slug: str
    runtime_model_name: str
    desired_status: str = "running"
    replicas: int = 1
    gpu_required: int = 0
    gpu_memory_required: int = 0
    configuration: dict = Field(default_factory=dict)


class KeyBody(BaseModel):
    name: str
    model_ids: list[uuid.UUID] = Field(default_factory=list)
    expires_at: datetime | None = None
    rpm_limit: int | None = None
    tpm_limit: int | None = None
    daily_request_limit: int | None = None
    monthly_request_limit: int | None = None


class PlaygroundBody(BaseModel):
    project_id: uuid.UUID | None = None
    model: str
    messages: list[dict]
    stream: bool = False
    temperature: float | None = 0.7
    max_tokens: int | None = 1024
    tools: list | None = None
    response_format: dict | None = None

    model_config = {"extra": "allow"}


def ok(request: Request, data: dict, status_code: int = 200) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"success": True, "data": data, "request_id": request.state.request_id})


@router.post("/auth/login")
async def post_login(body: LoginBody, request: Request, session: AsyncSession = Depends(get_session)) -> JSONResponse:
    tokens = await login(session, body.email, body.password)
    tokens.pop("access_jti", None)
    tokens.pop("refresh_jti", None)
    return ok(request, tokens)


@router.post("/auth/refresh")
async def post_refresh(body: RefreshBody, request: Request, session: AsyncSession = Depends(get_session)) -> JSONResponse:
    payload = decode_token(body.refresh_token, "refresh")
    from mc_api.deps import is_revoked

    if is_revoked(payload["jti"]):
        raise PlatformError("invalid_request", "Token has been revoked.", 401)
    user = await session.get(User, uuid.UUID(payload["sub"]))
    if user is None or not user.is_active:
        raise PlatformError("invalid_request", "Token is invalid.", 401)
    await revoke_jti(payload["jti"])
    access, _jti, ttl = issue_token(str(user.id), user.role, "access")
    refresh, _refresh_jti, _ttl = issue_token(str(user.id), user.role, "refresh")
    return ok(request, {"access_token": access, "refresh_token": refresh, "token_type": "bearer", "expires_in": ttl})


@router.post("/auth/logout")
async def post_logout(body: RefreshBody, request: Request, user: User = Depends(current_user)) -> JSONResponse:
    payload = decode_token(body.refresh_token, "refresh")
    await revoke_jti(payload["jti"])
    return ok(request, {"status": "logged_out"})


@router.get("/auth/me")
async def me(request: Request, user: User = Depends(current_user)) -> JSONResponse:
    return ok(request, public_user(user))


@router.post("/organizations")
async def post_org(body: OrgBody, request: Request, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    org = await create_organization(session, user, body.name, body.slug)
    return ok(request, {"id": str(org.id), "name": org.name, "slug": org.slug}, 201)


@router.get("/organizations")
async def list_orgs(request: Request, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    allowed = await member_org_ids(session, user)
    query = select(Organization)
    if allowed is not None:
        query = query.where(Organization.id.in_(allowed or [uuid.uuid4()]))
    rows = (await session.execute(query.order_by(Organization.created_at))).scalars().all()
    return ok(request, {"organizations": [{"id": str(row.id), "name": row.name, "slug": row.slug} for row in rows]})


@router.post("/projects")
async def post_project(body: ProjectBody, request: Request, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    assert_manager(user)
    await assert_org(session, user, body.organization_id)
    project = Project(
        organization_id=body.organization_id,
        name=body.name.strip(),
        slug=require_slug(body.slug),
        rpm_limit=body.rpm_limit,
        tpm_limit=body.tpm_limit,
        daily_request_limit=body.daily_request_limit,
        monthly_request_limit=body.monthly_request_limit,
    )
    session.add(project)
    await session.commit()
    await session.refresh(project)
    return ok(request, {"id": str(project.id), "name": project.name, "slug": project.slug, "organization_id": str(project.organization_id)}, 201)


@router.get("/projects")
async def list_projects(request: Request, organization_id: uuid.UUID, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    await assert_org(session, user, organization_id)
    rows = (await session.execute(select(Project).where(Project.organization_id == organization_id))).scalars().all()
    return ok(request, {"projects": [{"id": str(row.id), "name": row.name, "slug": row.slug, "organization_id": str(row.organization_id)} for row in rows]})


@router.get("/projects/{project_id}")
async def get_project(project_id: uuid.UUID, request: Request, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    project = await session.get(Project, project_id)
    if project is None:
        raise PlatformError("invalid_request", "Project was not found.", 404)
    await assert_org(session, user, project.organization_id)
    return ok(request, {"id": str(project.id), "name": project.name, "slug": project.slug, "organization_id": str(project.organization_id), "rpm_limit": project.rpm_limit, "tpm_limit": project.tpm_limit})


@router.post("/models")
async def post_model(body: ModelBody, request: Request, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    model = await create_model(session, user, body.model_dump())
    return ok(request, public_model(model), 201)


@router.get("/models")
async def list_models(request: Request, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(select(Model).order_by(Model.created_at))).scalars().all()
    payload = []
    for model in rows:
        running = (
            await session.execute(select(func.count(Deployment.id)).where(Deployment.model_id == model.id, Deployment.status == "running"))
        ).scalar_one()
        payload.append(public_model(model, int(running or 0)))
    return ok(request, {"models": payload})


@router.get("/models/{model_id}")
async def get_model(model_id: uuid.UUID, request: Request, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    model = await session.get(Model, model_id)
    if model is None:
        raise PlatformError("invalid_request", "Model was not found.", 404)
    running = (
        await session.execute(select(func.count(Deployment.id)).where(Deployment.model_id == model.id, Deployment.status == "running"))
    ).scalar_one()
    return ok(request, public_model(model, int(running or 0)))


@router.put("/models/{model_id}")
async def put_model(model_id: uuid.UUID, body: ModelBody, request: Request, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    assert_manager(user)
    model = await session.get(Model, model_id)
    if model is None:
        raise PlatformError("invalid_request", "Model was not found.", 404)
    for key, value in body.model_dump().items():
        if key == "slug":
            value = require_slug(value)
        setattr(model, key, value)
    await session.commit()
    await session.refresh(model)
    return ok(request, public_model(model))


@router.post("/models/{model_id}/disable")
async def disable_model(model_id: uuid.UUID, request: Request, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    assert_manager(user)
    model = await session.get(Model, model_id)
    if model is None:
        raise PlatformError("invalid_request", "Model was not found.", 404)
    model.is_active = False
    await session.commit()
    return ok(request, public_model(model))


@router.post("/runtimes")
async def post_runtime(body: RuntimeBody, request: Request, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    runtime = await create_runtime(session, user, body.model_dump())
    return ok(request, public_runtime(runtime), 201)


@router.get("/runtimes")
async def list_runtimes(request: Request, organization_id: uuid.UUID, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    await assert_org(session, user, organization_id)
    rows = (await session.execute(select(Runtime).where(Runtime.organization_id == organization_id))).scalars().all()
    payload = []
    for runtime in rows:
        count = (await session.execute(select(func.count(Deployment.id)).where(Deployment.runtime_id == runtime.id))).scalar_one()
        payload.append(public_runtime(runtime, int(count or 0)))
    return ok(request, {"runtimes": payload})


@router.post("/runtimes/{runtime_id}/health")
async def runtime_health(runtime_id: uuid.UUID, request: Request, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    runtime = await session.get(Runtime, runtime_id)
    if runtime is None:
        raise PlatformError("invalid_request", "Runtime was not found.", 404)
    await assert_org(session, user, runtime.organization_id)
    result = await check_runtime_health(session, runtime)
    return ok(request, result)


@router.post("/deployments")
async def post_deployment(body: DeploymentBody, request: Request, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    deployment = await create_deployment(session, user, body.model_dump())
    runtime = await session.get(Runtime, deployment.runtime_id)
    return ok(request, public_deployment(deployment, runtime), 201)


@router.get("/deployments")
async def list_deployments(request: Request, model_id: uuid.UUID | None = None, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    query = select(Deployment, Runtime).join(Runtime, Runtime.id == Deployment.runtime_id)
    if model_id is not None:
        query = query.where(Deployment.model_id == model_id)
    allowed = await member_org_ids(session, user)
    if allowed is not None:
        query = query.where(Runtime.organization_id.in_(allowed or [uuid.uuid4()]))
    rows = (await session.execute(query)).all()
    return ok(request, {"deployments": [public_deployment(deployment, runtime) for deployment, runtime in rows]})


@router.post("/deployments/{deployment_id}/stop")
async def stop_deployment(deployment_id: uuid.UUID, request: Request, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    assert_manager(user)
    deployment = await session.get(Deployment, deployment_id)
    if deployment is None:
        raise PlatformError("invalid_request", "Deployment was not found.", 404)
    deployment.status = "stopped"
    deployment.desired_status = "stopped"
    await session.commit()
    return ok(request, public_deployment(deployment))


@router.post("/projects/{project_id}/models")
async def allow_model(project_id: uuid.UUID, body: dict, request: Request, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    assert_manager(user)
    project = await session.get(Project, project_id)
    if project is None:
        raise PlatformError("invalid_request", "Project was not found.", 404)
    await assert_org(session, user, project.organization_id)
    model_id = uuid.UUID(str(body["model_id"]))
    session.add(ProjectModel(project_id=project.id, model_id=model_id))
    await session.commit()
    return ok(request, {"project_id": str(project.id), "model_id": str(model_id)}, 201)


@router.get("/projects/{project_id}/models")
async def project_models(project_id: uuid.UUID, request: Request, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    project = await session.get(Project, project_id)
    if project is None:
        raise PlatformError("invalid_request", "Project was not found.", 404)
    await assert_org(session, user, project.organization_id)
    rows = (
        await session.execute(
            select(Model).join(ProjectModel, ProjectModel.model_id == Model.id).where(ProjectModel.project_id == project.id)
        )
    ).scalars().all()
    return ok(request, {"models": [public_model(row) for row in rows]})


@router.post("/projects/{project_id}/api-keys")
async def post_key(project_id: uuid.UUID, body: KeyBody, request: Request, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    project = await session.get(Project, project_id)
    if project is None:
        raise PlatformError("invalid_request", "Project was not found.", 404)
    record, raw = await issue_project_key(
        session,
        user,
        project,
        body.name,
        body.model_ids,
        body.expires_at,
        body.model_dump(),
    )
    return ok(request, {"id": str(record.id), "name": record.name, "key_prefix": record.key_prefix, "api_key": raw}, 201)


@router.get("/projects/{project_id}/api-keys")
async def list_keys(project_id: uuid.UUID, request: Request, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    project = await session.get(Project, project_id)
    if project is None:
        raise PlatformError("invalid_request", "Project was not found.", 404)
    await assert_org(session, user, project.organization_id)
    rows = (await session.execute(select(ApiKey).where(ApiKey.project_id == project.id))).scalars().all()
    return ok(
        request,
        {
            "api_keys": [
                {"id": str(row.id), "name": row.name, "key_prefix": row.key_prefix, "status": row.status, "expires_at": None if row.expires_at is None else row.expires_at.isoformat()}
                for row in rows
            ]
        },
    )


@router.post("/api-keys/{key_id}/revoke")
async def revoke_key(key_id: uuid.UUID, request: Request, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    assert_manager(user)
    record = await session.get(ApiKey, key_id)
    if record is None:
        raise PlatformError("invalid_request", "API key was not found.", 404)
    project = await session.get(Project, record.project_id)
    if project is None:
        raise PlatformError("invalid_request", "API key was not found.", 404)
    await assert_org(session, user, project.organization_id)
    record.status = "revoked"
    record.revoked_at = datetime.now(UTC)
    await audit(session, "API_KEY_REVOKED", user.id, project.organization_id, {"prefix": record.key_prefix})
    await session.commit()
    return ok(request, {"id": str(record.id), "status": record.status})


@router.get("/dashboard")
async def get_dashboard(organization_id: uuid.UUID, request: Request, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    await assert_org(session, user, organization_id)
    return ok(request, await dashboard(session, organization_id))


@router.post("/playground/chat")
async def playground(body: PlaygroundBody, request: Request, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    model = (await session.execute(select(Model).where(Model.slug == body.model, Model.is_active.is_(True)))).scalar_one_or_none()
    if model is None:
        raise PlatformError("model_not_found", "Model was not found.", 404)
    if body.project_id is None:
        allowed = await member_org_ids(session, user)
        org_query = select(Organization)
        if allowed is not None:
            org_query = org_query.where(Organization.id.in_(allowed or [uuid.uuid4()]))
        org = (await session.execute(org_query.limit(1))).scalars().first()
        if org is None:
            raise PlatformError("invalid_request", "First create an organization.", 404)
        project = (
            await session.execute(select(Project).where(Project.organization_id == org.id, Project.slug == "playground"))
        ).scalars().first()
        if project is None:
            project = Project(organization_id=org.id, name="Playground", slug="playground")
            session.add(project)
            await session.flush()
    else:
        project = await session.get(Project, body.project_id)
        if project is None:
            raise PlatformError("invalid_request", "Project was not found.", 404)
        await assert_org(session, user, project.organization_id)
    linked = (
        await session.execute(
            select(ProjectModel).where(ProjectModel.project_id == project.id, ProjectModel.model_id == model.id)
        )
    ).scalar_one_or_none()
    if linked is None:
        session.add(ProjectModel(project_id=project.id, model_id=model.id))
        await session.flush()
    raw, prefix, digest = generate_api_key()
    ephemeral = ApiKey(project_id=project.id, name="playground", key_prefix=prefix, key_hash=digest, status="active")
    session.add(ephemeral)
    await session.commit()
    await session.refresh(ephemeral)
    payload = body.model_dump()
    try:
        if body.stream:
            async def events():
                try:
                    async for line in stream_chat(session, ephemeral, project, payload):
                        yield line
                finally:
                    ephemeral.status = "revoked"
                    await session.commit()

            return StreamingResponse(events(), media_type="text/event-stream")
        result = await complete_chat(session, ephemeral, project, payload)
        ephemeral.status = "revoked"
        await session.commit()
        return JSONResponse(result)
    except PlatformError:
        ephemeral.status = "revoked"
        await session.commit()
        raise
