# Lumen — Agent-Native Architecture

## ⚠️ Phase: Product Capability Development

**Architecture Baseline v1 已冻结 (2026-08-18).**

Lumen 已从 **Architecture Migration 阶段** 正式进入 **Product Capability Development 阶段**.
架构收敛已完成；后续开发重心转向 `Learn / News / Review` 产品能力建设。

**冻结规则：**
- 不得重新讨论已冻结的架构决策（见 `ARCHITECTURE_V1.md`）
- 不得主动清理 `deeptutor/` 历史痕迹
- 不得在无 bake-off 证据的情况下切换 Production Agent Loop Provider
- 所有架构变更必须通过 Architecture Gates 验证

详细基线见 `ARCHITECTURE_V1.md`.

## Overview

Lumen is an **agent-native** intelligent learning companion organized
around a Plugin Kernel runtime — single-shot **Tools** invoked by the
LLM plus one product **Mode** (`mode.learn`) — exposed through three
entry points: CLI, WebSocket API, and Python SDK.

## Architecture

```
Entry Points:  CLI (Typer)  |  WebSocket /api/v1/ws  |  Python SDK  |  Cron
                    ↓                   ↓                   ↓            ↓
              ┌──────────────────────────────────────────────────────────┐
              │  TurnRuntimeManager / DeepTutorApp (turn orchestration)  │
              └────────────────────────────┬─────────────────────────────┘
                                          ↓
                     LumenBootstrap (Plugin Kernel: profile → boot)
                                          ↓
        ┌─────────────────────────────────┴───────────────────────────┐
        │  Learn request → mode.learn → runtime.agent_loop            │
        │  Generic turn  → runtime.agent_loop                         │
        └─────────────────────────────────┬───────────────────────────┘
                                          ↓
                    Legacy Provider (AgenticChatPipeline) + ToolRegistry
```

Every turn — Learn or generic, from WS / CLI / Cron / SDK — converges on
the same `runtime.agent_loop` Runtime contract. The production assembly
is booted by the FastAPI lifespan (server) or on demand at first turn
(CLI / SDK / Cron); a boot failure is fatal rather than falling back to
a deprecated assembly. Turns emit on a shared `StreamBus`. Runtime
settings live in `data/user/settings/*.json` — project-root `.env` files
are intentionally ignored.

### Kernel / Runtime / Shared / Modes / App

| Layer   | Location                            | Owns                                              |
| ------- | ----------------------------------- | ------------------------------------------------- |
| Kernel  | `lumen/kernel/`                     | Plugin Kernel: bootstrap, profile, registry       |
| Runtime | `lumen/runtime/`                    | `runtime.*` contracts + providers (agent_loop, llm, tools, session, prompt) |
| Shared  | `lumen/shared/`                     | knowledge / memory / notebook / rendering services |
| Modes   | `lumen/modes/learn/`                | `mode.learn` — the only product mode              |
| App     | `lumen/bootstrap.py`, `lumen/profile.py`, `lumen/app/facade.py`, `lumen/app/api/` | Profile assembly + App facade + Web/API |

`chat` is **not** a product mode: a generic agent turn is a Runtime
concern routed straight into `runtime.agent_loop`. Legacy
`mastery_path` / `mastery` names are transport-level compatibility
aliases mapped to `mode.learn` (`lumen/compat.py`); they are not
product capabilities.

### Tools

Single-function tools the LLM picks on demand. Three user-toggleable
tools surface in `/settings/tools`:

| Tool           | Description                                   |
| -------------- | --------------------------------------------- |
| `brainstorm`   | Breadth-first idea exploration with rationale |
| `web_search`   | Web search with citations                     |
| `reason`       | Dedicated deep-reasoning LLM call             |

The rest are **context-gated**: the chat pipeline auto-mounts them from
`ToolMountFlags` (presence of a KB, attachments, sandbox availability, …),
and any of them can also be force-enabled via `--tool`. Auto-mounted
set: `rag`, `kb_files`, `read_source`, `read_memory`, `write_memory`,
`code_execution` (sandboxed compile+run for python/c/cpp),
`list_notebook`, `write_note`, `web_fetch`, `cron`,
`ask_user` (pauses the turn and resumes with the user's reply), plus
the Learn (mode.learn) mastery tools.

## CLI Usage

```bash
# Install
pip install deeptutor      # Full app (CLI + Web/API + packaged Web assets)
pip install deeptutor-cli  # CLI-only

# Run a turn
deeptutor run chat "Explain Fourier transform"
deeptutor run mastery_path "Master vector calculus" --kb textbook   # Learn (mode.learn); CLI compat name mastery_path

# Interactive REPL
deeptutor chat
# (inside the REPL: /regenerate or /retry re-runs the last user message)

# Sessions, config, server
deeptutor session list
deeptutor config show
deeptutor serve --port 8001       # API server only
deeptutor start                   # backend + frontend together
```

## Key Files

| Path                                       | Purpose                              |
| ------------------------------------------ | ------------------------------------ |
| `lumen/bootstrap.py`                       | `LumenBootstrap` — Plugin Kernel composition root + active-assembly bridge |
| `lumen/profile.py`                         | Production profile (Runtime + Shared + mode.learn plugins) |
| `lumen/kernel/`                            | Plugin Kernel (bootstrap / profile / registry / resolver) |
| `lumen/runtime/`                           | Runtime contracts + providers (`agent_loop`, `llm`, `tools`, `session`, `prompt`) |
| `lumen/shared/`                            | Shared service contracts + providers (knowledge / memory / notebook / rendering) |
| `lumen/modes/learn/`                       | `mode.learn` — Learn mode plugin, teaching domain, learner state |
| `lumen/compat.py`                          | `mastery_path` / `mastery` → `mode.learn` alias mapping |
| `lumen/runtime/session/turn_runtime.py`   | `TurnRuntimeManager` — turn orchestration (WS/CLI/Cron/SDK turns) |
| `lumen/app/cron/executor.py`              | Cron job execution via `runtime.agent_loop` |
| `lumen/runtime/agent_loop/providers/legacy/` | Legacy Agent Loop Provider (`AgenticChatPipeline` — production agent loop) |
| `lumen/app/launcher.py`                    | Backend + frontend lifecycle / port discovery |
| `lumen/runtime/tools/registry.py`          | Tool registry                      |
| `lumen/shared/config/runtime_settings.py`  | JSON settings + process-env overrides |
| `lumen/runtime/stream/events.py`, `lumen/runtime/stream/bus.py` | StreamEvent protocol + async fan-out |
| `lumen/runtime/tool_protocol.py`           | `BaseTool` + `ToolDefinition`         |
| `lumen/runtime/context.py`                 | `UnifiedContext` dataclass            |
| `lumen/runtime/tools/builtin/__init__.py`  | All built-in tool wrappers           |
| `lumen/app/facade.py`                      | `DeepTutorApp` — Python SDK facade    |
| `deeptutor_cli/main.py`                    | Typer CLI entry point                |
| `lumen/app/api/routers/unified_ws.py`      | Unified WebSocket endpoint           |

## Dependency Layers

Public install paths and source extras are defined in `pyproject.toml`.
Requirements files mirror the same dependency groups for Docker/CI installs.

```
pip install deeptutor      — Full app (CLI + Web/API + packaged Web assets)
pip install deeptutor-cli  — CLI-only (LLM + RAG + providers + document parsing)
pip install -e .           — Source install for development

Source extras (.[ extra ], defined in pyproject.toml):
.[cli]            — CLI-only dependency set
.[server]         — Web/API server dependencies
.[parse]          — Extra document-parsing engines
.[dev]            — Test / lint tooling
.[all]            — Everything above
```
