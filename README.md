# Model Center

The platform must not depend on a specific inference runtime.

Model Center is a self-hosted control plane for models, deployments, and an OpenAI-compatible API. Ollama and vLLM are optional external runtimes. The gateway never imports them. GSM is only a client:

```env
AI_PLATFORM_BASE_URL=http://localhost:8090/v1
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

The panel is `http://localhost:3010`. The API is `http://localhost:8090`.

## First model

1. Sign in and create organization `gsm`.
2. Register runtime `vLLM Server 01` with type `vllm` and the external endpoint, for example `http://192.168.1.50:8000/v1`.
3. Add model slug `qwen3-8b`.
4. Deploy it with runtime model name `Qwen/Qwen3-8B`. A running deployment is active immediately. This does not start containers.
5. Create project `voice-agent`, allow `qwen3-8b`, and create an API key. The raw key is shown once.
6. Call the gateway:

```powershell
curl http://127.0.0.1:8090/v1/chat/completions -H "Authorization: Bearer sk-gsm-..." -H "Content-Type: application/json" -d "{\"model\":\"qwen3-8b\",\"messages\":[{\"role\":\"user\",\"content\":\"سلام، خودت را معرفی کن.\"}]}"
```

Add `"stream": true` for SSE. The Playground page calls `/api/v1/playground/chat`, which uses the same router and runtime adapter as `/v1/chat/completions`.
