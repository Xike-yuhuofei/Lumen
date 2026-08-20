"""Rendering service adapter plugin."""

from __future__ import annotations

from lumen.kernel.plugin import Plugin, PluginContext, PluginManifest
from lumen.shared.contract import RenderingService


class _RenderingServiceAdapter(RenderingService):
    """Wraps existing lumen text-processing utilities.

    Only lightweight text cleaning exists in the backend today; full
    Markdown / formula / Mermaid rendering lives in the frontend and is
    recorded as technical debt (see the Phase 3 report).
    """

    def strip_markdown(self, text: str) -> str:
        from lumen.shared._util.rendering_text import strip_markdown_for_speech

        return strip_markdown_for_speech(text)

    def clean_thinking_tags(self, text: str) -> str:
        from lumen.shared._util.rendering_text import clean_thinking_tags

        return clean_thinking_tags(text)


class RenderingPlugin(Plugin):
    """Provide lightweight text rendering as ``rendering``."""

    manifest = PluginManifest(id="rendering", provides=["rendering"])

    async def setup(self, ctx: PluginContext) -> None:
        ctx.provide("rendering", _RenderingServiceAdapter())
