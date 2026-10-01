# Model Center

The platform must not depend on a specific inference runtime.

Model Center is a self-hosted control plane for models, deployments, and an OpenAI-compatible API. Ollama and vLLM are optional external runtimes. The gateway never imports them. GSM is only a client:

```env
AI_PLATFORM_BASE_URL=http://localhost:9005/v1
AI_PLATFORM_API_KEY=sk-gsm-...
AI_MODEL=qwen3-8b
```

## Run

```powershell
Copy-Item .env.example .env
docker compose --env-file .env -f infra/docker/docker-compose.yml up --build -d
```

Set `DEFAULT_ADMIN_EMAIL` and `DEFAULT_ADMIN_PASSWORD` before the first start. The API creates that super admin only when both values are set and none exists. The password is not printed.

Migration and bootstrap run when the API container starts:

```powershell
docker compose --env-file .env -f infra/docker/docker-compose.yml exec api alembic upgrade head
docker compose --env-file .env -f infra/docker/docker-compose.yml exec api python -m mc_api.bootstrap
```

Tests:

```powershell
docker compose --env-file .env -f infra/docker/docker-compose.yml exec api pytest -q /srv/tests
```

The panel is `http://localhost:9006`. The API is `http://localhost:9005`. PostgreSQL is on `9007` and Redis is on `9008`.

## First model

1. Sign in and create organization `gsm`.
2. Register runtime `vLLM Server 01` with type `vllm` and the external endpoint, for example `http://192.168.1.50:8000/v1`.
3. Add model slug `qwen3-8b`.
4. Deploy it with runtime model name `Qwen/Qwen3-8B`. A running deployment is active immediately. This does not start containers.
5. Create project `voice-agent`, allow `qwen3-8b`, and create an API key. The raw key is shown once.
6. Call the gateway:

```powershell
curl http://127.0.0.1:9005/v1/chat/completions -H "Authorization: Bearer sk-gsm-..." -H "Content-Type: application/json" -d "{\"model\":\"qwen3-8b\",\"messages\":[{\"role\":\"user\",\"content\":\"سلام، خودت را معرفی کن.\"}]}"
```

## Persian speech

The `tts` service in `apps/tts` serves `mehdi-hf/pocket-tts-farsi-v2` on CPU behind `/v1/audio/speech`. It is a separate container; the gateway reaches it over HTTP like any other runtime. The first start downloads about 1 GB into the `tts-hf-cache` volume and needs about 8 GB of RAM. The model license is CC-BY-NC-4.0.

```powershell
docker compose --env-file .env -f infra/docker/docker-compose.yml up --build -d tts
```

Register runtime type `openai_compatible` with endpoint `http://tts:8010/v1`, a model `pocket-tts-fa` of type speech, and a deployment with runtime model name `pocket-tts-farsi-v2`. Voices are `hello`, `short`, and `news`. Output is `wav` or `pcm`. Voice chat also needs a transcription model.

## Persian transcription (BuzzASR)

The `asr` service in `apps/asr` serves `BuzzASR/persian`, a full fine-tune of Whisper large-v3 with its own tokenizer, behind `/v1/audio/transcriptions`. It runs through transformers, not faster-whisper, because the replaced tokenizer moves Whisper's special token ids. It is in the `asr` profile and reserves the NVIDIA GPU; it needs about 5 GB of VRAM. The first start downloads about 3.1 GB into the `asr-hf-cache` volume. The model license is MIT.

```powershell
docker compose --env-file .env -f infra/docker/docker-compose.yml --profile asr up --build -d asr
```

Without a GPU, remove the `deploy` block, set `ASR_TORCH_INDEX=https://download.pytorch.org/whl/cpu` in `.env`, and expect several seconds per second of audio and about 8 GB of RAM.

Register runtime type `openai_compatible` with endpoint `http://asr:8011/v1`, a model `buzz-fa` of type transcription, and a deployment with runtime model name `BuzzASR/persian`.

Add `"stream": true` for SSE. The Playground page calls `/api/v1/playground/chat`, which uses the same router and runtime adapter as `/v1/chat/completions`.
