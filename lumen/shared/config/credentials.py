"""Provider API-key resolution — environment variables are the single source of truth.

Provider credentials (API keys / tokens) are never read from configuration
files. Any plaintext key that ends up in a persisted config is ignored at
runtime and stripped on load/save.

Unified conventions (applied across LLM / Embedding / Search / TTS / STT):

* Named providers map to a fixed environment variable (the LLM registry's
  ``ProviderSpec.env_key`` is canonical, e.g. ``OPENAI_API_KEY``,
  ``GITEE_API_KEY``, ``GEMINI_API_KEY``, ``DASHSCOPE_API_KEY``).
* Custom / direct bindings fall back to ``<BINDING>_API_KEY``
  (e.g. ``CUSTOM_API_KEY``).
* A missing or empty environment variable means "credentials not configured"
  and always resolves to ``""``. There is **never** a fallback to a
  config-file value.
"""

from __future__ import annotations

import os

from lumen.shared._util.provider_registry import find_by_name

# Embedding provider -> env var, overridden where the provider's LLM env key
# differs or the embedding binding has its own conventional key.
EMBEDDING_ENV_KEY: dict[str, str] = {
    "openai": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "azure_openai": "AZURE_OPENAI_API_KEY",
    "cohere": "COHERE_API_KEY",
    "jina": "JINA_API_KEY",
    "ollama": "OLLAMA_API_KEY",
    "vllm": "HOSTED_VLLM_API_KEY",
    "gitee": "GITEE_API_KEY",
    "siliconflow": "SILICONFLOW_API_KEY",
    "aliyun": "DASHSCOPE_API_KEY",
    "dashscope": "DASHSCOPE_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "orcarouter": "ORCAROUTER_API_KEY",
}

# Search provider -> env var. Mirrors the init wizard's preferred keys.
SEARCH_ENV_KEY: dict[str, str] = {
    "brave": "BRAVE_API_KEY",
    "tavily": "TAVILY_API_KEY",
    "jina": "JINA_API_KEY",
    "serper": "SERPER_API_KEY",
    "perplexity": "PERPLEXITY_API_KEY",
    "firecrawl": "FIRECRAWL_API_KEY",
    "doubao": "ARK_API_KEY",
    "bocha": "BOCHA_API_KEY",
    "zhipu": "ZHIPU_API_KEY",
    "qianfan": "QIANFAN_API_KEY",
    "aliyun_iqs": "ALIYUN_IQS_API_KEY",
}

# Voice / TTS / STT provider -> env var.
VOICE_ENV_KEY: dict[str, str] = {
    "openai": "OPENAI_API_KEY",
    "gitee": "GITEE_API_KEY",
    "dashscope": "DASHSCOPE_API_KEY",
}

_SERVICE_TABLES: dict[str, dict[str, str]] = {
    "llm": {},
    "embedding": EMBEDDING_ENV_KEY,
    "search": SEARCH_ENV_KEY,
    "voice": VOICE_ENV_KEY,
    "tts": VOICE_ENV_KEY,
    "stt": VOICE_ENV_KEY,
}


def _binding_env_name(binding: str) -> str:
    return binding.upper().replace("-", "_") + "_API_KEY"


def provider_env_key(binding: str | None) -> str:
    """Env-var name for *binding* under the LLM registry convention."""
    name = (binding or "").strip().lower()
    if not name:
        return ""
    spec = find_by_name(name)
    if spec is not None and spec.env_key:
        return spec.env_key
    return _binding_env_name(name)


def env_var_for_provider(binding: str | None, *, service_type: str = "llm") -> str:
    """Env-var name for a provider binding under a given service type.

    ``service_type`` ∈ ``{"llm", "embedding", "search", "voice", "tts", "stt"}``.
    Falls back to the LLM registry mapping, then to ``<BINDING>_API_KEY``.
    """
    name = (binding or "").strip().lower()
    if not name:
        return ""
    table = _SERVICE_TABLES.get(service_type or "llm")
    if table and name in table:
        return table[name]
    key = provider_env_key(name)
    if key:
        return key
    return _binding_env_name(name)


def get_provider_api_key(
    binding: str | None,
    *,
    service_type: str = "llm",
) -> str:
    """Return the configured API key for *binding*, or ``""`` when unset.

    Reads only from the process environment — never from any config file.
    """
    name = (binding or "").strip().lower()
    if not name:
        return ""
    env_var = env_var_for_provider(name, service_type=service_type)
    if not env_var:
        return ""
    value = os.environ.get(env_var, "").strip()
    return "" if not value else value


def is_provider_key_configured(
    binding: str | None,
    *,
    service_type: str = "llm",
) -> bool:
    """True when the provider's env var is present and non-empty."""
    return bool(get_provider_api_key(binding, service_type=service_type))


__all__ = [
    "EMBEDDING_ENV_KEY",
    "SEARCH_ENV_KEY",
    "VOICE_ENV_KEY",
    "provider_env_key",
    "env_var_for_provider",
    "get_provider_api_key",
    "is_provider_key_configured",
]