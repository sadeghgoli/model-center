import os
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

os.environ.setdefault("JWT_SECRET", "test-secret-key-must-be-long-enough")
os.environ.setdefault("AI_PLATFORM_SECRET", "test-platform-secret-value")
os.environ.setdefault("REDIS_URL", "")
os.environ.setdefault("DEFAULT_ADMIN_EMAIL", "")
os.environ.setdefault("DEFAULT_ADMIN_PASSWORD", "")

from mc_api.main import app  # noqa: E402
from mc_auth.passwords import hash_password  # noqa: E402
from mc_gateway.limiter import reset_memory_limits  # noqa: E402
from mc_shared import db as database
from mc_shared.db import Base
from mc_shared.models import User  # noqa: E402


@pytest.fixture
async def client(tmp_path: Path):
    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{tmp_path}/db.sqlite"
    database.init_db(os.environ["DATABASE_URL"])
    async with database.get_engine().begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
    assert database.SessionLocal is not None
    async with database.SessionLocal() as session:
        session.add(
            User(
                email="admin@example.com",
                username="admin",
                password_hash=hash_password("password-1"),
                role="SUPER_ADMIN",
                is_active=True,
            )
        )
        session.add(
            User(
                email="user@example.com",
                username="user",
                password_hash=hash_password("password-1"),
                role="USER",
                is_active=True,
            )
        )
        await session.commit()
    reset_memory_limits()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        yield http
    reset_memory_limits()


async def token(client: AsyncClient, email: str = "admin@example.com") -> str:
    response = await client.post("/api/v1/auth/login", json={"email": email, "password": "password-1"})
    assert response.status_code == 200
    return response.json()["data"]["access_token"]


def auth(value: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {value}"}
