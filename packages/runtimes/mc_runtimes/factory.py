from mc_shared.crypto import decrypt_secret
from mc_shared.errors import PlatformError
from mc_shared.models import Runtime
from mc_shared.settings import get_settings
from mc_runtimes.local import LocalRuntime
from mc_runtimes.ollama import OllamaRuntime
from mc_runtimes.openai_compatible import OpenAICompatibleRuntime
from mc_runtimes.vllm import VLLMRuntime
from mc_runtimes.base import ModelRuntime


def build_runtime(runtime: Runtime) -> ModelRuntime:
    timeout = get_settings().request_timeout_seconds
    api_key = decrypt_secret(runtime.api_key_encrypted) if runtime.api_key_encrypted else ""
    kind = runtime.type
    if kind == "local":
        return LocalRuntime(runtime.endpoint, api_key, timeout)
    if kind == "ollama":
        return OllamaRuntime(runtime.endpoint, api_key, timeout)
    if kind == "vllm":
        return VLLMRuntime(runtime.endpoint, api_key, timeout)
    if kind in {"openai_compatible", "custom"}:
        return OpenAICompatibleRuntime(runtime.endpoint, api_key, timeout)
    raise PlatformError("runtime_unavailable", "Runtime type is not supported.", 503)
