from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any


class ModelRuntime(ABC):
    def __init__(self, endpoint: str, api_key: str = "", timeout: float = 60) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    async def deploy(self, deployment: dict[str, Any]) -> dict[str, Any]:
        return {"accepted": True, "mode": "existing_runtime_model", "deployment": deployment["slug"]}

    async def undeploy(self, deployment: dict[str, Any]) -> dict[str, Any]:
        return {"accepted": True, "deployment": deployment["slug"]}

    @abstractmethod
    async def health_check(self, deployment: dict[str, Any] | None = None) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    async def chat(self, deployment: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    async def stream_chat(
        self, deployment: dict[str, Any], request: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        raise NotImplementedError

    async def list_models(self) -> list[dict[str, Any]]:
        return []

    async def get_model_info(self, deployment: dict[str, Any]) -> dict[str, Any]:
        return {"runtime_model_name": deployment.get("runtime_model_name", "")}

    async def get_metrics(self, deployment: dict[str, Any] | None = None) -> dict[str, Any]:
        health = await self.health_check(deployment)
        return {"health": health.get("status", "unknown")}
