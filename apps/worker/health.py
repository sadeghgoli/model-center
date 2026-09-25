import asyncio
from datetime import UTC, datetime

from sqlalchemy import select

from mc_api.services import check_runtime_health
from mc_shared.db import SessionLocal, init_db
from mc_shared.models import Deployment, Runtime


async def tick() -> None:
    init_db()
    assert SessionLocal is not None
    async with SessionLocal() as session:
        runtimes = (await session.execute(select(Runtime))).scalars().all()
        for runtime in runtimes:
            result = await check_runtime_health(session, runtime)
            deployments = (
                await session.execute(select(Deployment).where(Deployment.runtime_id == runtime.id, Deployment.status == "running"))
            ).scalars().all()
            for deployment in deployments:
                deployment.health_status = "unhealthy" if result["status"] != "online" else "online"
                deployment.last_health_check = datetime.now(UTC)
        await session.commit()


async def main() -> None:
    while True:
        try:
            await tick()
        except Exception:
            pass
        await asyncio.sleep(30)


if __name__ == "__main__":
    asyncio.run(main())
