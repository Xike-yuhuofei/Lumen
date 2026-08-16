# Lumen 最终后端裁剪执行报告

> 基线：`V4FM-Lumen最小后端能力与调用链审计报告.md`，所有判断基于当前最新 `main`。
> 目标：将 Lumen 基于 DeepTutor 的通用后端裁剪为**专门服务学习场景的 AI 教学后端**，
> 彻底移除与 Lumen 定位无关的 DeepTutor 通用平台能力，同时保证核心学习能力不被破坏。

---

## 0. 结论速览

| 项目 | 数值 |
| --- | --- |
| 变更文件数 | **199**（+126 / −23,477 行） |
| 删除源码文件 | **91** 个（deeptutor/ 下） |
| 删除测试文件 | **29** 个（tests/ 下） |
| 删除后 Capability | **6** 个（chat / deep_solve / deep_question / deep_research / visualize / mastery_path） |
| 删除后注册 Tool | **31** 个（无缺失引用） |
| pytest 回归 | **3461 passed, 8 skipped, 6 failed（均为既有基线/环境失败，与本次裁剪无关）** |
| `validate_tool_consistency()` | ✅ 通过 |
| import 冒烟 | ✅ 23 个核心模块全部导入成功 |
| 残余引用扫描 | ✅ 无已删除模块的代码引用 |

---

## 1. 删除内容清单

### 1.1 能力（Capability）—— 全部删除

| 删除项 | 目录 / 文件 |
| --- | --- |
| Math Animator 能力 | `deeptutor/agents/math_animator/`（含 agents / prompts en+zh / capability / pipeline / renderer / retry_manager 等） |
| ExploreContext 能力 | `deeptutor/capabilities/explore_context/` |
| Obsidian 能力 | `deeptutor/capabilities/obsidian/` |
| Subagent 能力 | `deeptutor/capabilities/subagent/` |

### 1.2 服务（Service）—— 全部删除

| 删除项 | 目录 / 文件 |
| --- | --- |
| MCP 服务 | `deeptutor/services/mcp/`（manager / config / catalog / oauth / secrets / pageindex_server / session_state / user_config / network） |
| Subagent 驱动层 | `deeptutor/services/subagent/`（base / claude_code / codex / gemini / kimi / opencode_family / partner / process / registry / sessions / models / images / config / types） |
| ImageGen 服务 | `deeptutor/services/imagegen/` |
| VideoGen 服务 | `deeptutor/services/videogen/` |
| 媒体生成 HTTP 公共层 | `deeptutor/services/generation_http.py` |

### 1.3 工具（Tool）—— 全部删除

| 删除项 | 文件 / 注册项 |
| --- | --- |
| 媒体生成工具 | `deeptutor/tools/media_gen_tool.py`（ImagegenTool / VideogenTool） |
| 子代理咨询工具 | `consult_subagent`（随 Subagent 能力一并移除） |
| Obsidian 工具 | `obsidian_read` / `obsidian_list`（随 Obsidian 能力一并移除） |

### 1.4 路由（Router）—— 全部删除

| 删除项 | 文件 |
| --- | --- |
| MCP 设置路由 | `deeptutor/api/routers/mcp_settings.py` |
| Space MCP 路由 | `deeptutor/api/routers/space_mcp.py` |
| Subagents 路由 | `deeptutor/api/routers/subagents.py` |
| Obsidian 连接路由 | `deeptutor/api/routers/knowledge.py` 中 `POST /connect-obsidian`（及 `ConnectObsidianRequest`） |

### 1.5 注册表 / 启动链清理

- `deeptutor/capabilities/registry.py`：`LOOP_CAPABILITIES` 只保留 solve / mastery；移除 `any_exclusive_capability_active`
- `deeptutor/runtime/bootstrap/builtin_capabilities.py`：`BUILTIN_CAPABILITY_CLASSES` 移除 math_animator
- `deeptutor/tools/builtin/__init__.py`：`BUILTIN_TOOL_TYPES` / `USER_TOGGLEABLE_TOOL_NAMES` 移除 imagegen / videogen / obsidian / subagent 工具
- `deeptutor/api/main.py`：移除 MCP / Subagents 路由导入与注册，清理 lifespan 中相关启动项
- `deeptutor/capabilities/protocol.py`：删除 `KnowledgeCapability`（唯一的两个子类 Obsidian / Subagent 能力已删除，成为死代码）

### 1.6 下游引用 / 兼容代码清理

| 文件 | 清理内容 |
| --- | --- |
| `deeptutor/agents/chat/agentic_pipeline.py` | 移除 `_GENERATION_TOOL_SERVICES` / `_drop_unconfigured_generation_tools`、imagegen/videogen 分支、consult_subagent trace 分支、`_exclusive_capability_active` / `_capability_owned_kbs` / `_coexisting_rag_kbs`，简化 KB seed 与 KB note 逻辑；`has_sources=True` 恢复 `read_source` 挂载 |
| `deeptutor/services/session/turn_runtime.py` | 移除 `subagent_consult_budget` 运行时配置键 |
| `deeptutor/services/setup/init.py` | 移除 math_animator 的 agents 默认配置与目录结构 |
| `deeptutor/app/facade.py` | 移除 `get_capability_availability` 中 math_animator 的 manim 探测分支 |
| `deeptutor/services/prompt/manager.py` | `MODULES` 移除 math_animator |
| `deeptutor/services/config/model_catalog.py` | `services` 移除 imagegen / videogen（llm/embedding/search/tts/stt 保留） |
| `deeptutor/services/config/capabilities_settings.py` / `loader.py` / `provider_runtime.py` / `test_runner.py` / `path_service.py` | 移除对已删模块的路径 / 配置 / 探测引用 |
| `deeptutor/api/utils/tool_options.py` / `api/routers/knowledge.py` | 移除 MCP reload 与 MCP manager 引用 |
| `deeptutor/agents/research/pipeline.py` | 移除 obsidian_read / obsidian_list 引用与 `RESEARCH_OBSIDIAN_READ_TOOLS`（__all__ 中的失效导出已清除） |
| `deeptutor/knowledge/kb_types.py` / `manifest.py` / `manager.py` | 移除 `OBSIDIAN_KB_TYPE` / `SUBAGENT_KB_TYPE` / `UNAVAILABLE_AGENT` 与 subagent 连接字段 |
| `deeptutor/book/` | 移除 Manim 动画块（`book/blocks/animation.py` 及 page_planner / spine_agent 提示词中的 manim 引用） |
| `deeptutor/core/i18n.py` | 移除 MCP 配置 UI 的 12 个 en/zh i18n 键 |
| `deeptutor/agents/visualize/` | 移除 manim_video / manim_image 渲染类型与提示词 |
| `deeptutor/agents/chat/prompts/en+zh/agentic_chat.yaml`、`agents/_shared/`、`agents/chat/agent_loop.py` 等 | 清理 obsidian / subagent / math_animator 残留注释 |

### 1.7 依赖（Dependency）清理

- `pyproject.toml`：移除 `[project.optional-dependencies].math-animator` extra 及其在 `all` 中的引用
- `requirements/math-animator.txt`：删除
- `requirements.txt`：移除 math-animator 安装注释
- 注：`mcp` pip 包保留 —— 它同时被保留的 CodeBuddy provider（SDK MCP server）使用，且 `runtime/providers` 授权框架仍依赖它

### 1.8 测试清理（29 个文件）

- `tests/agents/math_animator/*`（4 个）、`tests/core/test_math_animator_capability.py`
- `tests/capabilities/test_explore_context_capability.py` / `test_obsidian_capability.py` / `test_subagent_capability.py`
- `tests/knowledge/test_obsidian_kb.py` / `test_subagent_connection_kb.py`
- `tests/api/test_mcp_settings_auth.py` / `test_space_mcp.py` / `test_subagents_router.py` / `test_pageindex_mcp.py`
- `tests/services/mcp/*`（8 个）、`tests/services/test_media_gen.py`、`tests/services/test_subagent_backends.py`
- `tests/runtime/test_request_contracts_subagent.py`
- 同步更新：`test_kb_files_tool.py`、`test_kb_seed_context.py`、`test_tools_router.py`、`test_model_catalog.py`、`test_runtime_settings.py`、`test_knowledge_router.py`、`test_tool_options.py`、`test_manifest.py`、`test_prompt_manager.py`、`test_status_i18n_consistency.py`、`test_capabilities_runtime.py`、`test_context_budget.py`、`test_path_service.py`、`test_agent_loop.py`、`test_chat_cli.py` 等

> 说明：前序会话曾删除多组测试（multi_user / partners / skill / codex_auth / cli_apps / book / scripts / packaging / matrix），
> 经复核这些源码均属**保留能力**，本报告将其恢复，仅保留与已删除能力对应的测试。

---

## 2. 保留内容（Lumen 核心学习能力）

### 2.1 能力（6 个）

`chat`（默认 agent loop）· `deep_solve` · `deep_question` · `deep_research` · `visualize` · `mastery_path`

### 2.2 保留的子系统

- **Knowledge / RAG**：LlamaIndex 默认管道 + 知识库管理 / embedding / parsing / manifest / kb_files / rag 工具
- **Memory / Notebook / Skill / Persona**：三层记忆、笔记本、技能、人格系统
- **Learning / Book**：mastery_path（Guided Learning）、Book 引擎（保留文本 / 交互 / 测验等块，移除 Manim 动画块）
- **Attachments / Outputs / Voice**：附件、输出、语音
- **Auth / Multi-user**：登录、多用户隔离、资源授权
- **Model Selection**：llm / embedding / search / tts / stt 模型目录
- **Runtime / Registry**：orchestrator、tool/capability registry、providers（外部工具授权框架 + CLI apps）
- **LLM Core**：provider 体系（openai/anthropic/azure/custom/codebuddy 等）、agentic engine

### 2.3 保留的服务目录

```
deeptutor/services/
  cli_apps/  codex_auth/  config/  cron/  embedding/  llm/  memory/  model_selection/
  notebook/  parsing/  partners/  prompt/  provider_registry.py  rag/  sandbox/  search/
  session/  settings/  setup/  skill/  storage/  voice/  auth.py  codebuddy_auth.py  ...
```

---

## 3. 代码量 / 依赖变化

| 维度 | 变更 |
| --- | --- |
| 总变更 | 199 文件，+126 / −23,477 行 |
| 源码删除 | 91 个文件（deeptutor/） |
| 测试删除 | 29 个文件（tests/） |
| 依赖删除 | `math-animator` extra（manim）、`requirements/math-animator.txt` |
| 保留依赖 | `mcp`（CodeBuddy provider 使用）、`partners`/`matrix` extras（另一批次范围） |

---

## 4. 验收结果（Definition of Done）

| 验收项 | 结果 |
| --- | --- |
| 6 个学习能力正常注册 | ✅ `chat / deep_solve / deep_question / deep_research / visualize / mastery_path` |
| `validate_tool_consistency()` | ✅ 无漂移（capability `tools_used` ⊆ 注册工具） |
| Tool 注册一致性 | ✅ 31 个工具；`imagegen / videogen / consult_subagent / obsidian_*` 均不存在 |
| import 冒烟 | ✅ 23 个核心模块导入成功（app / api.main / orchestrator / capabilities / agentic_pipeline / knowledge / services 等） |
| pytest 全量回归 | ✅ **3461 passed, 8 skipped, 6 failed**（见 §5） |
| 全仓残余引用扫描 | ✅ 无 `deeptutor.services.mcp` / `subagent` / `math_animator` / `imagegen` / `videogen` / `UNAVAILABLE_AGENT` / `OBSIDIAN_KB_TYPE` / `connect-obsidian` 等代码引用 |
| 前端清理 | ✅ `frontend/src/api/tools.ts` 移除 imagegen / videogen 标签 |
| 文档清理 | ✅ README / SKILL.md / AGENTS.md / deeptutor_cli/README.md 移除 math_animator / consult_subagent / imagegen / videogen / My Agents 章节 |

---

## 5. pytest 失败项（均为既有基线 / 环境，与本次裁剪无关）

| 失败测试 | 原因 | 分类 |
| --- | --- | --- |
| `test_prompt_manager.py::test_clear_cache_all` | solve 模块提示词文件缺失（`No prompt file found for solve/solve_agent`） | 既有基线（clean main 复现，已用 git stash 验证） |
| `test_prompt_manager.py::test_clear_cache_module_specific` | 同上 | 既有基线 |
| `test_codex_oauth_callback.py::test_codex_callback_endpoint_delivers_without_echoing_secrets` | 品牌文案遗留（页面输出 DeepTutor，测试期望 Lumen） | 既有基线（clean main 复现，Lumen 改名时遗留） |
| `test_partners_channel_schema.py::test_slack_*`（2 个） | 本地未安装 `slack_sdk` | 环境依赖（CI 安装 `requirements/partners.txt` 后通过） |
| `test_channel_manager.py::test_channel_registry_discovers_builtin_channels` | 本地未安装部分 IM 渠道 SDK（discord/telegram 等） | 环境依赖（CI 通过） |

---

## 6. 无法删除 / 保留的原因

| 项 | 原因 |
| --- | --- |
| `runtime/providers/`（authorize / scope / view / allowlist / deferred_tools） | 外部工具授权框架，同时服务于保留的 multi-user 授权、partners 工具白名单与 CLI apps；`authorize_mcp_tools` 为通用授权函数 |
| `services/cli_apps/` | 保留的外部 CLI 应用工具系统，被 `runtime/providers/view.py` 与 chat pipeline 使用 |
| `mcp` pip 依赖 | 保留的 CodeBuddy provider 通过 in-process SDK MCP server 使用 |
| `services/partners/`、`api/routers/partners.py` | Partners 体系为另一独立批次（chore/prune-partners，PR #1）的范围，本次不涉及 |
| `services/codex_auth/`、CodeBuddy / Codex provider | 属于 Model Selection / LLM Core 保留能力 |
| PageIndex / LightRAG / GraphRAG / IMA 管道 | 属于 RAG 单管道批次（chore/prune-rag）的范围，本次不涉及 |
| `deeptutor/learning/`、`deeptutor/book/` | Learning 与 Book 为明确保留的核心学习能力 |

---

## 7. 最终目录树（相关部分）

```
deeptutor/
├── agents/
│   ├── _shared/  chat/  notebook/  question/  research/  vision_solver/  visualize/
├── api/
│   ├── main.py  run_server.py  utils/
│   └── routers/  attachments auth book chat knowledge mastery_path memory notebook
│                 outputs partners personas question sessions settings skills tools unified_ws voice
├── book/                    # Book 引擎（文本/测验/交互块等，无 Manim 动画块）
├── capabilities/
│   ├── mastery/  solve/  protocol.py  registry.py
├── core/                    # agentic / stream / context / tool_protocol / i18n 等
├── knowledge/               # manager / manifest / kb_types / initializer / add_documents
├── learning/                # Learning（掌握度/间隔重复）
├── multi_user/              # Auth / 多用户
├── runtime/
│   ├── orchestrator.py  launcher.py  request_contracts.py
│   ├── bootstrap/  registry/  providers/
├── services/
│   ├── cli_apps/  codex_auth/  config/  cron/  embedding/  llm/  memory/  model_selection/
│   ├── notebook/  parsing/  partners/  prompt/  rag/  sandbox/  search/  session/
│   ├── settings/  setup/  skill/  storage/  voice/
├── tools/
│   ├── builtin/  (无 media_gen_tool.py / 无 obsidian / 无 subagent 工具)
```

---

## 8. 结论

本次最终裁剪从 **入口（api/main、注册表、lifespan）→ Runtime（orchestrator、registry、providers）→ Capability → Tool → Service → Config → 依赖** 全链路完成
对 MCP、Subagent、Obsidian、ExploreContext、Math Animator、ImageGen/VideoGen、Plugin 动态加载残余的移除，
并同步清理了 Router / Tool / Service / Config / CLI / 依赖 / 测试 / 兼容代码与前端无效项。

最终后端仅保留与 Lumen 学习产品直接相关的能力；核心学习能力（6 个 Capability、RAG/Book/Learning/Memory 等）验证正常，
`validate_tool_consistency()` 通过，pytest 全量回归通过（仅剩 6 个既有基线/环境失败），全仓扫描无已删除模块残留引用。
