"""Localized display metadata for built-in tools and capabilities.

Canonical home: ``lumen/runtime/i18n/metadata_i18n`` (migrated from
``lumen/i18n/metadata_i18n``).  ``lumen.i18n`` re-exports these for
existing importers and tests only.
"""

from __future__ import annotations

_CAPABILITY_DESCRIPTIONS: dict[str, dict[str, str]] = {
    "chat": {
        "en": "Default agentic chat with tools, retrieval, memory, and attachments.",
        "zh": "默认智能聊天，支持工具、检索、记忆和附件。",
    },
}

_TOOL_DESCRIPTIONS: dict[str, dict[str, str]] = {
    "brainstorm": {
        "en": "Explore ideas broadly and organize them with rationale.",
        "zh": "广泛发散想法，并按理由组织结果。",
    },
    "code_execution": {
        "en": "Run sandboxed Python code for computation and data exploration.",
        "zh": "在沙箱中运行 Python，用于计算和数据探索。",
    },
    "kb_files": {
        "en": "List the documents a knowledge base holds, with the total count.",
        "zh": "列出知识库中的文档清单与总数。",
    },
    "reason": {
        "en": "Use a dedicated reasoning model call for hard reasoning tasks.",
        "zh": "调用专门的推理模型处理高难度推理任务。",
    },
    "web_search": {
        "en": "Search the web and return sourced results.",
        "zh": "联网搜索并返回带来源的结果。",
    },
}


def capability_description_i18n(name: str, fallback: str = "") -> dict[str, str]:
    values = _CAPABILITY_DESCRIPTIONS.get(name)
    if values:
        return dict(values)
    return {"en": fallback, "zh": fallback}


def tool_description_i18n(name: str, fallback: str = "") -> dict[str, str]:
    values = _TOOL_DESCRIPTIONS.get(name)
    if values:
        return dict(values)
    return {"en": fallback, "zh": fallback}


def localized_description(values: dict[str, str], language: str) -> str:
    lang = "zh" if (language or "en").lower().startswith("zh") else "en"
    return values.get(lang) or values.get("en") or values.get("zh") or ""


__all__ = [
    "capability_description_i18n",
    "localized_description",
    "tool_description_i18n",
]
