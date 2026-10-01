"""OpenAI-compatible transcription server for BuzzASR/persian.

BuzzASR replaces the Whisper tokenizer, so its special token ids differ from
stock Whisper and CTranslate2/faster-whisper conversions are not used. The
model runs through transformers exactly as its model card shows. Model Center
reaches this as an openai_compatible runtime.
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import threading
from contextlib import asynccontextmanager

import numpy as np
import torch
from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import PlainTextResponse
from transformers import WhisperForConditionalGeneration, WhisperProcessor

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("asr")

MODEL_ID = os.environ.get("ASR_MODEL_ID", "BuzzASR/persian")
API_KEY = os.environ.get("ASR_API_KEY", "")
DEVICE = os.environ.get("ASR_DEVICE") or ("cuda" if torch.cuda.is_available() else "cpu")
SAMPLE_RATE = 16000
CHUNK_SECONDS = 30
MAX_SECONDS = int(os.environ.get("ASR_MAX_SECONDS", "600"))
MAX_UPLOAD_BYTES = 50 * 1024 * 1024

_model: WhisperForConditionalGeneration | None = None
_processor: WhisperProcessor | None = None
_lock = threading.Lock()


def _load() -> None:
    global _model, _processor
    dtype = torch.float16 if DEVICE.startswith("cuda") else torch.float32
    logger.info("loading %s on %s (%s)", MODEL_ID, DEVICE, dtype)
    _processor = WhisperProcessor.from_pretrained(MODEL_ID)
    _model = WhisperForConditionalGeneration.from_pretrained(MODEL_ID, torch_dtype=dtype).to(DEVICE).eval()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await asyncio.to_thread(_load)
    logger.info("ready")
    yield


app = FastAPI(title="BuzzASR Persian", lifespan=lifespan)


def _check_key(authorization: str | None) -> None:
    if API_KEY and authorization != f"Bearer {API_KEY}":
        raise HTTPException(status_code=401, detail="Invalid API key.")


def _decode(audio: bytes) -> np.ndarray:
    """Any container ffmpeg can read -> 16 kHz mono float32."""
    result = subprocess.run(
        ["ffmpeg", "-nostdin", "-loglevel", "error", "-i", "pipe:0", "-f", "f32le", "-ac", "1", "-ar", str(SAMPLE_RATE), "pipe:1"],
        input=audio,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise ValueError("Audio could not be decoded.")
    return np.frombuffer(result.stdout, dtype=np.float32)


def _transcribe(audio: bytes) -> str:
    assert _model is not None and _processor is not None
    wav = _decode(audio)
    if wav.size == 0:
        raise ValueError("Audio is empty.")
    if wav.size > MAX_SECONDS * SAMPLE_RATE:
        raise ValueError(f"Audio is longer than {MAX_SECONDS} seconds.")
    step = CHUNK_SECONDS * SAMPLE_RATE
    parts: list[str] = []
    with _lock, torch.inference_mode():
        for start in range(0, wav.size, step):
            chunk = wav[start : start + step]
            if chunk.size < SAMPLE_RATE // 4:
                continue
            features = _processor(chunk, sampling_rate=SAMPLE_RATE, return_tensors="pt").input_features
            features = features.to(DEVICE, dtype=_model.dtype)
            ids = _model.generate(features, num_beams=1, no_repeat_ngram_size=3, repetition_penalty=1.2)
            text = _processor.batch_decode(ids, skip_special_tokens=True)[0].strip()
            if text:
                parts.append(text)
    return " ".join(parts)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok" if _model is not None else "loading", "device": DEVICE}


@app.get("/v1/models")
async def models(authorization: str | None = Header(None)) -> dict:
    _check_key(authorization)
    return {"object": "list", "data": [{"id": MODEL_ID, "object": "model", "owned_by": "BuzzASR"}]}


@app.post("/v1/audio/transcriptions")
async def transcriptions(
    file: UploadFile = File(...),
    model: str = Form(MODEL_ID),
    language: str | None = Form(None),
    response_format: str = Form("json"),
    authorization: str | None = Header(None),
):
    _check_key(authorization)
    if _model is None:
        raise HTTPException(status_code=503, detail="Model is still loading.")
    audio = await file.read()
    if not audio:
        raise HTTPException(status_code=400, detail="Audio file is empty.")
    if len(audio) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Audio file is too large.")
    try:
        text = await run_in_threadpool(_transcribe, audio)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if response_format == "text":
        return PlainTextResponse(text)
    return {"text": text}
