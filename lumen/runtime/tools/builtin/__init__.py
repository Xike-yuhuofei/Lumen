"""Built-in tool implementations (canonical home).

The tool *class* wrappers that get registered in the runtime registry live in
``deeptutor/tools/builtin`` while the legacy namespace is being converged;
their stateless implementation functions (LLM calls, RAG search, notebook
writes, web fetch/search, cron) live here in ``lumen/runtime/tools/builtin``
as the canonical Source of Truth.  ``deeptutor/tools/<name>`` re-exports
these for existing importers and tests only.
"""
