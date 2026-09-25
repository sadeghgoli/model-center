from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mc_gateway.gateway import authenticate_key, complete_chat, stream_chat
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
