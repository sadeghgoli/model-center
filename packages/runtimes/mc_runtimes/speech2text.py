import asyncio
import time
from collections.abc import AsyncIterator
from pathlib import PurePath
from typing import Any

import httpx

from mc_shared.errors import PlatformError
from mc_runtimes.base import ModelRuntime

_FINAL = {"completed", "failed", "cancelled"}
_EXTENSIONS = {"wav", "mp3", "m4a", "ogg", "flac", "aac", "mp4", "webm", "mov"}
_TYPE_EXTENSIONS = {
    "audio/webm": "webm",
    "video/webm": "webm",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/mpeg": "mp3",
    "audio/mp4": "m4a",
    "audio/ogg": "ogg",
    "audio/flac": "flac",
    "audio/aac": "aac",
}


def upload_name(filename: str, content_type: str) -> str:
    """The service picks the decoder from the file extension and rejects names without one."""
    stem = PurePath(filename or "audio").name or "audio"
    if PurePath(stem).suffix.lstrip(".").lower() in _EXTENSIONS:
        return stem
    extension = _TYPE_EXTENSIONS.get((content_type or "").split(";")[0].strip().lower(), "webm")
    return f"{PurePath(stem).stem or 'audio'}.{extension}"


class Speech2TextRuntime(ModelRuntime):
    """Asynchronous transcription service: upload a job, then poll until it finishes."""

    poll_interval = 0.5
    max_poll_interval = 2.0

    def _root(self) -> str:
        return self.endpoint.removesuffix("/api/v1")

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}

    async def health_check(self, deployment: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(f"{self._root()}/health")
            if response.status_code >= 400:
                return {"status": "unhealthy", "detail": response.text[:200]}
            return {"status": "online"}
        except httpx.TimeoutException:
            return {"status": "offline", "detail": "timeout"}
        except httpx.HTTPError as exc:
            return {"status": "offline", "detail": str(exc)}

    async def chat(self, deployment: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
        raise PlatformError("runtime_unavailable", "This runtime only transcribes audio.", 503)

    async def stream_chat(
        self, deployment: dict[str, Any], request: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        raise PlatformError("runtime_unavailable", "This runtime only transcribes audio.", 503)
        yield {}

    @staticmethod
    def _rejected(response: httpx.Response) -> PlatformError:
        try:
            error = response.json().get("error") or {}
        except ValueError:
            error = {}
        code = str(error.get("code") or "")
        if response.status_code in {413, 415, 422}:
            return PlatformError("invalid_request", f"Audio was rejected by the transcription service ({code or response.status_code}).", 400)
        if response.status_code == 429:
            return PlatformError("rate_limit_exceeded", "Transcription service rate limit exceeded.", 429)
        return PlatformError("runtime_unavailable", "Runtime rejected the request.", 503)

    async def transcribe(
        self,
        deployment: dict[str, Any],
        *,
        audio: bytes,
        filename: str,
        content_type: str,
        language: str | None = None,
    ) -> dict[str, Any]:
        form = {"language": language or "fa"}
        model = str(deployment.get("runtime_model_name") or "").strip()
        if model:
            form["model"] = model
        files = {"file": (upload_name(filename, content_type), audio, content_type or "application/octet-stream")}
        deadline = time.monotonic() + self.timeout
        job_id = ""
        try:
            async with httpx.AsyncClient(base_url=self._root(), headers=self._headers(), timeout=self.timeout) as client:
                created = await client.post("/api/v1/transcriptions", data=form, files=files)
                if created.status_code >= 400:
                    raise self._rejected(created)
                job_id = str(created.json().get("job_id") or "")
                if not job_id:
                    raise PlatformError("runtime_unavailable", "Transcription service returned no job.", 503)
                interval = self.poll_interval
                while True:
                    status = await client.get(f"/api/v1/transcriptions/{job_id}")
                    if status.status_code >= 400:
                        raise self._rejected(status)
                    job = status.json()
                    state = job.get("status")
                    if state == "completed":
                        return {"text": str(job.get("text") or "")}
                    if state in _FINAL:
                        raise PlatformError("runtime_unavailable", "Transcription failed.", 503)
                    if time.monotonic() + interval > deadline:
                        await client.delete(f"/api/v1/transcriptions/{job_id}")
                        raise PlatformError("timeout", "Runtime timed out.", 504)
                    await asyncio.sleep(interval)
                    interval = min(interval * 1.5, self.max_poll_interval)
        except PlatformError:
            raise
        except httpx.TimeoutException as exc:
            raise PlatformError("timeout", "Runtime timed out.", 504) from exc
        except httpx.HTTPError as exc:
            raise PlatformError("runtime_unavailable", "Runtime is unavailable.", 503) from exc
