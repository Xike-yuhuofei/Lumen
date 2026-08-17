from __future__ import annotations

from deeptutor.services.provider_registry import find_by_model, find_by_name


def test_zhipu_provider_is_registered() -> None:
    spec = find_by_name("zhipu")
    assert spec is not None
    assert spec.env_key == "ZHIPU_API_KEY"
    assert spec.default_api_base == "https://open.bigmodel.cn/api/paas/v4"
    assert spec.display_name == "Zhipu AI"


def test_zhipu_model_name_routes_to_zhipu_provider() -> None:
    assert find_by_model("glm-4.7-flash").name == "zhipu"
    assert find_by_model("zhipu/glm-4.7-flash").name == "zhipu"
    assert find_by_model("bigmodel/glm-4.7-flash").name == "zhipu"
