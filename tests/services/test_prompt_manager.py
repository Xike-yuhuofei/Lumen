"""Prompt manager path resolution tests."""

from __future__ import annotations

from lumen.runtime.prompt import get_prompt_manager


def test_prompt_manager_loads_prompts_from_deeptutor_tree() -> None:
    manager = get_prompt_manager()
    manager.clear_cache()

    prompts = manager.load_prompts(
        module_name="chat",
        agent_name="agentic_chat",
        language="en",
    )

    assert "general" in prompts
