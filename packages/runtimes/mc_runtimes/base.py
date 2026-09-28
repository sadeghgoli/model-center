from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any

from mc_shared.errors import PlatformError


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

    async def _audio_unsupported(self) -> None:
        raise PlatformError("runtime_unavailable", "This runtime does not support audio.", 503)

    async def transcribe(
        self,
        deployment: dict[str, Any],
        *,
        audio: bytes,
        filename: str,
        content_type: str,
        language: str | None = None,
    ) -> dict[str, Any]:
        await self._audio_unsupported()
        return {}

    async def stream_speech(
        self,
        deployment: dict[str, Any],
        *,
        text: str,
        voice: str,
        response_format: str = "mp3",
    ) -> AsyncIterator[bytes]:
        await self._audio_unsupported()
        yield b""

    async def list_models(self) -> list[dict[str, Any]]:
        return []

    async def get_model_info(self, deployment: dict[str, Any]) -> dict[str, Any]:
        return {"runtime_model_name": deployment.get("runtime_model_name", "")}

    async def get_metrics(self, deployment: dict[str, Any] | None = None) -> dict[str, Any]:
        health = await self.health_check(deployment)
        return {"health": health.get("status", "unknown")}
