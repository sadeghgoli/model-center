import base64
import json

import pytest
from httpx import AsyncClient

from mc_gateway.gateway import ReasoningSplitter, _reasoning_styles, remember_reasoning_style, take_sentences
from mc_runtimes.ollama import OllamaRuntime
from mc_runtimes.speech2text import Speech2TextRuntime, upload_name
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


def _split(style: str | None, chunks: list[str]) -> tuple[str, str, str]:
    splitter = ReasoningSplitter(style)
    parts = [part for chunk in chunks for part in splitter.feed(chunk)] + splitter.finish()
    thought = "".join(text for kind, text in parts if kind == "reasoning")
    answer = "".join(text for kind, text in parts if kind == "text")
    return thought, answer, splitter.learned_style()


def test_reasoning_with_both_tags_split_across_chunks() -> None:
    thought, answer, style = _split(None, ["  <thi", "nk>Okay, the user", " greets.</th", "ink>\n\nسلام!", " خوبی؟"])
    assert thought == "Okay, the user greets."
    assert answer == "سلام! خوبی؟"
    assert style == "tags"


def test_reasoning_with_only_closing_tag() -> None:
    thought, answer, style = _split(None, ["Okay, the user said سلام.", " I should greet.\n</think>\n\n", "سلام، وقت بخیر."])
    assert "Okay, the user said" in thought
    assert answer == "سلام، وقت بخیر."
    assert style == "closing"


def test_no_reasoning_is_released_as_answer_and_learned() -> None:
    thought, answer, style = _split(None, ["سلام.", " چطور کمک کنم؟"])
    assert answer == "سلام. چطور کمک کنم؟"
    assert style == "none"
    splitter = ReasoningSplitter("none")
    assert splitter.feed("سلام.") == [("text", "سلام.")]


def test_closing_tag_after_learning_none_is_not_spoken_and_relearned() -> None:
    thought, answer, style = _split("none", ["Okay thinking.</th", "ink>سلام."])
    assert "</think>" not in answer
    assert answer.endswith("سلام.")
    assert style == "closing"


def test_none_style_needs_several_tagless_replies() -> None:
    _reasoning_styles.clear()
    for _ in range(2):
        remember_reasoning_style("deployment", "none")
    assert "deployment" not in _reasoning_styles
    remember_reasoning_style("deployment", "none")
    assert _reasoning_styles["deployment"] == "none"
    remember_reasoning_style("deployment", "closing")
    assert _reasoning_styles["deployment"] == "closing"
    _reasoning_styles.clear()


async def test_ollama_stream_keeps_thinking_separate(monkeypatch) -> None:
    lines = [
        json.dumps({"message": {"role": "assistant", "content": "", "thinking": "Okay, the user"}, "done": False}),
        json.dumps({"message": {"role": "assistant", "content": "سلام."}, "done": False}),
        json.dumps({"message": {"role": "assistant", "content": ""}, "done": True}),
    ]

    class Response:
        status_code = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def aiter_lines(self):
            for line in lines:
                yield line

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        def stream(self, *args, **kwargs):
            return Response()

    monkeypatch.setattr("mc_runtimes.ollama.httpx.AsyncClient", Client)
    runtime = OllamaRuntime("http://ollama:11434")
    deltas = [item["choices"][0]["delta"] async for item in runtime.stream_chat({"runtime_model_name": "qwen3:4b"}, {"model": "qwen3-4b"})]
    assert deltas[0] == {"reasoning_content": "Okay, the user"}
    assert deltas[1] == {"content": "سلام."}


def test_upload_name_keeps_or_adds_extension() -> None:
    assert upload_name("speech.webm", "audio/webm") == "speech.webm"
    assert upload_name("blob", "audio/webm;codecs=opus") == "blob.webm"
    assert upload_name("", "audio/wav") == "audio.wav"
    assert upload_name("../../etc/clip.mp3", "") == "clip.mp3"


def _speech2text_client(states: list[dict], calls: list[tuple[str, str]]):
    class Reply:
        def __init__(self, status_code: int, body: dict):
            self.status_code = status_code
            self._body = body

        def json(self):
            return self._body

    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.headers = kwargs.get("headers") or {}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, **kwargs):
            calls.append(("POST", url))
            assert self.headers["Authorization"] == "Bearer sk_stt_test"
            assert kwargs["files"]["file"][0] == "speech.webm"
            assert kwargs["data"] == {"language": "fa", "model": "large-v3"}
            return Reply(202, {"success": True, "job_id": "job-1", "status": "queued"})

        async def get(self, url, **kwargs):
            calls.append(("GET", url))
            return Reply(200, states.pop(0))

        async def delete(self, url, **kwargs):
            calls.append(("DELETE", url))
            return Reply(200, {})

    return FakeClient


async def test_speech2text_polls_until_completed(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    states = [{"status": "queued"}, {"status": "processing"}, {"status": "completed", "text": "سلام"}]
    monkeypatch.setattr("mc_runtimes.speech2text.httpx.AsyncClient", _speech2text_client(states, calls))
    runtime = Speech2TextRuntime("https://stt.test/api/v1", "sk_stt_test", timeout=30)
    runtime.poll_interval = 0
    result = await runtime.transcribe(
        {"runtime_model_name": "large-v3"}, audio=b"x", filename="speech.webm", content_type="audio/webm", language="fa"
    )
    assert result == {"text": "سلام"}
    assert calls[0] == ("POST", "/api/v1/transcriptions")
    assert calls[-1] == ("GET", "/api/v1/transcriptions/job-1")


async def test_speech2text_failed_job_is_runtime_error(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    states = [{"status": "failed", "error_message": "bad audio"}]
    monkeypatch.setattr("mc_runtimes.speech2text.httpx.AsyncClient", _speech2text_client(states, calls))
    runtime = Speech2TextRuntime("https://stt.test", "sk_stt_test", timeout=30)
    runtime.poll_interval = 0
    with pytest.raises(PlatformError) as exc:
        await runtime.transcribe(
            {"runtime_model_name": "large-v3"}, audio=b"x", filename="speech.webm", content_type="audio/webm", language="fa"
        )
    assert exc.value.status_code == 503


def _audio_client(speech_inputs: list[str], chat_line: str = 'data: {"choices":[{"index":0,"delta":{"content":"سلام. خوبی؟"}}]}'):
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
            yield chat_line
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

    _reasoning_styles.clear()
    speech_inputs.clear()
    thinking_line = json.dumps(
        {"choices": [{"index": 0, "delta": {"content": "Okay, the user greets me.\n</think>\n\nسلام. خوبی؟"}}]},
        ensure_ascii=False,
    )
    monkeypatch.setattr("mc_runtimes.openai_compatible.httpx.AsyncClient", _audio_client(speech_inputs, f"data: {thinking_line}"))
    thinking = await client.post(
        "/v1/audio/chat",
        headers=headers,
        files={"file": ("speech.webm", b"fake-audio", "audio/webm")},
        data={"model": "qwen3-8b", "stt_model": "whisper", "tts_model": "tts", "messages": "[]", "language": "fa"},
    )
    events = [json.loads(line.removeprefix("data: ")) for line in thinking.text.splitlines() if line.startswith("data: {")]
    thought = "".join(event["delta"] for event in events if event["type"] == "reasoning")
    answer = "".join(event["delta"] for event in events if event["type"] == "text")
    assert "Okay, the user greets me." in thought
    assert answer == "سلام. خوبی؟"
    assert speech_inputs == ["سلام.", "خوبی؟"]


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
