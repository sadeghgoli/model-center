"""OpenAI-compatible speech server for pocket-tts-farsi-v2.

Model Center reaches this as an openai_compatible runtime; the gateway never
imports it. The model is loaded once at startup and kept in memory.
"""

from __future__ import annotations

import asyncio
import io
import os
import threading
from contextlib import asynccontextmanager

import numpy as np
import scipy.io.wavfile
from fastapi import FastAPI, Header, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from pocket_engine import DEFAULT_VOICE, MODEL_ID, VOICE_FILES, Engine, load_engine, logger, render, to_pcm16

PUBLIC_MODEL = "pocket-tts-farsi-v2"
API_KEY = os.environ.get("POCKET_TTS_API_KEY", "")
MAX_INPUT_CHARS = 2000

_engine: Engine | None = None
_render_lock = threading.Lock()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global _engine
    _engine = await asyncio.to_thread(load_engine)
    logger.info("ready")
    yield


app = FastAPI(title="Pocket TTS Farsi", lifespan=lifespan)


class SpeechBody(BaseModel):
    model: str = PUBLIC_MODEL
    input: str
    voice: str = DEFAULT_VOICE
    response_format: str = "wav"
    speed: float | None = None


def _check_key(authorization: str | None) -> None:
    if API_KEY and authorization != f"Bearer {API_KEY}":
        raise HTTPException(status_code=401, detail="Invalid API key.")


def _speak(text: str, voice: str) -> tuple[np.ndarray, int]:
    assert _engine is not None
    with _render_lock:
        wav, sample_rate = render(_engine, text, voice)
    return to_pcm16(wav), sample_rate


@app.get("/health")
async def health() -> dict:
    return {"status": "ok" if _engine is not None else "loading"}


@app.get("/v1/models")
async def models(authorization: str | None = Header(None)) -> dict:
    _check_key(authorization)
    return {"object": "list", "data": [{"id": PUBLIC_MODEL, "object": "model", "owned_by": MODEL_ID}]}


@app.post("/v1/audio/speech")
async def speech(body: SpeechBody, authorization: str | None = Header(None)):
    _check_key(authorization)
    if _engine is None:
        raise HTTPException(status_code=503, detail="Model is still loading.")
    text = body.input.strip()
    if not text:
        raise HTTPException(status_code=400, detail="input is required.")
    if len(text) > MAX_INPUT_CHARS:
        raise HTTPException(status_code=400, detail=f"input is longer than {MAX_INPUT_CHARS} characters.")
    response_format = (body.response_format or "wav").lower()
    if response_format not in {"wav", "pcm"}:
        return JSONResponse(
            status_code=400,
            content={"error": {"message": "Only wav and pcm are supported.", "type": "invalid_request_error"}},
        )
    voice = body.voice if body.voice in VOICE_FILES else DEFAULT_VOICE
    try:
        pcm, sample_rate = await run_in_threadpool(_speak, text, voice)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if response_format == "pcm":
        return Response(pcm.tobytes(), media_type="audio/pcm", headers={"X-Sample-Rate": str(sample_rate)})
    buffer = io.BytesIO()
    scipy.io.wavfile.write(buffer, sample_rate, pcm)
    return Response(buffer.getvalue(), media_type="audio/wav")
