import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mc_gateway.gateway import authenticate_key, complete_chat, stream_chat, stream_speech_audio, stream_voice_chat, transcribe_audio
from mc_shared.db import get_session
from mc_shared.errors import PlatformError
from mc_shared.models import Model, ProjectModel

router = APIRouter()
_bearer = HTTPBearer(auto_error=False)


class ChatBody(BaseModel):
    model: str
    messages: list[dict] = Field(default_factory=list)
    stream: bool = False
    tools: list | None = None
    tool_choice: object | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    response_format: dict | None = None

    model_config = {"extra": "allow"}


class SpeechBody(BaseModel):
    model: str
    input: str
    voice: str = "alloy"
    response_format: str = "mp3"


async def _lead(iterator: AsyncIterator):
    try:
        return await anext(iterator)
    except StopAsyncIteration:
        return None


async def _rest(first, iterator: AsyncIterator):
    if first:
        yield first
    async for item in iterator:
        yield item


def _audio_type(response_format: str) -> str:
    if response_format == "mp3":
        return "audio/mpeg"
    return "application/octet-stream"


def _history(raw: str) -> list:
    try:
        parsed = json.loads(raw or "[]")
    except json.JSONDecodeError as exc:
        raise PlatformError("invalid_request", "messages must be JSON.", 400) from exc
    if not isinstance(parsed, list):
        raise PlatformError("invalid_request", "messages must be a list.", 400)
    return parsed


async def _key(credentials: HTTPAuthorizationCredentials | None, session: AsyncSession):
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise PlatformError("invalid_api_key", "API key is invalid.", 401)
    return await authenticate_key(session, credentials.credentials)


@router.get("/v1/models")
async def list_models(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    _api_key, project = await _key(credentials, session)
    rows = (
        await session.execute(
            select(Model).join(ProjectModel, ProjectModel.model_id == Model.id).where(ProjectModel.project_id == project.id, Model.is_active.is_(True))
        )
    ).scalars().all()
    return JSONResponse(
        {
            "object": "list",
            "data": [
                {"id": row.slug, "object": "model", "owned_by": row.provider_name or "model-center"}
                for row in rows
            ],
        }
    )


@router.post("/v1/chat/completions")
async def chat(
    body: ChatBody,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    session: AsyncSession = Depends(get_session),
):
    api_key, project = await _key(credentials, session)
    payload = body.model_dump()
    if body.stream:
        return StreamingResponse(stream_chat(session, api_key, project, payload), media_type="text/event-stream")
    return JSONResponse(await complete_chat(session, api_key, project, payload))


@router.post("/v1/audio/transcriptions")
async def transcriptions(
    file: UploadFile = File(...),
    model: str = Form(...),
    language: str | None = Form(None),
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    session: AsyncSession = Depends(get_session),
):
    api_key, project = await _key(credentials, session)
    text = await transcribe_audio(
        session,
        api_key,
        project,
        {"model": model, "language": language or None},
        audio=await file.read(),
        filename=file.filename or "audio.webm",
        content_type=file.content_type or "application/octet-stream",
    )
    return JSONResponse({"text": text})


@router.post("/v1/audio/speech")
async def speech(
    body: SpeechBody,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    session: AsyncSession = Depends(get_session),
):
    api_key, project = await _key(credentials, session)
    chunks = stream_speech_audio(session, api_key, project, body.model_dump())
    first = await _lead(chunks)
    return StreamingResponse(_rest(first, chunks), media_type=_audio_type(body.response_format))


@router.post("/v1/audio/chat")
async def audio_chat(
    file: UploadFile = File(...),
    model: str = Form(...),
    stt_model: str = Form(...),
    tts_model: str = Form(...),
    messages: str = Form("[]"),
    voice: str = Form("alloy"),
    language: str = Form("fa"),
    temperature: float | None = Form(None),
    max_tokens: int | None = Form(None),
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    session: AsyncSession = Depends(get_session),
):
    api_key, project = await _key(credentials, session)
    payload = {
        "model": model,
        "stt_model": stt_model,
        "tts_model": tts_model,
        "messages": _history(messages),
        "voice": voice,
        "language": language,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    events = stream_voice_chat(
        session,
        api_key,
        project,
        payload,
        audio=await file.read(),
        filename=file.filename or "audio.webm",
        content_type=file.content_type or "application/octet-stream",
    )
    first = await _lead(events)
    return StreamingResponse(
        _rest(first, events),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
