from collections.abc import AsyncIterator
from typing import Any

from mc_runtimes.base import ModelRuntime
from mc_runtimes.openai_compatible import OpenAICompatibleRuntime


class VLLMRuntime(OpenAICompatibleRuntime):
    """vLLM exposes an OpenAI-compatible server. This adapter does not import vLLM."""

    async def transcribe(
        self,
        deployment: dict[str, Any],
        *,
        audio: bytes,
        filename: str,
        content_type: str,
        language: str | None = None,
    ) -> dict[str, Any]:
        return await ModelRuntime.transcribe(
            self,
            deployment,
            audio=audio,
            filename=filename,
            content_type=content_type,
            language=language,
        )

    async def stream_speech(
        self,
        deployment: dict[str, Any],
        *,
        text: str,
        voice: str,
        response_format: str = "mp3",
    ) -> AsyncIterator[bytes]:
        async for chunk in ModelRuntime.stream_speech(
            self,
            deployment,
            text=text,
            voice=voice,
            response_format=response_format,
        ):
            yield chunk
