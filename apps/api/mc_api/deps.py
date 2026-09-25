import uuid

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mc_auth.tokens import decode_token
from mc_shared.db import get_session
from mc_shared.errors import PlatformError
from mc_shared.models import User

_bearer = HTTPBearer(auto_error=False)
_revoked: set[str] = set()


async def revoke_jti(jti: str) -> None:
    _revoked.add(jti)


def is_revoked(jti: str) -> bool:
    return jti in _revoked


async def current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    session: AsyncSession = Depends(get_session),
) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise PlatformError("invalid_request", "Authentication is required.", 401)
    payload = decode_token(credentials.credentials, "access")
    if is_revoked(payload["jti"]):
        raise PlatformError("invalid_request", "Token has been revoked.", 401)
    user = await session.get(User, uuid.UUID(payload["sub"]))
    if user is None or not user.is_active:
        raise PlatformError("invalid_request", "Token is invalid.", 401)
    return user


async def optional_org_filter(session: AsyncSession, user: User):
    if user.role == "SUPER_ADMIN":
        return None
    from mc_shared.models import OrganizationUser

    return list(
        (await session.execute(select(OrganizationUser.organization_id).where(OrganizationUser.user_id == user.id))).scalars().all()
    )
