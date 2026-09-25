from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from mc_shared.settings import get_settings

_engine = None
SessionLocal: async_sessionmaker[AsyncSession] | None = None


class Base(DeclarativeBase):
    pass


def init_db(url: str | None = None) -> None:
    global _engine, SessionLocal
    database_url = url or get_settings().database_url
    _engine = create_async_engine(database_url, pool_pre_ping=True)
    SessionLocal = async_sessionmaker(_engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    if SessionLocal is None:
        init_db()
    assert SessionLocal is not None
    async with SessionLocal() as session:
        yield session


def get_engine():
    if _engine is None:
        init_db()
    return _engine
