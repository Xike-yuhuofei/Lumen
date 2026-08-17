from deeptutor.services.provider_registry import find_by_name, find_gateway


def test_openrouter_gateway_detection_by_key_and_base() -> None:
    spec = find_by_name("openrouter")

    assert spec is not None
    assert spec.is_gateway is True
    assert spec.mode == "gateway"
    assert spec.default_api_base == "https://openrouter.ai/api/v1"
    assert find_gateway(api_key="sk-or-v1-abcdef") == spec
    assert find_gateway(api_base="https://openrouter.ai/api/v1") == spec


def test_retained_core_providers_resolve() -> None:
    for name in (
        "custom",
        "custom_anthropic",
        "azure_openai",
        "openai",
        "anthropic",
        "deepseek",
        "gemini",
        "dashscope",
        "ollama",
        "vllm",
    ):
        assert find_by_name(name) is not None, name


def test_pruned_providers_no_longer_resolve() -> None:
    """Cold providers removed from the registry must not resolve or be claimed."""
    for name in (
        "nvidia_nim",
        "atlascloud",
        "edenai",
        "novita",
        "orcarouter",
        "aihubmix",
        "siliconflow",
        "volcengine",
        "byteplus",
        "zhipu",
        "moonshot",
        "minimax",
        "mistral",
        "groq",
        "qianfan",
    ):
        assert find_by_name(name) is None, name

    # Former NVIDIA / OrcaRouter key formats no longer claim a gateway.
    assert find_gateway(api_key="nvapi-test-key") is None
    assert find_gateway(api_key="sk-orca-test-key") is None
    # OpenRouter keys still resolve to the retained gateway.
    assert find_gateway(api_key="sk-or-v1-abcdef").name == "openrouter"
