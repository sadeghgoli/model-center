from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mc_shared.errors import PlatformError
from mc_shared.models import Deployment, Model, Runtime


async def resolve_route(session: AsyncSession, model_slug: str) -> tuple[Model, Deployment, Runtime]:
    model = (
        await session.execute(select(Model).where(Model.slug == model_slug, Model.is_active.is_(True)))
    ).scalar_one_or_none()
    if model is None:
        raise PlatformError("model_not_found", "Model was not found.", 404)
    rows = (
        await session.execute(
            select(Deployment, Runtime)
            .join(Runtime, Runtime.id == Deployment.runtime_id)
            .where(Deployment.model_id == model.id, Deployment.status == "running")
            .order_by(Deployment.created_at)
        )
    ).all()
    for deployment, runtime in rows:
        if deployment.health_status in {"unhealthy", "offline"} or runtime.health_status in {"unhealthy", "offline"}:
            continue
        return model, deployment, runtime
    raise PlatformError("deployment_unavailable", "No healthy deployment is available.", 503)
