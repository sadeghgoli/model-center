import base64
import json

import pytest
from httpx import AsyncClient

from mc_gateway.gateway import take_sentences
from mc_runtimes.ollama import OllamaRuntime
from mc_runtimes.vllm import VLLMRuntime
from mc_shared.errors import PlatformError
from tests.conftest import auth, token


def test_take_sentences_on_punctuation_and_length() -> None:
    ready, rest = take_sentences("سلام. خوبی؟")
    assert ready == ["سلام.", "خوبی؟"]
    assert rest == ""
    ready, rest = take_sentences("...")
    assert ready == []
    assert rest == ""
    long_text = "کلمه " * 40
    ready, rest = take_sentences(long_text)
    assert ready
    assert len(ready[0]) >= 120
    assert len(rest) < 120


async def test_ollama_and_vllm_reject_audio() -> None:
    deployment = {"runtime_model_name": "audio"}
    for runtime in (OllamaRuntime("http://ollama:11434"), VLLMRuntime("http://vllm/v1")):
        with pytest.raises(PlatformError) as exc:
            await runtime.transcribe(deployment, audio=b"a", filename="a.webm", content_type="audio/webm")
        assert exc.value.status_code == 503
        with pytest.raises(PlatformError) as speech_exc:
            async for _chunk in runtime.stream_speech(deployment, text="سلام", voice="alloy"):
                pass
        assert speech_exc.value.status_code == 503


def _audio_client(speech_inputs: list[str]):
    class FakeResponse:
        status_code = 200

        def json(self):
            return {"text": "سلام"}

    class FakeStream:
        def __init__(self, url: str, kwargs: dict):
            self.url = url
            self.kwargs = kwargs
            self.status_code = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def aiter_lines(self):
            yield 'data: {"choices":[{"index":0,"delta":{"content":"سلام. خوبی؟"}}]}'
            yield "data: [DONE]"

        async def aiter_bytes(self):
            speech_inputs.append((self.kwargs.get("json") or {}).get("input"))
            yield b"ID3fake"

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, **kwargs):
            assert url.endswith("/audio/transcriptions")
            assert kwargs["data"]["language"] == "fa"
            return FakeResponse()

        def stream(self, *args, **kwargs):
            return FakeStream(args[1], kwargs)

        async def get(self, *args, **kwargs):
            class Health:
                status_code = 200
                text = ""

            return Health()

    return FakeClient


async def _register(client: AsyncClient, access: str, org_id: str, project_id: str, *, slug: str, runtime_type: str, runtime_model: str, model_type: str):
    model = await client.post(
        "/api/v1/models",
        headers=auth(access),
        json={"name": slug, "slug": slug, "display_name": slug, "model_type": model_type, "supports_audio": model_type != "chat"},
    )
    assert model.status_code == 201
    model_id = model.json()["data"]["id"]
    runtime = await client.post(
        "/api/v1/runtimes",
        headers=auth(access),
        json={"organization_id": org_id, "name": slug, "slug": f"{slug}-rt", "type": runtime_type, "endpoint": "http://runtime.test/v1"},
    )
    assert runtime.status_code == 201
    deployment = await client.post(
        "/api/v1/deployments",
        headers=auth(access),
        json={
            "model_id": model_id,
            "runtime_id": runtime.json()["data"]["id"],
            "name": slug,
            "slug": f"{slug}-dep",
            "runtime_model_name": runtime_model,
        },
    )
    assert deployment.status_code == 201
    linked = await client.post(f"/api/v1/projects/{project_id}/models", headers=auth(access), json={"model_id": model_id})
    assert linked.status_code == 201
    return model_id


async def test_audio_upload_limit_is_higher_than_json(client: AsyncClient) -> None:
    payload = "a" * (1_048_576 + 32)
    chat = await client.post("/v1/chat/completions", json={"model": "qwen", "messages": [{"role": "user", "content": payload}]})
    assert chat.status_code == 413
    audio = await client.post(
        "/v1/audio/transcriptions",
        files={"file": ("speech.webm", b"a" * (1_048_576 + 32), "audio/webm")},
        data={"model": "whisper"},
    )
    assert audio.status_code == 401


async def test_transcription_speech_and_voice_stream(client: AsyncClient, monkeypatch) -> None:
    speech_inputs: list[str] = []
    monkeypatch.setattr("mc_runtimes.openai_compatible.httpx.AsyncClient", _audio_client(speech_inputs))
    access = await token(client)
    org = await client.post("/api/v1/organizations", headers=auth(access), json={"name": "GSM", "slug": "gsm"})
    org_id = org.json()["data"]["id"]
    project = await client.post(
        "/api/v1/projects",
        headers=auth(access),
        json={"organization_id": org_id, "name": "Voice", "slug": "voice"},
    )
    project_id = project.json()["data"]["id"]
    chat_id = await _register(client, access, org_id, project_id, slug="qwen3-8b", runtime_type="openai_compatible", runtime_model="Qwen/Qwen3-8B", model_type="chat")
    stt_id = await _register(client, access, org_id, project_id, slug="whisper", runtime_type="openai_compatible", runtime_model="whisper-1", model_type="transcription")
    tts_id = await _register(client, access, org_id, project_id, slug="tts", runtime_type="openai_compatible", runtime_model="tts-1", model_type="speech")
    created = await client.post(
        f"/api/v1/projects/{project_id}/api-keys",
        headers=auth(access),
        json={"name": "voice", "model_ids": [chat_id, stt_id, tts_id]},
    )
    raw = created.json()["data"]["api_key"]
    headers = {"Authorization": f"Bearer {raw}"}

    transcript = await client.post(
        "/v1/audio/transcriptions",
        headers=headers,
        files={"file": ("speech.webm", b"fake-audio", "audio/webm")},
        data={"model": "whisper", "language": "fa"},
    )
    assert transcript.status_code == 200
    assert transcript.json()["text"] == "سلام"

    spoken = await client.post("/v1/audio/speech", headers=headers, json={"model": "tts", "input": "سلام.", "voice": "alloy"})
    assert spoken.status_code == 200
    assert spoken.headers["content-type"].startswith("audio/mpeg")
    assert spoken.content == b"ID3fake"

    speech_inputs.clear()
    voice = await client.post(
        "/v1/audio/chat",
        headers=headers,
        files={"file": ("speech.webm", b"fake-audio", "audio/webm")},
        data={
            "model": "qwen3-8b",
            "stt_model": "whisper",
            "tts_model": "tts",
            "messages": "[]",
            "voice": "alloy",
            "language": "fa",
        },
    )
    assert voice.status_code == 200
    body = voice.text
    assert body.index('"type": "transcript"') < body.index('"type": "text"')
    assert body.index('"type": "text"') < body.index('"type": "audio"')
    assert body.count('"type": "audio"') == 2
    assert "data: [DONE]" in body
    assert speech_inputs == ["سلام.", "خوبی؟"]
    audio_line = next(line for line in body.splitlines() if '"type": "audio"' in line)
    payload = json.loads(audio_line.removeprefix("data: "))
    assert base64.b64decode(payload["audio"]) == b"ID3fake"
    assert payload["format"] == "wav"

    panel = await client.post(
        "/api/v1/playground/voice",
        headers=auth(access),
        files={"file": ("speech.webm", b"fake-audio", "audio/webm")},
        data={"model": "qwen3-8b", "stt_model": "whisper", "tts_model": "tts", "messages": "[]", "language": "fa"},
    )
    assert panel.status_code == 200
    assert '"type": "transcript"' in panel.text
    assert "data: [DONE]" in panel.text


async def test_vllm_transcription_is_rejected(client: AsyncClient) -> None:
    access = await token(client)
    org = await client.post("/api/v1/organizations", headers=auth(access), json={"name": "GSM", "slug": "gsm"})
    org_id = org.json()["data"]["id"]
    project = await client.post(
        "/api/v1/projects",
        headers=auth(access),
        json={"organization_id": org_id, "name": "Voice", "slug": "voice"},
    )
    project_id = project.json()["data"]["id"]
    model_id = await _register(client, access, org_id, project_id, slug="whisper", runtime_type="vllm", runtime_model="whisper-1", model_type="transcription")
    created = await client.post(
        f"/api/v1/projects/{project_id}/api-keys",
        headers=auth(access),
        json={"name": "voice", "model_ids": [model_id]},
    )
    raw = created.json()["data"]["api_key"]
    denied = await client.post(
        "/v1/audio/transcriptions",
        headers={"Authorization": f"Bearer {raw}"},
        files={"file": ("speech.webm", b"fake-audio", "audio/webm")},
        data={"model": "whisper", "language": "fa"},
    )
    assert denied.status_code == 503
    assert denied.json()["error"]["code"] == "runtime_unavailable"
