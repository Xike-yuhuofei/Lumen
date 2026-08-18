r"""Foundational agentic engine primitives.

These modules implement the chat-style ``\`\`LABEL\`\`+content`` LLM protocol as
reusable building blocks. Any capability that wants a streaming, label-driven
LLM loop (chat, solve step, etc.) composes them.

Canonical home: ``lumen/runtime/agent_loop/engine`` (migrated from
``deeptutor/core/agentic``).  ``deeptutor.core.agentic`` re-exports these for
existing importers and tests only.

Layering:

* :mod:`labels`         — protocol-label parsing (parametric label set).
* :mod:`messages`       — canonical message builders.
* :mod:`tool_arg_guard` — pre-dispatch validation of model tool arguments.

The remaining engine modules (``usage`` / ``client`` / ``labeled_step`` /
``tool_dispatch`` / ``loop``) still live under ``deeptutor.core.agentic``
until their ``lumen.shared._util.llm`` dependencies are canonicalized; they
import these primitives from this package.  (Their LLM deps now point at
``lumen.shared._util.llm``, the canonical LLM module.)
"""

from lumen.runtime.agent_loop.engine.labels import (
    LABEL_PROBE_MAX_CHARS,
    LABEL_UNKNOWN,
    classify_label,
    find_inline_labels,
    strip_label_probe_prefix,
)
from lumen.runtime.agent_loop.engine.messages import assistant_message_with_tool_calls
from lumen.runtime.agent_loop.engine.tool_arg_guard import (
    RequiredArg,
    missing_args_message,
    missing_required_args,
    required_args,
)

__all__ = [
    "LABEL_PROBE_MAX_CHARS",
    "LABEL_UNKNOWN",
    "RequiredArg",
    "assistant_message_with_tool_calls",
    "classify_label",
    "find_inline_labels",
    "missing_args_message",
    "missing_required_args",
    "required_args",
    "strip_label_probe_prefix",
]
