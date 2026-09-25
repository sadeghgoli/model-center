import httpx

from mc_runtimes.local import LocalRuntime
from mc_runtimes.ollama import OllamaRuntime
from mc_shared.errors import PlatformError


async def test_local_runtime_has_no_engine() -> None:
    runtime = LocalRuntime("")
    health = await runtime.health_check()
    assert health["status"] == "offline"
    try:
        await runtime.chat({"runtime_model_name": "local"}, {"model": "qwen3-8b", "messages": []})
        assert False
    except PlatformError as exc:
        assert exc.code == "runtime_unavailable"


async def test_runtime_timeout_and_offline() -> None:
    class TimeoutClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, *args, **kwargs):
            raise httpx.TimeoutException("slow")

    original = httpx.AsyncClient
    httpx.AsyncClient = TimeoutClient
    try:
        health = await OllamaRuntime("http://ollama:11434").health_check()
    finally:
        httpx.AsyncClient = original
    assert health["status"] == "offline"
    assert health["detail"] == "timeout"
