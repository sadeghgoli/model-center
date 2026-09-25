from mc_runtimes.openai_compatible import OpenAICompatibleRuntime


class VLLMRuntime(OpenAICompatibleRuntime):
    """vLLM exposes an OpenAI-compatible server. This adapter does not import vLLM."""
