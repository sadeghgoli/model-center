from collections.abc import AsyncIterator
from typing import Any

from mc_shared.errors import PlatformError
from mc_runtimes.base import ModelRuntime


class LocalRuntime(ModelRuntime):
    """Placeholder for a future in-process inference engine."""

    async def health_check(self, deployment: dict[str, Any] | None = None) -> dict[str, Any]:
        return {"status": "offline", "detail": "Local inference engine is not installed."}

    async def chat(self, deployment: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
        raise PlatformError("runtime_unavailable", "Local inference engine is not installed.", 503)

    async def stream_chat(
        self, deployment: dict[str, Any], request: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        raise PlatformError("runtime_unavailable", "Local inference engine is not installed.", 503)
        yield {}
