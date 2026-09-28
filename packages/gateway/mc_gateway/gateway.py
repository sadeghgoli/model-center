import asyncio
import base64
import contextlib
import json
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


_SENTENCE_BREAKS = set(".!?؟\n")
_SENTENCE_FLUSH = 120


def take_sentences(buffer: str) -> tuple[list[str], str]:
    sentences: list[str] = []
    start = 0
    index = 0
    while index < len(buffer):
        char = buffer[index]
        if char in _SENTENCE_BREAKS:
            piece = buffer[start : index + 1].strip()
            if any(item.isalnum() for item in piece):
                sentences.append(piece)
            start = index + 1
        elif index - start >= _SENTENCE_FLUSH and char.isspace():
            piece = buffer[start:index].strip()
            if any(item.isalnum() for item in piece):
                sentences.append(piece)
            start = index + 1
        index += 1
    return sentences, buffer[start:]


def _event(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _unwrap(exc: BaseException) -> BaseException:
    if isinstance(exc, BaseExceptionGroup):
        for item in exc.exceptions:
            found = _unwrap(item)
            if isinstance(found, PlatformError):
                return found
        return _unwrap(exc.exceptions[0])
    return exc


async def _open_model(
    session: AsyncSession, api_key: ApiKey, project: Project, slug: str
) -> tuple[Model, Deployment, Runtime]:
    model, deployment, runtime = await resolve_route(session, slug)
    await assert_model_allowed(session, api_key, project, model)
    return model, deployment, runtime


async def _limit(api_key: ApiKey, project: Project, tokens: int) -> None:
    rpm, tpm, daily, monthly = _limits(project, api_key)
    await enforce_limits(
        key_id=str(api_key.id),
        project_id=str(project.id),
        rpm=rpm,
        tpm=tpm,
        daily=daily,
        monthly=monthly,
        tokens=tokens,
    )


async def prepare_chat(session: AsyncSession, api_key: ApiKey, project: Project, request: dict) -> tuple[Model, Deployment, Runtime]:
    model, deployment, runtime = await _open_model(session, api_key, project, str(request.get("model") or ""))
    await _limit(api_key, project, _estimate_prompt_tokens(request))
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


async def transcribe_audio(
    session: AsyncSession,
    api_key: ApiKey,
    project: Project,
    request: dict,
    *,
    audio: bytes,
    filename: str,
    content_type: str,
) -> str:
    request_id = str(uuid.uuid4())
    started = time.perf_counter()
    model = deployment = runtime = None
    try:
        if not audio:
            raise PlatformError("invalid_request", "Audio file is empty.", 400)
        model, deployment, runtime = await _open_model(session, api_key, project, str(request.get("model") or ""))
        await _limit(api_key, project, max(1, len(audio) // 64))
        payload = await build_runtime(runtime).transcribe(
            _deployment_payload(deployment),
            audio=audio,
            filename=filename or "audio.webm",
            content_type=content_type or "application/octet-stream",
            language=request.get("language") or None,
        )
        text = str(payload.get("text") or "").strip()
        await _record(
            session,
            project=project,
            api_key=api_key,
            model=model,
            deployment=deployment,
            runtime=runtime,
            request_id=request_id,
            endpoint="/v1/audio/transcriptions",
            prompt_tokens=max(1, len(audio) // 64),
            completion_tokens=max(1, len(text) // 4),
            latency_ms=int((time.perf_counter() - started) * 1000),
            ttft_ms=None,
            status_code=200,
            streaming=False,
            error_type=None,
        )
        return text
    except PlatformError as exc:
        await _record(
            session,
            project=project,
            api_key=api_key,
            model=model,
            deployment=deployment,
            runtime=runtime,
            request_id=request_id,
            endpoint="/v1/audio/transcriptions",
            prompt_tokens=0,
            completion_tokens=0,
            latency_ms=int((time.perf_counter() - started) * 1000),
            ttft_ms=None,
            status_code=exc.status_code,
            streaming=False,
            error_type=exc.code,
        )
        raise


async def stream_speech_audio(
    session: AsyncSession, api_key: ApiKey, project: Project, request: dict
) -> AsyncIterator[bytes]:
    request_id = str(uuid.uuid4())
    started = time.perf_counter()
    model = deployment = runtime = None
    text = str(request.get("input") or "")
    try:
        if not text.strip():
            raise PlatformError("invalid_request", "input is required.", 400)
        model, deployment, runtime = await _open_model(session, api_key, project, str(request.get("model") or ""))
        await _limit(api_key, project, max(1, len(text) // 4))
        async for chunk in build_runtime(runtime).stream_speech(
            _deployment_payload(deployment),
            text=text,
            voice=str(request.get("voice") or "alloy"),
            response_format=str(request.get("response_format") or "mp3"),
        ):
            yield chunk
        await _record(
            session,
            project=project,
            api_key=api_key,
            model=model,
            deployment=deployment,
            runtime=runtime,
            request_id=request_id,
            endpoint="/v1/audio/speech",
            prompt_tokens=max(1, len(text) // 4),
            completion_tokens=0,
            latency_ms=int((time.perf_counter() - started) * 1000),
            ttft_ms=None,
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
            endpoint="/v1/audio/speech",
            prompt_tokens=0,
            completion_tokens=0,
            latency_ms=int((time.perf_counter() - started) * 1000),
            ttft_ms=None,
            status_code=exc.status_code,
            streaming=True,
            error_type=exc.code,
        )
        raise


async def stream_voice_chat(
    session: AsyncSession,
    api_key: ApiKey,
    project: Project,
    request: dict,
    *,
    audio: bytes,
    filename: str,
    content_type: str,
) -> AsyncIterator[str]:
    request_id = str(uuid.uuid4())
    started = time.perf_counter()
    chat_model = chat_deployment = chat_runtime = None
    producer: asyncio.Task | None = None
    try:
        if not audio:
            raise PlatformError("invalid_request", "Audio file is empty.", 400)
        chat_model, chat_deployment, chat_runtime = await _open_model(session, api_key, project, str(request.get("model") or ""))
        _stt_model, stt_deployment, stt_runtime = await _open_model(session, api_key, project, str(request.get("stt_model") or ""))
        _tts_model, tts_deployment, tts_runtime = await _open_model(session, api_key, project, str(request.get("tts_model") or ""))
        history = [item for item in (request.get("messages") or []) if isinstance(item, dict)]
        await _limit(api_key, project, _estimate_prompt_tokens({"messages": history}) + max(1, len(audio) // 64))
        transcript_payload = await build_runtime(stt_runtime).transcribe(
            _deployment_payload(stt_deployment),
            audio=audio,
            filename=filename or "audio.webm",
            content_type=content_type or "application/octet-stream",
            language=request.get("language") or None,
        )
        transcript = str(transcript_payload.get("text") or "").strip()
        if not transcript:
            raise PlatformError("invalid_request", "Speech was not recognized.", 400)
        yield _event({"type": "transcript", "text": transcript})

        chat_request = {"model": request.get("model"), "messages": [*history, {"role": "user", "content": transcript}]}
        for key in ("temperature", "max_tokens", "tools", "tool_choice"):
            if request.get(key) is not None:
                chat_request[key] = request[key]
        events: asyncio.Queue = asyncio.Queue()
        sentences: asyncio.Queue = asyncio.Queue()
        completion_text = ""
        ttft: int | None = None
        chat_adapter = build_runtime(chat_runtime)
        tts_adapter = build_runtime(tts_runtime)
        voice = str(request.get("voice") or "alloy")
        response_format = str(request.get("response_format") or "mp3")

        async def read_llm() -> None:
            nonlocal completion_text, ttft
            buffer = ""
            async for item in chat_adapter.stream_chat(_deployment_payload(chat_deployment), chat_request):
                if ttft is None:
                    ttft = int((time.perf_counter() - started) * 1000)
                delta = ""
                for choice in item.get("choices") or []:
                    delta += str((choice.get("delta") or {}).get("content") or "")
                if not delta:
                    continue
                completion_text += delta
                await events.put({"type": "text", "delta": delta})
                buffer += delta
                ready, buffer = take_sentences(buffer)
                for sentence in ready:
                    await sentences.put(sentence)
            tail = buffer.strip()
            if any(item.isalnum() for item in tail):
                await sentences.put(tail)
            await sentences.put(None)

        async def speak() -> None:
            while True:
                sentence = await sentences.get()
                if sentence is None:
                    break
                spoken = bytearray()
                async for chunk in tts_adapter.stream_speech(
                    _deployment_payload(tts_deployment),
                    text=sentence,
                    voice=voice,
                    response_format=response_format,
                ):
                    spoken.extend(chunk)
                if spoken:
                    await events.put(
                        {
                            "type": "audio",
                            "format": response_format or "mp3",
                            "text": sentence,
                            "audio": base64.b64encode(bytes(spoken)).decode("ascii"),
                        }
                    )

        async def produce() -> None:
            try:
                async with asyncio.TaskGroup() as group:
                    group.create_task(read_llm())
                    group.create_task(speak())
            except Exception as exc:
                await events.put({"type": "error", "error": _unwrap(exc)})
            await events.put({"type": "done"})

        producer = asyncio.create_task(produce())
        failure: BaseException | None = None
        while True:
            event = await events.get()
            kind = event.get("type")
            if kind == "done":
                break
            if kind == "error":
                failure = event.get("error")
                continue
            if failure is None:
                yield _event(event)
        if failure is not None:
            if isinstance(failure, PlatformError):
                raise failure
            raise PlatformError("runtime_unavailable", "Runtime is unavailable.", 503) from failure
        yield "data: [DONE]\n\n"
        await _record(
            session,
            project=project,
            api_key=api_key,
            model=chat_model,
            deployment=chat_deployment,
            runtime=chat_runtime,
            request_id=request_id,
            endpoint="/v1/audio/chat",
            prompt_tokens=_estimate_prompt_tokens({"messages": [*history, {"role": "user", "content": transcript}]}),
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
            model=chat_model,
            deployment=chat_deployment,
            runtime=chat_runtime,
            request_id=request_id,
            endpoint="/v1/audio/chat",
            prompt_tokens=0,
            completion_tokens=0,
            latency_ms=int((time.perf_counter() - started) * 1000),
            ttft_ms=None,
            status_code=exc.status_code,
            streaming=True,
            error_type=exc.code,
        )
        raise
    finally:
        if producer is not None and not producer.done():
            producer.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await producer
