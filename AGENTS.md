# Lumen — Agent-Native Architecture

## ⚠️ Phase: Product Capability Development

**Architecture Baseline v1 已冻结 (2026-08-18).**

Lumen 已从 **Architecture Migration 阶段** 正式进入 **Product Capability Development 阶段**.
架构收敛已完成；后续开发重心转向 `Learn / News / Review` 产品能力建设。

**冻结规则：**
- 不得重新讨论已冻结的架构决策（见 `ARCHITECTURE_V1.md`）
- 不得主动清理 `lumen/` 历史痕迹
- 所有架构变更必须通过 Architecture Gates 验证

**Production Agent Loop — 决策更新 (2026-08-20)：** Production Provider 已
从 Legacy (P0) 切换为 **P1 `agent_loop.langgraph_thin`** (`PRODUCTION_PROFILE`
绑定 elect)。Legacy `AgentLoopPlugin` 仍注册为 shadowed provider，回退 P0 通过
`LUMEN_AGENT_LOOP_PROVIDER=legacy` 一个环境变量即可。此覆盖此前「Production =
LEGACY 不可变更」的冻结结论。

**Teaching Architecture — 决策更新 (2026-08-20 / COMPLETE)：PROMOTE B。**
`mode.learn` 教学架构正式采用 **Candidate B（Teaching Session Graph +
Agent Runtime）作为 Production Default**；`route_learn_turn` 对 Learn turn 恒
返回 `"graph"`。**Candidate A（teaching-hook + generic Agent Loop）已退役**，
从生产路径删除、不再作为默认或 fallback（无 `LUMEN_LEARN_*` 开关）。
Teaching Architecture Promotion **COMPLETE**。Phase-3 → Phase-4b → Phase-4c 的
A/B parity 证据保留在 `tests/modes/learn/eval/bakeoff/out_phase*/` 归档。
**依据为长期教学架构上限与已验证生产可行性，而非实测教学效果优势**；教学
效果 parity 仍稳定（A/B 逐字相等）。重新评估此决策需新证据（见
`ARCHITECTURE_V1.md` §6）。

**Production Operations — 决策冻结 (2026-08-20)：PRODUCTION OPERATIONS BASELINE。**
Lumen 2.0.0（commit `4b553e33`，tag `v2.0.0` = `production-release-v1`）的生产
运维状态已冻结为 **Production Operations Baseline**。新增运维能力：
- **SLI/SLO 监测**：`lumen/ops/`（`sli.py`/`capacity.py`/`monitor.py`）+ 无鉴权
  `GET /api/v1/health/detailed`（Turn/LLM/Tool/Retrieval/Persistence/Telemetry
  六链路 SLI + 容量/保留），阈值经 `LUMEN_SLO_*` 环境变量配置。
- **运维 CLI**：`lumenctl sli`、`lumenctl health --detailed`。
- **备份/恢复**：`deploy/lumen-backup`（SQLite 在线一致性快照 + sha256 manifest +
  轮换）、`deploy/lumen-restore`（manifest 校验 + 恢复前安全备份）。
- **生命周期**：metrics 摘要 7 天保留落地执行（`MetricsSummaryExporter` 裁剪）。
- 事故处置 Runbook、已知限制与验证证据：`docs/validation/lumen-production-operations-baseline-v1.md`。
- 全量回归 **2690 passed / 8 skipped / 0 failed**（干净环境；Provider key 需 unset）。

详细基线见 `ARCHITECTURE_V1.md`.

## Overview

Lumen is an **agent-native** intelligent learning companion organized
around a Plugin Kernel runtime — single-shot **Tools** invoked by the
LLM plus one product **Mode** (`mode.learn`) — exposed through three
entry points: CLI, WebSocket API, and Python SDK.

## Credential Policy (凭据规则)

- Provider API keys are read **only from environment variables** — the unified
  entry is `lumen/shared/config/credentials.py` (`get_provider_api_key`).
  Convention: `<BINDING>_API_KEY` (e.g. `GITEE_API_KEY`, `DEEPSEEK_API_KEY`,
  `ZHIPU_API_KEY`, `OPENAI_API_KEY`, `CODEXMANAGER_API_KEY`).
- Never write a plaintext API key into code, config files, logs, or Git.
  `model_catalog.json` intentionally stores no keys — any `api_key` field is
  stripped on load/save (`ModelCatalogService._normalize`), so it is never a
  credential source of truth.
- Local providers (ollama / vllm) may use the `sk-no-key-required` placeholder.
- Do not ask the user for API keys during development; read them from the
  environment (e.g. `source ~/.zshrc`). The `lumen init` wizard auto-detects
  env vars and only falls back to an interactive prompt when none is set.

## Architecture

```
Entry Points:  CLI (Typer)  |  WebSocket /api/v1/ws  |  Python SDK  |  Cron
                    ↓                   ↓                   ↓            ↓
              ┌──────────────────────────────────────────────────────────┐
              │  TurnRuntimeManager / LumenApp (turn orchestration)  │
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
pip install lumen      # Full app (CLI + Web/API + packaged Web assets)
pip install lumen-cli  # CLI-only

# Run a turn
lumen run chat "Explain Fourier transform"
lumen run mastery_path "Master vector calculus" --kb textbook   # Learn (mode.learn); CLI compat name mastery_path

# Interactive REPL
lumen chat
# (inside the REPL: /regenerate or /retry re-runs the last user message)

# Sessions, config, server
lumen session list
lumen config show
lumen serve --port 8001       # API server only
lumen start                   # backend + frontend together
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
| `lumen/runtime/agent_loop/providers/legacy/` | Legacy Agent Loop Provider (`AgenticChatPipeline` — P0 rollback; production default is P1 `langgraph_thin`) |
| `lumen/runtime/agent_loop/providers/langgraph_thin/` | P1 LangGraph Thin Agent Loop Provider — production Active Provider |
| `lumen/app/launcher.py`                    | Backend + frontend lifecycle / port discovery |
| `lumen/runtime/tools/registry.py`          | Tool registry                      |
| `lumen/shared/config/runtime_settings.py`  | JSON settings + process-env overrides |
| `lumen/runtime/stream/events.py`, `lumen/runtime/stream/bus.py` | StreamEvent protocol + async fan-out |
| `lumen/runtime/tool_protocol.py`           | `BaseTool` + `ToolDefinition`         |
| `lumen/runtime/context.py`                 | `UnifiedContext` dataclass            |
| `lumen/runtime/tools/builtin/__init__.py`  | All built-in tool wrappers           |
| `lumen/app/facade.py`                      | `LumenApp` — Python SDK facade    |
| `lumen_cli/main.py`                    | Typer CLI entry point                |
| `lumen/app/api/routers/unified_ws.py`      | Unified WebSocket endpoint           |

## Dependency Layers

Public install paths and source extras are defined in `pyproject.toml`.
Requirements files mirror the same dependency groups for Docker/CI installs.

```
pip install lumen      — Full app (CLI + Web/API + packaged Web assets)
pip install lumen-cli  — CLI-only (LLM + RAG + providers + document parsing)
pip install -e .           — Source install for development

Source extras (.[ extra ], defined in pyproject.toml):
.[cli]            — CLI-only dependency set
.[server]         — Web/API server dependencies
.[parse]          — Extra document-parsing engines
.[dev]            — Test / lint tooling
.[all]            — Everything above
```
