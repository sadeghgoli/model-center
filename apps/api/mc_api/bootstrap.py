import asyncio

from sqlalchemy import select

from mc_api.services import bootstrap_admin
from mc_shared.db import SessionLocal, get_engine, init_db
from mc_shared.models import User
from mc_shared.settings import get_settings


async def main() -> None:
    settings = get_settings()
    init_db()
    async with get_engine().begin() as connection:
        from mc_shared.db import Base

        await connection.run_sync(Base.metadata.create_all)
    if SessionLocal is None:
        return
    async with SessionLocal() as session:
        await bootstrap_admin(session, settings.default_admin_email.strip(), settings.default_admin_password)
        admin = (await session.execute(select(User).where(User.role == "SUPER_ADMIN"))).scalar_one_or_none()
        if admin is not None:
            print(f"super admin ready: {admin.email}")


if __name__ == "__main__":
    asyncio.run(main())
