"""
Visualize Capability
====================

Unified visualization capability. AnalysisAgent picks one of four render
types — svg / chartjs / mermaid / html (text-emitting, three-stage pipeline).
The result envelope carries ``render_type`` as the discriminator so the
frontend can delegate to the right viewer.
"""

from __future__ import annotations

import logging
from typing import Any

from deeptutor.agents._shared.capability_result import emit_capability_result
from deeptutor.core.agentic.usage import UsageTracker
from deeptutor.core.capability_protocol import BaseCapability, CapabilityManifest
from deeptutor.core.context import UnifiedContext
from deeptutor.core.stream_bus import StreamBus
from deeptutor.core.trace import merge_trace_metadata
from deeptutor.i18n import StatusI18n
from deeptutor.runtime.request_contracts import (
    get_capability_request_schema,
    validate_visualize_request_config,
)

logger = logging.getLogger(__name__)

# Stages exposed in the manifest. The three stages cover the text-emitting
# path (svg/chartjs/mermaid/html). A given turn only streams a subset of these.
_VISUALIZE_STAGES = [
    "analyzing",
    "generating",
    "reviewing",
    "render_output",
]


class VisualizeCapability(BaseCapability):
    manifest = CapabilityManifest(
        name="visualize",
        description=("Generate SVG, Chart.js, Mermaid, or interactive HTML visualizations."),
        stages=_VISUALIZE_STAGES,
        tools_used=[],
        cli_aliases=["visualize", "viz"],
        request_schema=get_capability_request_schema("visualize"),
    )

    async def run(self, context: UnifiedContext, stream: StreamBus) -> None:
        from deeptutor.agents.visualize.models import ReviewResult
        from deeptutor.agents.visualize.pipeline import VisualizePipeline
        from deeptutor.agents.visualize.utils import (
            build_fallback_html,
            validate_visualization,
        )
        from deeptutor.services.llm.config import get_llm_config

        request_config = validate_visualize_request_config(context.config_overrides)
        render_mode = request_config.render_mode
        i18n = StatusI18n(self.name, context.language, module="visualize")

        llm_config_for_usage = get_llm_config()
        usage = UsageTracker(model=getattr(llm_config_for_usage, "model", None))

        llm_config = get_llm_config()
        history_context = str(context.metadata.get("conversation_context_text", "") or "").strip()

        pipeline = VisualizePipeline(
            api_key=llm_config.api_key,
            base_url=llm_config.base_url,
            api_version=llm_config.api_version,
            language=context.language,
            trace_callback=self._build_trace_bridge(stream, i18n=i18n),
        )

        # Stage 1: Analyze (routing decision)
        async with stream.stage("analyzing", source=self.name):
            await stream.thinking(
                i18n.t("analyzing", "Analyzing visualization requirements..."),
                source=self.name,
                stage="analyzing",
            )
            analysis = await pipeline.run_analysis(
                user_input=context.user_message,
                history_context=history_context,
                render_mode=render_mode,
                attachments=context.attachments,
            )
            await stream.progress(
                message=i18n.t(
                    "render_type_detected",
                    f"Render type: {analysis.render_type} — {analysis.description}",
                    render_type=analysis.render_type,
                    description=analysis.description,
                ),
                source=self.name,
                stage="analyzing",
            )

        # Stage 2: Generate code
        async with stream.stage("generating", source=self.name):
            await stream.thinking(
                i18n.t("generating", "Generating visualization code..."),
                source=self.name,
                stage="generating",
            )
            code = await pipeline.run_code_generation(
                user_input=context.user_message,
                history_context=history_context,
                analysis=analysis,
            )
            await stream.progress(
                message=i18n.t("code_generated", "Code generated."),
                source=self.name,
                stage="generating",
            )

        # Stage 3: Validate locally; repair only on failure.
        #
        # The old generic LLM review is replaced by a deterministic, zero-cost
        # local check (well-formed XML / strict-JSON / mermaid lint / HTML
        # sanity). When it passes we ship the draft as-is — saving a whole
        # serial LLM call. When it fails we spend one *targeted* repair call
        # driven by the concrete error, not an open-ended re-judgement.
        async with stream.stage("reviewing", source=self.name):
            ok, validation_error = validate_visualization(code, analysis.render_type)
            if ok:
                final_code = code
                review = ReviewResult(
                    optimized_code=final_code,
                    changed=False,
                    review_notes="Passed local validation.",
                )
                await stream.progress(
                    message=i18n.t(
                        "validation_passed",
                        "Looks good — passed local checks.",
                    ),
                    source=self.name,
                    stage="reviewing",
                )
            elif analysis.render_type == "html":
                # html documents are 8-16k tokens; we don't run them through
                # the repair loop — fall back to a minimal renderable template.
                final_code = build_fallback_html(
                    title=analysis.description or "Visualization",
                    summary=analysis.data_description,
                    note="The model did not return a renderable HTML document.",
                )
                review = ReviewResult(
                    optimized_code=final_code,
                    changed=True,
                    review_notes=f"Used fallback HTML template ({validation_error}).",
                )
                await stream.progress(
                    message=i18n.t(
                        "html_invalid_fallback",
                        "HTML did not validate; using fallback template.",
                    ),
                    source=self.name,
                    stage="reviewing",
                )
            else:
                await stream.thinking(
                    i18n.t("repairing", "Fixing a validation issue..."),
                    source=self.name,
                    stage="reviewing",
                )
                try:
                    review = await pipeline.run_repair(
                        user_input=context.user_message,
                        analysis=analysis,
                        code=code,
                        error=validation_error,
                    )
                except Exception as exc:
                    # Repair wraps code inside a JSON string field; large/complex
                    # SVGs can trip JSON-mode escaping. Fall back to the draft so
                    # the user still gets a rendered result.
                    logger.warning("Visualize repair failed (%s); using unvalidated draft.", exc)
                    review = ReviewResult(
                        optimized_code=code,
                        changed=False,
                        review_notes=f"Repair skipped due to error: {exc}",
                    )
                    final_code = code
                    await stream.progress(
                        message=i18n.t(
                            "repair_skipped_error",
                            "Repair skipped — using draft as-is.",
                        ),
                        source=self.name,
                        stage="reviewing",
                    )
                else:
                    final_code = review.optimized_code or code
                    repaired_ok, repaired_error = validate_visualization(
                        final_code, analysis.render_type
                    )
                    if repaired_ok:
                        await stream.progress(
                            message=i18n.t(
                                "code_repaired",
                                f"Fixed: {review.review_notes}",
                                notes=review.review_notes,
                            ),
                            source=self.name,
                            stage="reviewing",
                        )
                    else:
                        await stream.progress(
                            message=i18n.t(
                                "repair_incomplete",
                                f"Repair attempted; residual issue: {repaired_error}",
                                error=repaired_error,
                            ),
                            source=self.name,
                            stage="reviewing",
                        )

        # Emit final content as a fenced code block for the chat area
        if analysis.render_type == "svg":
            lang_tag = "svg"
        elif analysis.render_type == "mermaid":
            lang_tag = "mermaid"
        elif analysis.render_type == "html":
            lang_tag = "html"
        else:
            lang_tag = "javascript"
        content_md = f"```{lang_tag}\n{final_code}\n```"
        await stream.content(content_md, source=self.name, stage="reviewing")

        # Structured result for the frontend viewer
        await emit_capability_result(
            stream,
            {
                "response": content_md,
                "render_type": analysis.render_type,
                "code": {
                    "language": lang_tag,
                    "content": final_code,
                },
                "analysis": analysis.model_dump(),
                "review": review.model_dump(),
            },
            source=self.name,
            usage=usage,
        )

    def _build_trace_bridge(self, stream: StreamBus, i18n: StatusI18n | None = None):
        async def _trace_bridge(update: dict[str, Any]) -> None:
            event = str(update.get("event", "") or "")
            stage = str(update.get("phase") or update.get("stage") or "analyzing")
            base_metadata = {
                key: value
                for key, value in update.items()
                if key
                not in {"event", "state", "response", "chunk", "result", "tool_name", "tool_args"}
            }

            if event != "llm_call":
                return

            state = str(update.get("state", "running"))
            label = str(base_metadata.get("label", "") or stage.replace("_", " ").title())
            if state == "running":
                await stream.progress(
                    message=label,
                    source=self.name,
                    stage=stage,
                    metadata=merge_trace_metadata(
                        base_metadata,
                        {"trace_kind": "call_status", "call_state": "running"},
                    ),
                )
                return
            if state == "streaming":
                chunk = str(update.get("chunk", "") or "")
                if chunk:
                    await stream.thinking(
                        chunk,
                        source=self.name,
                        stage=stage,
                        metadata=merge_trace_metadata(
                            base_metadata,
                            {"trace_kind": "llm_chunk"},
                        ),
                    )
                return
            if state == "complete":
                was_streaming = update.get("streaming", False)
                if not was_streaming:
                    response = str(update.get("response", "") or "")
                    if response:
                        await stream.thinking(
                            response,
                            source=self.name,
                            stage=stage,
                            metadata=merge_trace_metadata(
                                base_metadata,
                                {"trace_kind": "llm_output"},
                            ),
                        )
                await stream.progress(
                    message=label,
                    source=self.name,
                    stage=stage,
                    metadata=merge_trace_metadata(
                        base_metadata,
                        {"trace_kind": "call_status", "call_state": "complete"},
                    ),
                )
                return
            if state == "error":
                fallback = (
                    i18n.t("llm_call_failed", "LLM call failed.")
                    if i18n is not None
                    else "LLM call failed."
                )
                await stream.error(
                    str(update.get("response", "") or fallback),
                    source=self.name,
                    stage=stage,
                    metadata=merge_trace_metadata(
                        base_metadata,
                        {"trace_kind": "call_status", "call_state": "error"},
                    ),
                )

        return _trace_bridge
