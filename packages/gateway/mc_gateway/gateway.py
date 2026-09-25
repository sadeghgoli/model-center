import time
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mc_auth.api_keys import hash_api_key
from mc_gateway.limiter import enforce_limits
from mc_router.router import resolve_route
from mc_runtimes.factory import build_runtime
from mc_shared.errors import PlatformError
from mc_shared.models import ApiKey, ApiKeyModel, Deployment, Model, Project, ProjectModel, Runtime, UsageLog


def _limits(project: Project, api_key: ApiKey) -> tuple[int, int, int, int]:
    return (
        api_key.rpm_limit or project.rpm_limit,
        api_key.tpm_limit or project.tpm_limit,
        api_key.daily_request_limit or project.daily_request_limit,
        api_key.monthly_request_limit or project.monthly_request_limit,
    )


async def authenticate_key(session: AsyncSession, raw_key: str) -> tuple[ApiKey, Project]:
    if not raw_key.startswith("sk-gsm-"):
        raise PlatformError("invalid_api_key", "API key is invalid.", 401)
    record = (
        await session.execute(select(ApiKey).where(ApiKey.key_hash == hash_api_key(raw_key)))
    ).scalar_one_or_none()
    if record is None or record.status != "active" or record.revoked_at is not None:
        raise PlatformError("invalid_api_key", "API key is invalid.", 401)
    if record.expires_at is not None and record.expires_at < datetime.now(UTC):
        raise PlatformError("invalid_api_key", "API key has expired.", 401)
    project = await session.get(Project, record.project_id)
    if project is None:
        raise PlatformError("invalid_api_key", "API key is invalid.", 401)
    return record, project


async def assert_model_allowed(session: AsyncSession, api_key: ApiKey, project: Project, model: Model) -> None:
    project_allowed = (
        await session.execute(
            select(ProjectModel.model_id).where(ProjectModel.project_id == project.id, ProjectModel.model_id == model.id)
        )
    ).scalar_one_or_none()
    if project_allowed is None:
        raise PlatformError("model_not_allowed", "Project cannot use this model.", 403)
    key_models = (
        await session.execute(select(ApiKeyModel.model_id).where(ApiKeyModel.api_key_id == api_key.id))
    ).scalars().all()
    if key_models and model.id not in key_models:
        raise PlatformError("model_not_allowed", "API key cannot use this model.", 403)


def _estimate_prompt_tokens(request: dict) -> int:
    text = " ".join(str(item.get("content") or "") for item in request.get("messages") or [])
    return max(1, len(text) // 4)


async def _record(
    session: AsyncSession,
    *,
    project: Project,
    api_key: ApiKey | None,
    model: Model | None,
    deployment: Deployment | None,
    runtime: Runtime | None,
    request_id: str,
    endpoint: str,
    prompt_tokens: int,
    completion_tokens: int,
    latency_ms: int,
    ttft_ms: int | None,
    status_code: int,
    streaming: bool,
    error_type: str | None,
) -> None:
    session.add(
        UsageLog(
            organization_id=project.organization_id,
            project_id=project.id,
            api_key_id=None if api_key is None else api_key.id,
            model_id=None if model is None else model.id,
            deployment_id=None if deployment is None else deployment.id,
            runtime_id=None if runtime is None else runtime.id,
            request_id=request_id,
            endpoint=endpoint,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            latency_ms=latency_ms,
            time_to_first_token_ms=ttft_ms,
            status_code=status_code,
            streaming=streaming,
            error_type=error_type,
        )
    )
    if api_key is not None:
        api_key.last_used_at = datetime.now(UTC)
    await session.commit()


async def prepare_chat(session: AsyncSession, api_key: ApiKey, project: Project, request: dict) -> tuple[Model, Deployment, Runtime]:
    model, deployment, runtime = await resolve_route(session, str(request.get("model") or ""))
    await assert_model_allowed(session, api_key, project, model)
    rpm, tpm, daily, monthly = _limits(project, api_key)
    await enforce_limits(
        key_id=str(api_key.id),
        project_id=str(project.id),
        rpm=rpm,
        tpm=tpm,
        daily=daily,
        monthly=monthly,
        tokens=_estimate_prompt_tokens(request),
    )
    return model, deployment, runtime


def _deployment_payload(deployment: Deployment) -> dict:
    return {
        "slug": deployment.slug,
        "runtime_model_name": deployment.runtime_model_name,
        "configuration": deployment.configuration or {},
    }


async def complete_chat(session: AsyncSession, api_key: ApiKey, project: Project, request: dict) -> dict:
    request_id = str(uuid.uuid4())
    started = time.perf_counter()
    model = deployment = runtime = None
    try:
        model, deployment, runtime = await prepare_chat(session, api_key, project, request)
        adapter = build_runtime(runtime)
        payload = await adapter.chat(_deployment_payload(deployment), request)
        usage = payload.get("usage") or {}
        await _record(
            session,
            project=project,
            api_key=api_key,
            model=model,
            deployment=deployment,
            runtime=runtime,
            request_id=request_id,
            endpoint="/v1/chat/completions",
            prompt_tokens=int(usage.get("prompt_tokens") or 0),
            completion_tokens=int(usage.get("completion_tokens") or 0),
            latency_ms=int((time.perf_counter() - started) * 1000),
            ttft_ms=None,
            status_code=200,
            streaming=False,
            error_type=None,
        )
        return payload
    except PlatformError as exc:
        if project is not None:
            await _record(
                session,
                project=project,
                api_key=api_key,
                model=model,
                deployment=deployment,
                runtime=runtime,
                request_id=request_id,
                endpoint="/v1/chat/completions",
                prompt_tokens=0,
                completion_tokens=0,
                latency_ms=int((time.perf_counter() - started) * 1000),
                ttft_ms=None,
                status_code=exc.status_code,
                streaming=False,
                error_type=exc.code,
            )
        raise


async def stream_chat(session: AsyncSession, api_key: ApiKey, project: Project, request: dict) -> AsyncIterator[str]:
    import json

    request_id = str(uuid.uuid4())
    started = time.perf_counter()
    ttft: int | None = None
    completion_text = ""
    model, deployment, runtime = await prepare_chat(session, api_key, project, request)
    adapter = build_runtime(runtime)
    try:
        async for item in adapter.stream_chat(_deployment_payload(deployment), request):
            if ttft is None:
                ttft = int((time.perf_counter() - started) * 1000)
            for choice in item.get("choices") or []:
                completion_text += str((choice.get("delta") or {}).get("content") or "")
            yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"
        await _record(
            session,
            project=project,
            api_key=api_key,
            model=model,
            deployment=deployment,
            runtime=runtime,
            request_id=request_id,
            endpoint="/v1/chat/completions",
            prompt_tokens=_estimate_prompt_tokens(request),
            completion_tokens=max(1, len(completion_text) // 4),
            latency_ms=int((time.perf_counter() - started) * 1000),
            ttft_ms=ttft,
            status_code=200,
            streaming=True,
            error_type=None,
        )
    except PlatformError as exc:
        await _record(
            session,
            project=project,
            api_key=api_key,
            model=model,
            deployment=deployment,
            runtime=runtime,
            request_id=request_id,
            endpoint="/v1/chat/completions",
            prompt_tokens=0,
            completion_tokens=0,
            latency_ms=int((time.perf_counter() - started) * 1000),
            ttft_ms=ttft,
            status_code=exc.status_code,
            streaming=True,
            error_type=exc.code,
        )
        raise
