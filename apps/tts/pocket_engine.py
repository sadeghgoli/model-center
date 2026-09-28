"""Persian speech synthesis with mehdi-hf/pocket-tts-farsi-v2.

The checkpoint reads romanised phonemes, not Persian script. This follows the
official pipeline in training/farsi/v2/space/app.py: normalise, phonemise with
Homo-GE2PE, chunk, then synthesise with the mallahyari pocket-tts fork.
"""

from __future__ import annotations

import importlib.util
import logging
import math
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import numpy as np
import scipy.io.wavfile
import torch
from huggingface_hub import hf_hub_download

MODEL_ID = "mehdi-hf/pocket-tts-farsi-v2"
MODEL_CONFIG = f"hf://{MODEL_ID}/model.yaml"
G2P_ID = "mehdi-hf/Homo-GE2PE-Persian-HF"
VOICE_FILES = {
    "hello": "samples/prompt_hello.wav",
    "short": "samples/prompt_short_sentence.wav",
    "news": "samples/prompt_news_paragraph.wav",
}
DEFAULT_VOICE = "hello"

DEFAULT_TEMPERATURE = 0.3
DEFAULT_EOS_THRESHOLD = -2.0
FRAMES_AFTER_EOS = 0
DEFAULT_MAX_TOKENS = 18
DEFAULT_MIN_TOKENS = 5
DEFAULT_VOICE_SEC = 5.0
DEFAULT_PAUSE_SEC = 0.18
CLAUSE_PAUSE_SEC = 0.06
CROSSFADE_MS = 45
CAP_RATIO = 0.97
RETRIES = 2

TO_PHONEMES = str.maketrans({"/": "a", "a": "A", "@": "?", "$": "S", "c": "C"})
EZAFE_MARK = "1"
SENTENCE_SPLIT = re.compile(r"(?<=[.!؟])\s+")
CLAUSE_SPLIT = re.compile(r"(?<=[،؛:])\s+")

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("pocket-tts-farsi-v2")


@dataclass
class Engine:
    model: Any
    g2p_tok: Any
    g2p: Any
    tokenizer: Any
    normalize_for_model: Callable[[str], str]
    voice_states: dict[str, Any] = field(default_factory=dict)


def load_normalize_for_model():
    path = hf_hub_download(MODEL_ID, "normalize_fa.py")
    spec = importlib.util.spec_from_file_location("normalize_fa", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not import normalize_fa.py from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.normalize_for_model


def load_engine() -> Engine:
    from pocket_tts import TTSModel
    from transformers import AutoTokenizer, T5ForConditionalGeneration

    normalize_for_model = load_normalize_for_model()
    logger.info("loading %s", MODEL_ID)
    model = TTSModel.load_model(
        config=MODEL_CONFIG,
        temp=DEFAULT_TEMPERATURE,
        eos_threshold=DEFAULT_EOS_THRESHOLD,
    )
    logger.info("loading %s", G2P_ID)
    g2p_tok = AutoTokenizer.from_pretrained(G2P_ID)
    g2p = T5ForConditionalGeneration.from_pretrained(G2P_ID).eval()
    return Engine(
        model=model,
        g2p_tok=g2p_tok,
        g2p=g2p,
        tokenizer=model.flow_lm.conditioner.tokenizer.sp,
        normalize_for_model=normalize_for_model,
    )


def trim_voice_prompt(source: str, voice_sec: float) -> str:
    """Cap the prompt at the 5 s training limit. Library truncate only cuts at 30 s."""
    sample_rate, data = scipy.io.wavfile.read(source)
    audio = np.asarray(data)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if np.issubdtype(audio.dtype, np.integer):
        info = np.iinfo(audio.dtype)
        audio = audio.astype(np.float32) / max(abs(info.min), info.max)
    else:
        audio = audio.astype(np.float32)
    if voice_sec > 0:
        audio = audio[: int(voice_sec * sample_rate)]
    peak = float(np.max(np.abs(audio))) if audio.size else 0.0
    if peak > 1.0:
        audio = audio / peak
    path = Path(tempfile.mkdtemp()) / "voice_prompt.wav"
    scipy.io.wavfile.write(str(path), int(sample_rate), (audio * 32767.0).astype(np.int16))
    return str(path)


def voice_state(engine: Engine, voice: str):
    if voice not in engine.voice_states:
        source = hf_hub_download(MODEL_ID, VOICE_FILES[voice])
        prompt = trim_voice_prompt(source, DEFAULT_VOICE_SEC)
        engine.voice_states[voice] = engine.model.get_state_for_audio_prompt(prompt)
    return engine.voice_states[voice]


def strip_ezafe(text: str) -> str:
    return text.replace(EZAFE_MARK, "")


def phonemise(persian: str, normalize_for_model, g2p_tok, g2p) -> str:
    text = normalize_for_model(persian)
    text = text.replace("؟", "").replace("?", "")
    if not text.strip():
        raise ValueError(f"Nothing left after Persian normalisation: {persian!r}")
    enc = g2p_tok([text], add_special_tokens=False, return_tensors="pt")
    with torch.no_grad():
        out = g2p.generate(**enc, num_beams=5, max_length=512, early_stopping=True)
    raw = g2p_tok.batch_decode(out, skip_special_tokens=True)[0].strip()
    return raw.translate(TO_PHONEMES)


def count_tokens(tokenizer, text: str) -> int:
    return len(tokenizer.encode(strip_ezafe(text)))


def plan_sentence(sent: str, phonemise_fn, tokenizer, max_tokens: int) -> list[tuple[str, str]]:
    """One Persian sentence -> [(phoneme chunk, boundary kind)]. Ported from app.py."""
    words: list[tuple[str, bool]] = []
    for clause in CLAUSE_SPLIT.split(sent):
        if not clause.strip():
            continue
        phoneme_words = phonemise_fn(clause).split()
        words.extend((word, index == len(phoneme_words) - 1) for index, word in enumerate(phoneme_words))
    if not words:
        return []

    joined = " ".join(word for word, _ in words)
    total = count_tokens(tokenizer, joined)
    n_chunks = max(1, math.ceil(total / max_tokens))
    out: list[tuple[str, str]] = []
    for _ in range(4):
        out = []
        cur = ""
        for index, (word, ends_clause) in enumerate(words):
            trial = f"{cur} {word}".strip()
            bound = bool(cur) and cur.split()[-1].endswith(EZAFE_MARK)
            over_budget = count_tokens(tokenizer, trial) > max_tokens
            if cur and not bound and over_budget:
                out.append((cur, "budget"))
                cur = word
                continue
            cur = trial
            if not ends_clause or index == len(words) - 1:
                continue
            rest = count_tokens(tokenizer, " ".join(item for item, _ in words[index + 1 :]))
            if count_tokens(tokenizer, cur) >= DEFAULT_MIN_TOKENS and rest >= DEFAULT_MIN_TOKENS:
                out.append((cur, "clause"))
                cur = ""
        if cur:
            out.append((cur, "clause"))
        if len(out) <= n_chunks:
            break
        n_chunks = len(out)
    # A tail under min_tokens continues the voice prompt instead of the text.
    for index in range(len(out) - 1, 0, -1):
        chunk, kind = out[index]
        while count_tokens(tokenizer, chunk) < DEFAULT_MIN_TOKENS:
            prev_words = out[index - 1][0].split()
            if len(prev_words) < 2 or count_tokens(tokenizer, " ".join(prev_words[:-1])) < DEFAULT_MIN_TOKENS:
                break
            out[index - 1] = (" ".join(prev_words[:-1]), out[index - 1][1])
            chunk = f"{prev_words[-1]} {chunk}"
            out[index] = (chunk, kind)
    return out


def cap_seconds(model, tokenizer, text: str) -> float:
    tokens = len(tokenizer.encode(text))
    tps = getattr(model, "_TOKENS_PER_SECOND_ESTIMATE", 3.0)
    pad = getattr(model, "_GEN_SECONDS_PADDING", 2.0)
    return tokens / tps + pad


def generate_one(model, state, tokenizer, spoken: str) -> np.ndarray:
    cap = cap_seconds(model, tokenizer, spoken)
    sample_rate = model.sample_rate
    shortest = None
    for attempt in range(RETRIES + 1):
        audio = model.generate_audio(state, spoken, frames_after_eos=FRAMES_AFTER_EOS)
        if torch.is_tensor(audio):
            audio = audio.detach().float().cpu().numpy()
        audio = np.asarray(audio, dtype=np.float32).reshape(-1)
        duration = audio.shape[-1] / sample_rate
        if duration <= CAP_RATIO * cap:
            return audio
        logger.warning("runaway on attempt %d (%.1fs > %.1fs cap): %s", attempt + 1, duration, cap, spoken)
        if shortest is None or audio.shape[-1] < shortest.shape[-1]:
            shortest = audio
    return shortest


def trim_silence(audio: np.ndarray, sample_rate: int, keep_ms: float = 120.0) -> np.ndarray:
    if audio.size == 0:
        return audio
    rms = float(np.sqrt((audio.astype(np.float64) ** 2).mean()))
    if rms <= 0:
        return audio
    win = int(0.02 * sample_rate)
    thr = 0.04 * rms
    loud = [
        index
        for index in range(0, max(len(audio) - win, 1), win)
        if np.sqrt((audio[index : index + win].astype(np.float64) ** 2).mean()) > thr
    ]
    if not loud:
        return audio
    margin = int(keep_ms / 1000.0 * sample_rate)
    return audio[max(0, loud[0] - margin) : min(len(audio), loud[-1] + win + margin)]


def crossfade(left: np.ndarray, right: np.ndarray, sample_rate: int, fade_ms: float = CROSSFADE_MS) -> np.ndarray:
    """Overlap the seam so a mid-sentence chunk split does not drop to silence."""
    fade = int(fade_ms / 1000.0 * sample_rate)
    fade = min(fade, len(left) // 2, len(right) // 2)
    if fade <= 0:
        return np.concatenate([left, right])
    ramp = np.linspace(1.0, 0.0, fade, dtype=np.float32)
    mixed = left[-fade:] * ramp + right[:fade] * (1.0 - ramp)
    return np.concatenate([left[:-fade], mixed, right[fade:]])


def stitch(pieces: list[tuple[np.ndarray, str]], sample_rate: int) -> np.ndarray:
    """Join chunks. Only sentence ends get a pause; phrase splits crossfade."""
    audio, boundary = pieces[0]
    for nxt, nxt_boundary in pieces[1:]:
        if boundary == "sentence":
            gap = np.zeros(int(DEFAULT_PAUSE_SEC * sample_rate), dtype=np.float32)
            audio = crossfade(np.concatenate([audio, gap]), nxt, sample_rate, 20)
        elif boundary == "clause":
            gap = np.zeros(int(CLAUSE_PAUSE_SEC * sample_rate), dtype=np.float32)
            audio = crossfade(np.concatenate([audio, gap]), nxt, sample_rate, 25)
        else:
            audio = crossfade(audio, nxt, sample_rate)
        boundary = nxt_boundary
    return audio


def render(engine: Engine, text: str, voice: str) -> tuple[np.ndarray, int]:
    tokenizer = engine.tokenizer
    sentences = [part.strip() for part in SENTENCE_SPLIT.split(text.strip()) if part.strip()]
    plan: list[tuple[str, str]] = []

    def phonemise_fn(clause: str) -> str:
        return phonemise(clause, engine.normalize_for_model, engine.g2p_tok, engine.g2p)

    for sentence in sentences:
        chunks = plan_sentence(sentence, phonemise_fn, tokenizer, DEFAULT_MAX_TOKENS)
        if chunks:
            plan.extend(chunks[:-1])
            plan.append((chunks[-1][0], "sentence"))
    if not plan:
        raise ValueError("Nothing to synthesize.")

    state = voice_state(engine, voice)
    sample_rate = engine.model.sample_rate
    pieces: list[tuple[np.ndarray, str]] = []
    for chunk, kind in plan:
        audio = generate_one(engine.model, state, tokenizer, strip_ezafe(chunk))
        pieces.append((trim_silence(audio, sample_rate), kind))
    return stitch(pieces, sample_rate), sample_rate


def to_pcm16(wav: np.ndarray) -> np.ndarray:
    return (np.clip(wav, -1.0, 1.0) * 32767.0).astype(np.int16)
