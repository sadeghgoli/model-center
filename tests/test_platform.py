from httpx import AsyncClient

from tests.conftest import auth, token


async def test_login_and_rbac(client: AsyncClient) -> None:
    bad = await client.post("/api/v1/auth/login", json={"email": "admin@example.com", "password": "wrong-pass"})
    assert bad.status_code == 401
    access = await token(client)
    me = await client.get("/api/v1/auth/me", headers=auth(access))
    assert me.json()["data"]["role"] == "SUPER_ADMIN"
    user_access = await token(client, "user@example.com")
    denied = await client.post(
        "/api/v1/models",
        headers=auth(user_access),
        json={"name": "Qwen", "slug": "qwen3-8b"},
    )
    assert denied.status_code == 403


async def test_api_key_lifecycle_and_chat(client: AsyncClient, monkeypatch) -> None:
    access = await token(client)
    org = await client.post("/api/v1/organizations", headers=auth(access), json={"name": "GSM", "slug": "gsm"})
    org_id = org.json()["data"]["id"]
    project = await client.post(
        "/api/v1/projects",
        headers=auth(access),
        json={"organization_id": org_id, "name": "Voice", "slug": "voice", "rpm_limit": 2, "tpm_limit": 1000},
    )
    project_id = project.json()["data"]["id"]
    model = await client.post(
        "/api/v1/models",
        headers=auth(access),
        json={"name": "Qwen3 8B", "slug": "qwen3-8b", "display_name": "Qwen3 8B", "supports_tools": True, "supports_streaming": True},
    )
    model_id = model.json()["data"]["id"]
    other = await client.post(
        "/api/v1/organizations",
        headers=auth(access),
        json={"name": "Other", "slug": "other"},
    )
    hidden = await client.get(f"/api/v1/projects?organization_id={other.json()['data']['id']}", headers=auth(await token(client, "user@example.com")))
    assert hidden.status_code == 404
    runtime = await client.post(
        "/api/v1/runtimes",
        headers=auth(access),
        json={"organization_id": org_id, "name": "vLLM Server 01", "slug": "vllm-01", "type": "vllm", "endpoint": "http://runtime.test/v1"},
    )
    runtime_id = runtime.json()["data"]["id"]
    deployment = await client.post(
        "/api/v1/deployments",
        headers=auth(access),
        json={
            "model_id": model_id,
            "runtime_id": runtime_id,
            "name": "Qwen3 8B Production",
            "slug": "qwen3-prod",
            "runtime_model_name": "Qwen/Qwen3-8B",
        },
    )
    assert deployment.status_code == 201
    await client.post(f"/api/v1/projects/{project_id}/models", headers=auth(access), json={"model_id": model_id})
    created = await client.post(
        f"/api/v1/projects/{project_id}/api-keys",
        headers=auth(access),
        json={"name": "voice", "model_ids": [model_id]},
    )
    raw = created.json()["data"]["api_key"]
    assert raw.startswith("sk-gsm-")
    assert "key_hash" not in created.json()["data"]

    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "id": "chatcmpl-test",
                "object": "chat.completion",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "سلام"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
            }

    class FakeStream:
        status_code = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def aiter_lines(self):
            yield 'data: {"choices":[{"index":0,"delta":{"content":"سلام"}}]}'
            yield "data: [DONE]"

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, *args, **kwargs):
            assert kwargs["json"]["model"] == "Qwen/Qwen3-8B"
            assert kwargs["json"]["tools"][0]["function"]["name"] == "get_business_hours"
            return FakeResponse()

        def stream(self, *args, **kwargs):
            return FakeStream()

        async def get(self, *args, **kwargs):
            class Health:
                status_code = 200
                text = ""

            return Health()

    monkeypatch.setattr("mc_runtimes.openai_compatible.httpx.AsyncClient", FakeClient)
    chat = await client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {raw}"},
        json={
            "model": "qwen3-8b",
            "messages": [{"role": "user", "content": "سلام"}],
            "tools": [{"type": "function", "function": {"name": "get_business_hours", "parameters": {"type": "object"}}}],
        },
    )
    assert chat.status_code == 200
    assert chat.json()["choices"][0]["message"]["content"] == "سلام"
    streamed = await client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {raw}"},
        json={"model": "qwen3-8b", "stream": True, "messages": [{"role": "user", "content": "سلام"}]},
    )
    assert "data: [DONE]" in streamed.text
    missing = await client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer sk-gsm-nope"},
        json={"model": "qwen3-8b", "messages": []},
    )
    assert missing.status_code == 401
    assert missing.json()["error"]["code"] == "invalid_api_key"
    unknown = await client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {raw}"},
        json={"model": "missing-model", "messages": []},
    )
    assert unknown.status_code == 404
    dashboard = await client.get(f"/api/v1/dashboard?organization_id={org_id}", headers=auth(access))
    assert dashboard.json()["data"]["total_requests"] >= 2
    assert dashboard.json()["data"]["total_tokens"] >= 5
    key_id = created.json()["data"]["id"]
    revoked = await client.post(f"/api/v1/api-keys/{key_id}/revoke", headers=auth(access))
    assert revoked.status_code == 200
    after = await client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {raw}"},
        json={"model": "qwen3-8b", "messages": []},
    )
    assert after.status_code == 401


async def test_rate_limit_and_unhealthy_route(client: AsyncClient, monkeypatch) -> None:
    access = await token(client)
    org_id = (await client.post("/api/v1/organizations", headers=auth(access), json={"name": "GSM", "slug": "gsm"})).json()["data"]["id"]
    project_id = (
        await client.post(
            "/api/v1/projects",
            headers=auth(access),
            json={"organization_id": org_id, "name": "Voice", "slug": "voice", "rpm_limit": 1, "tpm_limit": 1000, "daily_request_limit": 10, "monthly_request_limit": 10},
        )
    ).json()["data"]["id"]
    model_id = (await client.post("/api/v1/models", headers=auth(access), json={"name": "Qwen3 8B", "slug": "qwen3-8b"})).json()["data"]["id"]
    runtime_id = (
        await client.post(
            "/api/v1/runtimes",
            headers=auth(access),
            json={"organization_id": org_id, "name": "vLLM", "slug": "vllm-01", "type": "openai_compatible", "endpoint": "http://runtime.test/v1"},
        )
    ).json()["data"]["id"]
    await client.post(
        "/api/v1/deployments",
        headers=auth(access),
        json={"model_id": model_id, "runtime_id": runtime_id, "name": "bad", "slug": "bad", "runtime_model_name": "bad"},
    )
    good = await client.post(
        "/api/v1/deployments",
        headers=auth(access),
        json={"model_id": model_id, "runtime_id": runtime_id, "name": "good", "slug": "good", "runtime_model_name": "Qwen/Qwen3-8B"},
    )
    from sqlalchemy import select
    from mc_shared import db as database
    from mc_shared.models import Deployment
    import uuid

    assert database.SessionLocal is not None
    async with database.SessionLocal() as session:
        rows = (await session.execute(select(Deployment))).scalars().all()
        for row in rows:
            if row.slug == "bad":
                row.health_status = "unhealthy"
        await session.commit()
    await client.post(f"/api/v1/projects/{project_id}/models", headers=auth(access), json={"model_id": model_id})
    raw = (
        await client.post(f"/api/v1/projects/{project_id}/api-keys", headers=auth(access), json={"name": "limited"})
    ).json()["data"]["api_key"]

    seen = {}

    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "choices": [{"message": {"role": "assistant", "content": "ok"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            }

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, *args, **kwargs):
            seen["model"] = kwargs["json"]["model"]
            return FakeResponse()

    monkeypatch.setattr("mc_runtimes.openai_compatible.httpx.AsyncClient", FakeClient)
    first_call = await client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {raw}"},
        json={"model": "qwen3-8b", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert first_call.status_code == 200
    assert seen["model"] == "Qwen/Qwen3-8B"
    limited = await client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {raw}"},
        json={"model": "qwen3-8b", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "rate_limit_exceeded"
    assert good.status_code == 201
    assert uuid.UUID(good.json()["data"]["id"])
