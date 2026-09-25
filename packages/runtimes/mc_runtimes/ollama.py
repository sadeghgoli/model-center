import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from mc_shared.errors import PlatformError
from mc_runtimes.base import ModelRuntime
from mc_runtimes.openai_compatible import chunk, completion


class OllamaRuntime(ModelRuntime):
    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _payload(self, deployment: dict[str, Any], request: dict[str, Any], stream: bool) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": deployment["runtime_model_name"],
            "messages": request.get("messages") or [],
            "stream": stream,
            "think": False,
        }
        if request.get("tools") is not None:
            body["tools"] = request["tools"]
        options = {}
        if request.get("temperature") is not None:
            options["temperature"] = request["temperature"]
        if request.get("max_tokens") is not None:
            options["num_predict"] = request["max_tokens"]
        if options:
            body["options"] = options
        return body

    async def health_check(self, deployment: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(f"{self.endpoint}/api/tags", headers=self._headers())
            if response.status_code >= 400:
                return {"status": "unhealthy", "detail": response.text[:200]}
            return {"status": "online"}
        except httpx.TimeoutException:
            return {"status": "offline", "detail": "timeout"}
        except httpx.HTTPError as exc:
            return {"status": "offline", "detail": str(exc)}

    async def list_models(self) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(f"{self.endpoint}/api/tags", headers=self._headers())
        response.raise_for_status()
        return response.json().get("models") or []

    async def chat(self, deployment: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.endpoint}/api/chat",
                    headers=self._headers(),
                    json=self._payload(deployment, request, False),
                )
        except httpx.TimeoutException as exc:
            raise PlatformError("timeout", "Runtime timed out.", 504) from exc
        except httpx.HTTPError as exc:
            raise PlatformError("runtime_unavailable", "Runtime is unavailable.", 503) from exc
        if response.status_code >= 400:
            raise PlatformError("runtime_unavailable", "Runtime rejected the request.", 503)
        message = response.json().get("message") or {}
        text = message.get("content") or message.get("thinking") or ""
        return completion(
            str(request.get("model") or ""),
            text,
            message.get("tool_calls"),
            None,
        )

    async def stream_chat(
        self, deployment: dict[str, Any], request: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        model = str(request.get("model") or "")
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                async with client.stream(
                    "POST",
                    f"{self.endpoint}/api/chat",
                    headers=self._headers(),
                    json=self._payload(deployment, request, True),
                ) as response:
                    if response.status_code >= 400:
                        raise PlatformError("runtime_unavailable", "Runtime rejected the request.", 503)
                    async for line in response.aiter_lines():
                        if not line:
                            continue
                        parsed = json.loads(line)
                        message = parsed.get("message") or {}
                        content = message.get("content") or ""
                        if not content and parsed.get("done"):
                            content = message.get("thinking") or ""
                        if content:
                            yield chunk(model, content)
                        if parsed.get("done"):
                            yield chunk(model, "", "stop")
        except PlatformError:
            raise
        except httpx.TimeoutException as exc:
            raise PlatformError("timeout", "Runtime timed out.", 504) from exc
        except httpx.HTTPError as exc:
            raise PlatformError("runtime_unavailable", "Runtime is unavailable.", 503) from exc
