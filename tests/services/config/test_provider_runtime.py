"""Tests for TutorBot-style runtime config adapter."""

from __future__ import annotations

import pytest

from lumen.shared.config.provider_runtime import (
    SEARCH_PROVIDERS,
    resolve_llm_runtime_config,
    resolve_search_runtime_config,
    search_fallback_candidates,
    search_missing_credential,
    search_provider_credentials,
)


@pytest.fixture(autouse=True)
def _clear_llm_lock(monkeypatch):
    """These tests exercise resolver mechanics with arbitrary catalogs; the
    fixed-production DeepSeek LLM lock (default ON) does not apply here."""
    monkeypatch.delenv("LUMEN_LLM_LOCK_MODEL", raising=False)
    monkeypatch.delenv("LUMEN_LLM_LOCK_BINDING", raising=False)
    # Bypass enforcement for catalogs that intentionally resolve non-DeepSeek.
    monkeypatch.setenv("LUMEN_LLM_LOCK_MODEL", "")
    monkeypatch.setenv("LUMEN_LLM_LOCK_BINDING", "")


def _build_catalog(
    *,
    llm_profile: dict | None = None,
    llm_model: dict | None = None,
    search_profile: dict | None = None,
    search_profiles: list[dict] | None = None,
) -> dict:
    llm_profile = llm_profile or {
        "id": "llm-p",
        "name": "LLM",
        "binding": "openai",
        "base_url": "",
        "api_key": "",
        "api_version": "",
        "extra_headers": {},
        "models": [{"id": "llm-m", "name": "m", "model": "gpt-4o-mini"}],
    }
    llm_model = llm_model or llm_profile["models"][0]
    search_profile = search_profile or {
        "id": "search-p",
        "name": "Search",
        "provider": "brave",
        "base_url": "",
        "api_key": "",
        "proxy": "",
        "models": [],
    }
    return {
        "version": 1,
        "services": {
            "llm": {
                "active_profile_id": llm_profile["id"],
                "active_model_id": llm_model["id"],
                "profiles": [llm_profile],
            },
            "embedding": {
                "active_profile_id": None,
                "active_model_id": None,
                "profiles": [],
            },
            "search": {
                "active_profile_id": search_profile["id"],
                "profiles": search_profiles or [search_profile],
            },
        },
    }


def test_llm_explicit_binding_and_headers() -> None:
    catalog = _build_catalog(
        llm_profile={
            "id": "llm-p",
            "name": "LLM",
            "binding": "dashscope",
            "base_url": "",
            "api_key": "dash-key",
            "api_version": "",
            "extra_headers": {"APP-Code": "abc"},
            "models": [{"id": "llm-m", "name": "q", "model": "qwen-max"}],
        }
    )
    resolved = resolve_llm_runtime_config(catalog=catalog)
    assert resolved.provider_name == "dashscope"
    assert resolved.provider_mode == "standard"
    assert resolved.effective_url == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert resolved.extra_headers == {"APP-Code": "abc"}


def test_llm_api_key_prefix_gateway(monkeypatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-key")
    catalog = _build_catalog(
        llm_profile={
            "id": "llm-p",
            "name": "LLM",
            "binding": "openrouter",
            "base_url": "",
            "api_key": "sk-or-test-key",
            "api_version": "",
            "extra_headers": {},
            "models": [{"id": "llm-m", "name": "m", "model": "gemini-2.5-pro"}],
        }
    )
    resolved = resolve_llm_runtime_config(catalog=catalog)
    assert resolved.provider_name == "openrouter"
    assert resolved.provider_mode == "gateway"
    assert resolved.effective_url == "https://openrouter.ai/api/v1"
    assert resolved.api_key == "sk-or-test-key"


def test_llm_openrouter_base_keyword_gateway() -> None:
    catalog = _build_catalog(
        llm_profile={
            "id": "llm-p",
            "name": "LLM",
            "binding": "",
            "base_url": "https://openrouter.ai/api/v1",
            "api_key": "sk-or-v1-test-key",
            "api_version": "",
            "extra_headers": {"APP-Code": "x"},
            "models": [{"id": "llm-m", "name": "m", "model": "claude-3-7-sonnet"}],
        }
    )
    resolved = resolve_llm_runtime_config(catalog=catalog)
    assert resolved.provider_name == "openrouter"
    assert resolved.provider_mode == "gateway"
    assert resolved.effective_url == "https://openrouter.ai/api/v1"
    assert resolved.extra_headers == {"APP-Code": "x"}


def test_llm_openrouter_binding_uses_default_endpoint() -> None:
    catalog = _build_catalog(
        llm_profile={
            "id": "llm-p",
            "name": "OpenRouter",
            "binding": "openrouter",
            "base_url": "",
            "api_key": "sk-or-v1-test-key",
            "api_version": "",
            "extra_headers": {},
            "models": [{"id": "llm-m", "name": "m", "model": "deepseek/deepseek-chat"}],
        }
    )
    resolved = resolve_llm_runtime_config(catalog=catalog)
    assert resolved.provider_name == "openrouter"
    assert resolved.provider_mode == "gateway"
    assert resolved.effective_url == "https://openrouter.ai/api/v1"


def test_llm_openrouter_base_url_detection_preserves_openai_binding_compatibility() -> None:
    catalog = _build_catalog(
        llm_profile={
            "id": "llm-p",
            "name": "OpenAI Compatible",
            "binding": "openai",
            "base_url": "https://openrouter.ai/api/v1",
            "api_key": "sk-or-v1-test-key",
            "api_version": "",
            "extra_headers": {},
            "models": [{"id": "llm-m", "name": "DeepSeek", "model": "deepseek/deepseek-chat"}],
        }
    )

    resolved = resolve_llm_runtime_config(catalog=catalog)

    assert resolved.provider_name == "openrouter"
    assert resolved.provider_mode == "gateway"
    assert resolved.effective_url == "https://openrouter.ai/api/v1"


def test_llm_local_fallback() -> None:
    catalog = _build_catalog(
        llm_profile={
            "id": "llm-p",
            "name": "LLM",
            "binding": "",
            "base_url": "http://localhost:11434/v1",
            "api_key": "",
            "api_version": "",
            "extra_headers": {},
            "models": [{"id": "llm-m", "name": "m", "model": "llama3.2"}],
        }
    )
    resolved = resolve_llm_runtime_config(catalog=catalog)
    assert resolved.provider_name == "ollama"
    assert resolved.provider_mode == "local"
    assert resolved.api_key == "sk-no-key-required"


def test_llm_deepseek_binding_uses_default_endpoint() -> None:
    catalog = _build_catalog(
        llm_profile={
            "id": "llm-p",
            "name": "LLM",
            "binding": "deepseek",
            "base_url": "",
            "api_key": "deepseek-key",
            "api_version": "",
            "extra_headers": {},
            "models": [{"id": "llm-m", "name": "m", "model": "deepseek-chat"}],
        }
    )
    resolved = resolve_llm_runtime_config(catalog=catalog)
    assert resolved.provider_name == "deepseek"
    assert resolved.provider_mode == "standard"
    assert resolved.effective_url == "https://api.deepseek.com"


def test_llm_anthropic_binding_uses_default_endpoint() -> None:
    catalog = _build_catalog(
        llm_profile={
            "id": "llm-p",
            "name": "LLM",
            "binding": "anthropic",
            "base_url": "",
            "api_key": "anthropic-key",
            "api_version": "",
            "extra_headers": {},
            "models": [{"id": "llm-m", "name": "c", "model": "claude-sonnet-4-6"}],
        }
    )
    resolved = resolve_llm_runtime_config(catalog=catalog)
    assert resolved.provider_name == "anthropic"
    assert resolved.provider_mode == "standard"
    assert resolved.effective_url == "https://api.anthropic.com/v1"


def test_llm_custom_anthropic_binding_stays_direct() -> None:
    catalog = _build_catalog(
        llm_profile={
            "id": "llm-p",
            "name": "LLM",
            "binding": "custom_anthropic",
            "base_url": "https://claude-proxy.example/v1/messages",
            "api_key": "anthropic-key",
            "api_version": "",
            "extra_headers": {"x-tenant": "lab"},
            "models": [{"id": "llm-m", "name": "c", "model": "claude-sonnet-4-20250514"}],
        }
    )
    resolved = resolve_llm_runtime_config(catalog=catalog)
    assert resolved.provider_name == "custom_anthropic"
    assert resolved.provider_mode == "direct"
    assert resolved.binding == "custom_anthropic"
    assert resolved.effective_url == "https://claude-proxy.example/v1/messages"
    assert resolved.extra_headers == {"x-tenant": "lab"}


def test_llm_ollama_binding_uses_local_default_endpoint() -> None:
    catalog = _build_catalog(
        llm_profile={
            "id": "llm-p",
            "name": "LLM",
            "binding": "ollama",
            "base_url": "",
            "api_key": "",
            "api_version": "",
            "extra_headers": {},
            "models": [{"id": "llm-m", "name": "m", "model": "llama3.2"}],
        }
    )
    resolved = resolve_llm_runtime_config(catalog=catalog)
    assert resolved.provider_name == "ollama"
    assert resolved.provider_mode == "local"
    assert resolved.effective_url == "http://localhost:11434/v1"
    assert resolved.api_key == "sk-no-key-required"


def test_llm_context_window_passes_through_from_catalog() -> None:
    catalog = _build_catalog(
        llm_profile={
            "id": "llm-p",
            "name": "LLM",
            "binding": "openai",
            "base_url": "https://api.openai.com/v1",
            "api_key": "sk-test",
            "api_version": "",
            "extra_headers": {},
            "models": [
                {
                    "id": "llm-m",
                    "name": "GPT 4o mini",
                    "model": "gpt-4o-mini",
                    "context_window": 128000,
                }
            ],
        }
    )
    resolved = resolve_llm_runtime_config(catalog=catalog)
    assert resolved.context_window == 128000


def test_llm_selection_overrides_active_model_without_mutating_catalog() -> None:
    profile_a = {
        "id": "p-a",
        "name": "OpenRouter",
        "binding": "openrouter",
        "base_url": "https://openrouter.ai/api/v1",
        "api_key": "sk-or-test",
        "api_version": "",
        "extra_headers": {},
        "models": [
            {
                "id": "m-a",
                "name": "Gemini",
                "model": "google/gemini-3-flash-preview",
            }
        ],
    }
    profile_b = {
        "id": "p-b",
        "name": "Local",
        "binding": "ollama",
        "base_url": "http://localhost:11434/v1",
        "api_key": "",
        "api_version": "",
        "extra_headers": {},
        "models": [{"id": "m-b", "name": "Llama", "model": "llama3.2"}],
    }
    catalog = _build_catalog(llm_profile=profile_a, llm_model=profile_a["models"][0])
    catalog["services"]["llm"]["profiles"].append(profile_b)

    resolved = resolve_llm_runtime_config(
        catalog=catalog,
        llm_selection={"profile_id": "p-b", "model_id": "m-b"},
    )

    assert resolved.model == "llama3.2"
    assert resolved.provider_name == "ollama"
    assert resolved.provider_mode == "local"
    assert catalog["services"]["llm"]["active_profile_id"] == "p-a"
    assert catalog["services"]["llm"]["active_model_id"] == "m-a"


def test_llm_reasoning_effort_resolves_from_catalog() -> None:
    catalog = _build_catalog(
        llm_profile={
            "id": "llm-p",
            "name": "LLM",
            "binding": "openai",
            "base_url": "https://api.openai.com/v1",
            "api_key": "sk-test",
            "api_version": "",
            "extra_headers": {},
            "models": [
                {
                    "id": "llm-m",
                    "name": "GPT 4o mini",
                    "model": "gpt-4o-mini",
                    "reasoning_effort": "high",
                }
            ],
        }
    )
    resolved = resolve_llm_runtime_config(catalog=catalog)
    assert resolved.reasoning_effort == "high"


def test_search_fallback_to_duckduckgo_without_key() -> None:
    catalog = _build_catalog(
        search_profile={
            "id": "search-p",
            "name": "Search",
            "provider": "brave",
            "base_url": "",
            "api_key": "",
            "proxy": "http://127.0.0.1:7890",
            "models": [],
        }
    )
    resolved = resolve_search_runtime_config(catalog=catalog)
    assert resolved.provider == "duckduckgo"
    assert resolved.requested_provider == "brave"
    assert resolved.fallback_reason is not None
    assert resolved.proxy == "http://127.0.0.1:7890"


def test_search_none_disables_runtime_provider() -> None:
    catalog = _build_catalog(
        search_profile={
            "id": "search-p",
            "name": "Search",
            "provider": "none",
            "base_url": "",
            "api_key": "",
            "proxy": "",
            "models": [],
        }
    )
    resolved = resolve_search_runtime_config(catalog=catalog)
    assert resolved.provider == "none"
    assert resolved.requested_provider == "none"
    assert resolved.status == "ok"


def test_search_marks_deprecated_provider() -> None:
    catalog = _build_catalog(
        search_profile={
            "id": "search-p",
            "name": "Search",
            "provider": "exa",
            "base_url": "",
            "api_key": "k",
            "proxy": "",
            "models": [],
        }
    )
    resolved = resolve_search_runtime_config(catalog=catalog)
    assert resolved.unsupported_provider is True
    assert resolved.deprecated_provider is True
    assert resolved.provider == "exa"


def test_search_perplexity_missing_credentials() -> None:
    catalog = _build_catalog(
        search_profile={
            "id": "search-p",
            "name": "Search",
            "provider": "perplexity",
            "base_url": "",
            "api_key": "",
            "proxy": "",
            "models": [],
        }
    )
    resolved = resolve_search_runtime_config(catalog=catalog)
    assert resolved.provider == "perplexity"
    assert resolved.unsupported_provider is False
    assert resolved.deprecated_provider is False
    assert resolved.missing_credentials is True


def test_search_serper_missing_credentials() -> None:
    catalog = _build_catalog(
        search_profile={
            "id": "search-p",
            "name": "Search",
            "provider": "serper",
            "base_url": "",
            "api_key": "",
            "proxy": "",
            "models": [],
        }
    )
    resolved = resolve_search_runtime_config(catalog=catalog)
    assert resolved.provider == "serper"
    assert resolved.unsupported_provider is False
    assert resolved.deprecated_provider is False
    assert resolved.missing_credentials is True


def test_search_searxng_without_url_fallback() -> None:
    catalog = _build_catalog(
        search_profile={
            "id": "search-p",
            "name": "Search",
            "provider": "searxng",
            "base_url": "",
            "api_key": "",
            "proxy": "",
            "models": [],
        }
    )
    resolved = resolve_search_runtime_config(catalog=catalog)
    assert resolved.provider == "duckduckgo"
    assert resolved.fallback_reason is not None


def _search_profile(pid: str, provider: str, **overrides) -> dict:
    profile = {
        "id": pid,
        "name": provider,
        "provider": provider,
        "base_url": "",
        "api_key": "",
        "proxy": "",
        "models": [],
    }
    profile.update(overrides)
    return profile


def test_search_missing_credential_names_the_field() -> None:
    assert search_missing_credential("brave", "", "") == "api_key"
    assert search_missing_credential("searxng", "", "") == "base_url"
    assert search_missing_credential("searxng", "", "https://searx.example.com") is None
    assert search_missing_credential("duckduckgo", "", "") is None
    assert search_missing_credential("exa", "", "") is None


def test_search_credentials_come_from_the_matching_profile(monkeypatch) -> None:
    monkeypatch.setenv("BRAVE_API_KEY", "brave-key")
    monkeypatch.setenv("TAVILY_API_KEY", "tavily-key")
    catalog = _build_catalog(
        search_profile=_search_profile("p-brave", "brave", api_key="brave-key"),
        search_profiles=[
            _search_profile("p-brave", "brave", api_key="brave-key"),
            _search_profile("p-tavily", "tavily", api_key="tavily-key"),
            _search_profile("p-searx", "searxng", base_url="https://searx.example.com"),
        ],
    )
    assert search_provider_credentials("brave", catalog=catalog) == ("brave-key", "")
    assert search_provider_credentials("tavily", catalog=catalog) == ("tavily-key", "")
    assert search_provider_credentials("searxng", catalog=catalog) == (
        "",
        "https://searx.example.com",
    )
    # A provider with no profile of its own gets nothing rather than borrowing
    # the active profile's key.
    assert search_provider_credentials("serper", catalog=catalog) == ("", "")


def test_search_fallback_candidates_skip_unconfigured_providers(monkeypatch) -> None:
    monkeypatch.setenv("BRAVE_API_KEY", "brave-key")
    monkeypatch.setenv("TAVILY_API_KEY", "tavily-key")
    catalog = _build_catalog(
        search_profile=_search_profile("p-brave", "brave", api_key="brave-key"),
        search_profiles=[
            _search_profile("p-brave", "brave", api_key="brave-key"),
            _search_profile("p-tavily", "tavily", api_key="tavily-key"),
            _search_profile("p-serper", "serper"),  # no key -> never a candidate
            _search_profile("p-none", "none"),  # explicit off -> never a candidate
        ],
    )
    assert search_fallback_candidates("brave", catalog=catalog) == ["tavily", "duckduckgo"]
    # The credential-free fallback is not appended when it is the requested
    # provider itself — the remaining configured providers are the chain.
    assert search_fallback_candidates("duckduckgo", catalog=catalog) == ["brave", "tavily"]


def test_every_search_provider_has_a_registered_implementation() -> None:
    from lumen.shared._util.search.providers import list_providers

    registered = set(list_providers())
    expected = {name for name in SEARCH_PROVIDERS if name != "none"}
    assert registered == expected


def test_llm_env_key_wins_over_legacy_catalog_api_key(monkeypatch) -> None:
    """A legacy plaintext ``api_key`` in the catalog is ignored — the runtime
    credential always comes from the environment variable."""
    catalog = _build_catalog(
        llm_profile={
            "id": "llm-p",
            "name": "LLM",
            "binding": "gitee",
            "base_url": "",
            "api_key": "sk-legacy-plaintext",
            "api_version": "",
            "extra_headers": {},
            "models": [{"id": "llm-m", "name": "m", "model": "Qwen3-8B"}],
        }
    )
    # No env var set -> clearly not configured, no fallback to the stored key.
    assert resolve_llm_runtime_config(catalog=catalog).api_key == ""
    # With the env var set, the environment value is the sole source.
    monkeypatch.setenv("GITEE_API_KEY", "sk-env-only")
    resolved = resolve_llm_runtime_config(catalog=catalog)
    assert resolved.api_key == "sk-env-only"
    assert "legacy" not in resolved.api_key


def test_llm_lock_blocks_non_deepseek_model(monkeypatch) -> None:
    from lumen.shared._util.llm.exceptions import LLMConfigError

    monkeypatch.delenv("LUMEN_LLM_LOCK_MODEL", raising=False)
    monkeypatch.delenv("LUMEN_LLM_LOCK_BINDING", raising=False)
    catalog = _build_catalog(
        llm_profile={
            "id": "llm-p",
            "name": "LLM",
            "binding": "openai",
            "base_url": "https://api.openai.com/v1",
            "api_key": "sk-test",
            "api_version": "",
            "extra_headers": {},
            "models": [{"id": "llm-m", "name": "m", "model": "gpt-4o-mini"}],
        }
    )
    # Default lock is ON -> resolving a non-DeepSeek model must fail loudly.
    try:
        resolve_llm_runtime_config(catalog=catalog)
        raise AssertionError("expected LLMConfigError for non-DeepSeek model")
    except LLMConfigError as exc:
        assert "deepseek-v4-flash" in str(exc)


def test_llm_lock_allows_deepseek_v4_flash(monkeypatch) -> None:
    monkeypatch.delenv("LUMEN_LLM_LOCK_MODEL", raising=False)
    monkeypatch.delenv("LUMEN_LLM_LOCK_BINDING", raising=False)
    catalog = _build_catalog(
        llm_profile={
            "id": "llm-p",
            "name": "DeepSeek",
            "binding": "deepseek",
            "base_url": "https://api.deepseek.com",
            "api_key": "sk-deepseek",
            "api_version": "",
            "extra_headers": {},
            "models": [{"id": "llm-m", "name": "deepseek-v4-flash", "model": "deepseek-v4-flash"}],
        }
    )
    resolved = resolve_llm_runtime_config(catalog=catalog)
    assert resolved.model == "deepseek-v4-flash"
    assert resolved.provider_name == "deepseek"


def test_llm_lock_bypass_when_env_cleared(monkeypatch) -> None:
    monkeypatch.setenv("LUMEN_LLM_LOCK_MODEL", "")
    monkeypatch.setenv("LUMEN_LLM_LOCK_BINDING", "")
    catalog = _build_catalog(
        llm_profile={
            "id": "llm-p",
            "name": "LLM",
            "binding": "openai",
            "base_url": "https://api.openai.com/v1",
            "api_key": "sk-test",
            "api_version": "",
            "extra_headers": {},
            "models": [{"id": "llm-m", "name": "m", "model": "gpt-4o-mini"}],
        }
    )
    # Explicitly cleared env vars skip enforcement (test escape hatch).
    resolved = resolve_llm_runtime_config(catalog=catalog)
    assert resolved.model == "gpt-4o-mini"
