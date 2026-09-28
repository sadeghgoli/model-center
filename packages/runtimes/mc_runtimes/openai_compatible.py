import json
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx

from mc_shared.errors import PlatformError
from mc_runtimes.base import ModelRuntime


def completion(model: str, content: str, tool_calls: list | None, usage: dict | None) -> dict[str, Any]:
    prompt = int((usage or {}).get("prompt_tokens") or 0)
    completion_tokens = int((usage or {}).get("completion_tokens") or max(1, len(content) // 4))
    if prompt == 0:
        prompt = 1
    message: dict[str, Any] = {"role": "assistant", "content": content}
    if tool_calls:
        message["tool_calls"] = tool_calls
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:24]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": message,
                "finish_reason": "tool_calls" if tool_calls else "stop",
            }
        ],
        "usage": {
            "prompt_tokens": prompt,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt + completion_tokens,
        },
    }


def chunk(model: str, content: str, finish: str | None = None, reasoning: str = "") -> dict[str, Any]:
    delta: dict[str, Any] = {"content": content} if content else {}
    if reasoning:
        delta["reasoning_content"] = reasoning
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
    }


class OpenAICompatibleRuntime(ModelRuntime):
    def _root(self) -> str:
        if self.endpoint.endswith("/v1"):
            return self.endpoint
        return f"{self.endpoint}/v1"

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _body(self, deployment: dict[str, Any], request: dict[str, Any], stream: bool) -> dict[str, Any]:
        body = {
            "model": deployment["runtime_model_name"],
            "messages": request.get("messages") or [],
            "stream": stream,
        }
        for key in ("tools", "tool_choice", "temperature", "max_tokens", "response_format"):
            if request.get(key) is not None:
                body[key] = request[key]
        return body

    async def health_check(self, deployment: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(f"{self._root()}/models", headers=self._headers())
            if response.status_code >= 400:
                return {"status": "unhealthy", "detail": response.text[:200]}
            return {"status": "online"}
        except httpx.TimeoutException:
            return {"status": "offline", "detail": "timeout"}
        except httpx.HTTPError as exc:
            return {"status": "offline", "detail": str(exc)}

    async def chat(self, deployment: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self._root()}/chat/completions",
                    headers=self._headers(),
                    json=self._body(deployment, request, False),
                )
        except httpx.TimeoutException as exc:
            raise PlatformError("timeout", "Runtime timed out.", 504) from exc
        except httpx.HTTPError as exc:
            raise PlatformError("runtime_unavailable", "Runtime is unavailable.", 503) from exc
        if response.status_code >= 400:
            raise PlatformError("runtime_unavailable", "Runtime rejected the request.", 503)
        payload = response.json()
        payload["model"] = request.get("model") or payload.get("model")
        return payload

    async def stream_chat(
        self, deployment: dict[str, Any], request: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        public_model = str(request.get("model") or "")
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                async with client.stream(
                    "POST",
                    f"{self._root()}/chat/completions",
                    headers=self._headers(),
                    json=self._body(deployment, request, True),
                ) as response:
                    if response.status_code >= 400:
                        raise PlatformError("runtime_unavailable", "Runtime rejected the request.", 503)
                    async for line in response.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        data = line.removeprefix("data:").strip()
                        if data == "[DONE]":
                            break
                        parsed = json.loads(data)
                        parsed["model"] = public_model or parsed.get("model")
                        yield parsed
        except PlatformError:
            raise
        except httpx.TimeoutException as exc:
            raise PlatformError("timeout", "Runtime timed out.", 504) from exc
        except httpx.HTTPError as exc:
            raise PlatformError("runtime_unavailable", "Runtime is unavailable.", 503) from exc

    def _auth_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def transcribe(
        self,
        deployment: dict[str, Any],
        *,
        audio: bytes,
        filename: str,
        content_type: str,
        language: str | None = None,
    ) -> dict[str, Any]:
        form = {"model": deployment["runtime_model_name"]}
        if language:
            form["language"] = language
        files = {"file": (filename or "audio.webm", audio, content_type or "application/octet-stream")}
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self._root()}/audio/transcriptions",
                    headers=self._auth_headers(),
                    data=form,
                    files=files,
                )
        except httpx.TimeoutException as exc:
            raise PlatformError("timeout", "Runtime timed out.", 504) from exc
        except httpx.HTTPError as exc:
            raise PlatformError("runtime_unavailable", "Runtime is unavailable.", 503) from exc
        if response.status_code >= 400:
            raise PlatformError("runtime_unavailable", "Runtime rejected the request.", 503)
        payload = response.json()
        text = payload.get("text") if isinstance(payload, dict) else payload
        return {"text": str(text or "")}

    async def stream_speech(
        self,
        deployment: dict[str, Any],
        *,
        text: str,
        voice: str,
        response_format: str = "mp3",
    ) -> AsyncIterator[bytes]:
        body = {
            "model": deployment["runtime_model_name"],
            "input": text,
            "voice": voice or "alloy",
            "response_format": response_format or "mp3",
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                async with client.stream(
                    "POST",
                    f"{self._root()}/audio/speech",
                    headers=self._headers(),
                    json=body,
                ) as response:
                    if response.status_code >= 400:
                        raise PlatformError("runtime_unavailable", "Runtime rejected the request.", 503)
                    async for chunk in response.aiter_bytes():
                        if chunk:
                            yield chunk
        except PlatformError:
            raise
        except httpx.TimeoutException as exc:
            raise PlatformError("timeout", "Runtime timed out.", 504) from exc
        except httpx.HTTPError as exc:
            raise PlatformError("runtime_unavailable", "Runtime is unavailable.", 503) from exc
