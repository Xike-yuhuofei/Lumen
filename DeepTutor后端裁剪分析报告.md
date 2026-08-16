# DeepTutor 后端裁剪分析报告

> 生成时间：2026-08-16  
> 分析目标：在不破坏 Lumen 必要功能和核心行为的前提下，裁剪冗余代码、依赖和配置

---

## 一、项目架构概览

### 1.1 总体代码统计

| 模块 | Python 文件数 | 代码行数 |
|------|:----------:|:-------:|
| `deeptutor/services` | 315 | 68,769 |
| `deeptutor/agents` | 63 | 17,540 |
| `deeptutor/api` | 40 | 15,883 |
| `deeptutor/partners` | 30 | 12,252 |
| `deeptutor/book` | 34 | 7,685 |
| `deeptutor/tools` | 30 | 7,604 |
| `deeptutor_cli` | 20 | 5,264 |
| `deeptutor/learning` | 22 | 4,692 |
| `deeptutor/capabilities` | 25 | 3,848 |
| `deeptutor/core` | 18 | 3,831 |
| `deeptutor/knowledge` | 8 | 3,556 |
| `deeptutor/runtime` | 23 | 3,516 |
| `deeptutor/multi_user` | 14 | 2,058 |
| `deeptutor/utils` | 8 | 1,681 |
| `deeptutor/logging` | 11 | 671 |
| `deeptutor/co_writer` | 3 | 623 |
| `deeptutor/events` | 2 | 220 |
| `deeptutor/app` | 2 | 219 |
| `deeptutor/config` | 6 | 153 |
| `deeptutor/i18n` | 3 | 183 |
| **总计** | **~661** | **~161,542** |

### 1.2 核心架构图

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           Entry Points (入口)                                │
├─────────────────────────────┬───────────────────────────────────────────────┤
│     CLI (deeptutor_cli)    │          WebSocket API (deeptutor/api)         │
│     ├─ chat                │          ├─ /api/v1/ws (统一 WebSocket)        │
│     ├─ run <capability>    │          ├─ /api/v1/chat                        │
│     ├─ serve               │          ├─ /api/v1/knowledge                  │
│     └─ ...                 │          └─ ...                                │
└─────────────────────────────┴───────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                    ChatOrchestrator (统一调度中心)                           │
│                    deeptutor/runtime/orchestrator.py                        │
├─────────────────────────────────────────────────────────────────────────────┤
│  路由 UnifiedContext → 选定 Capability（默认 chat）                         │
│  管理 StreamBus 生命周期                                                    │
│  发布 CAPABILITY_COMPLETE 事件                                              │
└─────────────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                  Capability Registry (能力注册表)                             │
│                  deeptutor/runtime/registry/capability_registry.py          │
├─────────────────────────────────────────────────────────────────────────────┤
│  内置能力:                                                                  │
│  ├─ chat              核心对话 (AgenticChatPipeline)                         │
│  ├─ deep_solve        求解 (DeepSolveCapability)                             │
│  ├─ deep_question     深度提问 (DeepQuestionCapability)                     │
│  ├─ deep_research     深度研究 (DeepResearchCapability)                      │
│  ├─ math_animator     数学动画 (MathAnimatorCapability) ← 可选              │
│  ├─ visualize         可视化 (VisualizeCapability)                           │
│  └─ mastery_path      掌握路径 (MasteryPathCapability)                      │
└─────────────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                   Tool Registry (工具注册表 - Level 1)                      │
│                   deeptutor/runtime/registry/tool_registry.py               │
├─────────────────────────────────────────────────────────────────────────────┤
│  用户可切换工具: brainstorm, web_search, paper_search, reason                │
│  自动挂载工具 (context-gated):                                              │
│  ├─ rag, read_source, read_memory, write_memory, read_skill                │
│  ├─ load_tools, exec, code_execution, list_notebook, write_note             │
│  ├─ web_fetch, github, cron, ask_user, kb_files                           │
│  └─ partner_memory (partner 场景下)                                        │
└─────────────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                       Services Layer (服务层)                               │
├─────────────────────────────────────────────────────────────────────────────┤
│  LLM 服务       ┃  RAG 服务       ┃  Memory 服务      ┃  MCP 服务            │
│  (10,556 行)    ┃  (7,539 行)     ┃  (6,332 行)      ┃  (2,936 行)          │
├─────────────────────────────────────────────────────────────────────────────┤
│  Session 服务   ┃  Config 服务    ┃  Partners 服务    ┃  Embedding 服务      │
│  (6,705 行)     ┃  (5,133 行)     ┃  (3,159 行)      ┃  (2,312 行)          │
├─────────────────────────────────────────────────────────────────────────────┤
│  Skill 服务     ┃  Subagent 服务  ┃  Parsing 服务    ┃  Sandbox 服务       │
│  (2,487 行)     ┃  (3,639 行)     ┃  (3,098 行)      ┃  (1,195 行)          │
├─────────────────────────────────────────────────────────────────────────────┤
│  CLI Apps 服务   ┃  Cron 服务      ┃  Notebook 服务   ┃  Persona 服务       │
│  (1,798 行)     ┃  (634 行)       ┃  (465 行)        ┃  (390 行)            │
├─────────────────────────────────────────────────────────────────────────────┤
│  Voice 服务     ┃  ImageGen 服务  ┃  VideoGen 服务   ┃  Model Selection    │
│  (715 行)       ┃  (350 行)       ┃  (355 行)        ┃  (197 行)            │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 二、模块详细分析

### 2.1 `deeptutor/agents` (Agent 层)

**职责**：实现各种能力的 Agent 逻辑

| 子模块 | 路径 | 引用数 | 风险评估 |
|--------|------|:------:|----------|
| `chat` | `deeptutor/agents/chat/` | 高（核心） | **必须保留** |
| `math_animator` | `deeptutor/agents/math_animator/` | 低（仅 9 文件引用） | 建议保留但可简化 |
| `question` | `deeptutor/agents/question/` | 中等（11 文件引用） | **建议保留** |
| `research` | `deeptutor/agents/research/` | 中等（16 文件引用） | **建议保留** |
| `visualize` | `deeptutor/agents/visualize/` | 低（7 文件引用） | 建议保留但可简化 |
| `notebook` | `deeptutor/agents/notebook/` | 极低 | **可安全删除** |
| `vision_solver` | `deeptutor/agents/vision_solver/` | 极低（仅 2 文件引用） | 建议保留但可简化 |
| `_shared` | `deeptutor/agents/_shared/` | 高 | **必须保留** |

**分析说明**：
- `chat/` 是核心对话能力的实现，包含 AgenticChatPipeline、AgentLoop 等核心逻辑
- `math_animator/` 依赖外部 manim 库，是可选的数学动画生成器
- `notebook/` 中的 notebook agent 仅在测试中被引用，实际业务逻辑已迁移到 `services/notebook/`
- `vision_solver/` 实现了几何问题分析功能，引用 `GeoGebra`，功能相对独立

### 2.2 `deeptutor/api` (API 层)

**职责**：FastAPI 路由、WebSocket 处理

| 子模块 | 路径 | 说明 |
|--------|------|------|
| `routers/` | `deeptutor/api/routers/` | **30+ 路由文件** |
| `utils/` | `deeptutor/api/utils/` | 工具函数 |
| `main.py` | `deeptutor/api/main.py` | FastAPI 应用入口 |
| `run_server.py` | `deeptutor/api/run_server.py` | 服务器启动 |

**路由清单**：
```
auth          - 认证（登录/登出/注册）
chat          - 核心聊天 API
knowledge     - 知识库管理
mastery_path  - 掌握路径学习
co_writer     - 协作编辑
notebook      - 笔记本管理
book          - 书籍引擎
memory        - 记忆管理
settings      - 设置管理
mcp_settings  - MCP 服务器配置
space_mcp     - 个人 MCP 服务器
space_cli_apps - CLI 应用管理
skills        - 技能管理
subagents     - 子代理管理
personas      - 人设管理
tools         - 工具 API
system        - 系统状态
voice         - 语音 API
plugins_api   - 插件 API
partners      - 伙伴管理
attachments   - 附件上传
imports       - 导入
dashboard     - 仪表盘
sessions      - 会话管理
question      - 深度提问
question_notebook - 问题笔记本
quiz_judge    - 测验评判
capabilities_settings - 能力设置
agent_config  - Agent 配置
unified_ws    - 统一 WebSocket
outputs       - 输出文件
```

### 2.3 `deeptutor/services` (服务层 - 最大模块)

**3.1 LLM 服务 (10,556 行)**

| 子模块 | 路径 | 说明 |
|--------|------|------|
| `provider_core/` | `deeptutor/services/llm/provider_core/` | 核心 Provider 实现 |
| `providers/` | `deeptutor/services/llm/providers/` | Provider 基础实现 |
| `factory.py` | `deeptutor/services/llm/factory.py` | 统一工厂 |
| `client.py` | `deeptutor/services/llm/client.py` | LLM 客户端 |
| `cloud_provider.py` | `deeptutor/services/llm/cloud_provider.py` | 云 Provider |
| `local_provider.py` | `deeptutor/services/llm/local_provider.py` | 本地 Provider |
| `provider_factory.py` | `deeptutor/services/llm/provider_factory.py` | Provider 工厂 |
| `provider_registry.py` | `deeptutor/services/llm/provider_registry.py` | Provider 注册表 |

**说明**：Provider 系统非常庞大，支持 30+ 个 LLM Provider。可简化。

**3.2 RAG 服务 (7,539 行)**

| 子模块 | 路径 | 说明 |
|--------|------|------|
| `pipelines/llamaindex/` | `deeptutor/services/rag/pipelines/llamaindex/` | LlamaIndex 管道（默认） |
| `pipelines/graphrag/` | `deeptutor/services/rag/pipelines/graphrag/` | GraphRAG 管道（可选） |
| `pipelines/lightrag/` | `deeptutor/services/rag/pipelines/lightrag/` | LightRAG 管道（可选） |
| `pipelines/lightrag_server/` | `deeptutor/services/rag/pipelines/lightrag_server/` | LightRAG 服务端（可选） |
| `pipelines/ima/` | `deeptutor/services/rag/pipelines/ima/` | IMA 管道（可选） |
| `pipelines/pageindex/` | `deeptutor/services/rag/pipelines/pageindex/` | PageIndex 管道（可选） |
| `service.py` | `deeptutor/services/rag/service.py` | RAG 服务入口 |
| `factory.py` | `deeptutor/services/rag/factory.py` | 管道工厂 |

**说明**：默认仅使用 LlamaIndex 管道，其他管道为可选功能。

**3.3 Memory 服务 (6,332 行)**

| 子模块 | 路径 | 说明 |
|--------|------|------|
| `consolidator/` | `deeptutor/services/memory/consolidator/` | 记忆整合器 |
| `snapshot/` | `deeptutor/services/memory/snapshot/` | 快照功能 |
| `store.py` | `deeptutor/services/memory/store.py` | 记忆存储 |
| `ops.py` | `deeptutor/services/memory/ops.py` | 记忆操作 |

**3.4 Session 服务 (6,705 行)**

| 子模块 | 路径 | 说明 |
|--------|------|------|
| `protocol.py` | `deeptutor/services/session/protocol.py` | 会话协议 |
| `turn_runtime.py` | `deeptutor/services/session/turn_runtime.py` | 回合运行时 |

**3.5 MCP 服务 (2,936 行)**

| 子模块 | 路径 | 说明 |
|--------|------|------|
| `catalog/` | `deeptutor/services/mcp/catalog/` | MCP 目录 |
| `manager.py` | `deeptutor/services/mcp/manager.py` | MCP 管理器 |
| `pageindex_server.py` | `deeptutor/services/mcp/pageindex_server.py` | PageIndex 服务 |

**3.6 其他服务**

| 服务 | 行数 | 评估 |
|------|:----:|------|
| `config/` | 5,133 | **必须保留**（配置管理） |
| `subagent/` | 3,639 | 建议保留 |
| `partners/` | 3,159 | 建议保留但可简化 |
| `parsing/` | 3,098 | **必须保留**（文档解析） |
| `skill/` | 2,487 | 建议保留 |
| `embedding/` | 2,312 | **必须保留**（RAG 嵌入） |
| `cli_apps/` | 1,798 | 可简化 |
| `sandbox/` | 1,195 | 建议保留 |
| `voice/` | 715 | 可简化 |
| `cron/` | 634 | 建议保留 |
| `notebook/` | 465 | 建议保留 |
| `persona/` | 390 | 可简化 |
| `imagegen/` | 350 | 可安全删除 |
| `videogen/` | 355 | 可安全删除 |
| `model_selection/` | 197 | 可简化 |

---

## 三、可删除项详细清单

### 3.1 高优先级可删除（低风险、无业务价值）

#### 3.1.1 `deeptutor/agents/notebook/` - Notebook Agent

| 属性 | 内容 |
|------|------|
| **路径** | `deeptutor/agents/notebook/` |
| **当前职责** | Notebook 相关 Agent 实现（analysis_agent.py, summarize_agent.py） |
| **调用方/依赖方** | 仅被测试文件引用 |
| **删除理由** | 核心逻辑已迁移到 `deeptutor/services/notebook/`；notebook agent 的功能已由 chat agent 和 notebook 服务直接处理 |
| **影响范围** | 极小 - 仅测试文件和可能的动态导入 |
| **风险等级** | 🟢 低 |
| **删除后需清理** | 测试文件、prompt 文件 |

#### 3.1.2 `deeptutor/services/imagegen/` - 图片生成服务

| 属性 | 内容 |
|------|------|
| **路径** | `deeptutor/services/imagegen/` |
| **当前职责** | AI 图片生成功能（通过 ImagegenTool 暴露） |
| **调用方/依赖方** | 被 `deeptutor/tools/media_gen_tool.py` 引用 |
| **删除理由** | Lumen 核心业务为学习辅助，图片生成为非核心功能 |
| **影响范围** | `media_gen_tool.py`、`services/imagegen/` |
| **风险等级** | 🟢 低 |
| **删除后需清理** | `deeptutor/tools/media_gen_tool.py` 中的 `ImagegenTool`、API 路由、前端引用 |

#### 3.1.3 `deeptutor/services/videogen/` - 视频生成服务

| 属性 | 内容 |
|------|------|
| **路径** | `deeptutor/services/videogen/` |
| **当前职责** | AI 视频生成功能（通过 VideogenTool 暴露） |
| **调用方/依赖方** | 被 `deeptutor/tools/media_gen_tool.py` 引用 |
| **删除理由** | Lumen 核心业务为学习辅助，视频生成为非核心功能 |
| **影响范围** | `media_gen_tool.py`、`services/videogen/` |
| **风险等级** | 🟢 低 |
| **删除后需清理** | `deeptutor/tools/media_gen_tool.py` 中的 `VideogenTool` |

#### 3.1.4 `deeptutor/tools/media_gen_tool.py` - 媒体生成工具

| 属性 | 内容 |
|------|------|
| **路径** | `deeptutor/tools/media_gen_tool.py` |
| **当前职责** | ImagegenTool 和 VideogenTool 的实现 |
| **调用方/依赖方** | 被 `deeptutor/tools/builtin/__init__.py` 引用 |
| **删除理由** | 配合 imagegen/videogen 服务删除 |
| **影响范围** | 工具注册 |
| **风险等级** | 🟢 低 |
| **删除后需清理** | `tools/builtin/__init__.py` 中的导入、API 路由 |

#### 3.1.5 `deeptutor/agents/vision_solver/` - 视觉求解器

| 属性 | 内容 |
|------|------|
| **路径** | `deeptutor/agents/vision_solver/` |
| **当前职责** | GeoGebra 几何问题分析 |
| **调用方/依赖方** | 仅被 `deeptutor/tools/builtin/__init__.py` 中的 `GeoGebraAnalysisTool` 引用 |
| **删除理由** | 独立的几何分析功能，非核心学习路径必需 |
| **影响范围** | `GeoGebraAnalysisTool`、prompt 文件 |
| **风险等级** | 🟢 低 |
| **删除后需清理** | `tools/builtin/__init__.py` 中的 `GeoGebraAnalysisTool` |

### 3.2 中优先级可删除（需验证依赖）

#### 3.2.1 RAG 可选管道

| 管道 | 路径 | 说明 |
|------|------|------|
| **GraphRAG** | `deeptutor/services/rag/pipelines/graphrag/` | 可选重型管道（需 graphrag 依赖） |
| **LightRAG** | `deeptutor/services/rag/pipelines/lightrag/` | 可选管道（需 raganything 依赖） |
| **LightRAG Server** | `deeptutor/services/rag/pipelines/lightrag_server/` | 可选服务端管道 |
| **IMA** | `deeptutor/services/rag/pipelines/ima/` | 可选管道 |
| **PageIndex** | `deeptutor/services/rag/pipelines/pageindex/` | 可选管道 |

**保留理由**：默认 LlamaIndex 管道足够。删除这些可选管道可显著减少代码量和依赖。

**清理内容**：
- 删除对应管道目录
- 清理 `deeptutor/services/rag/factory.py` 中的注册
- 清理 `pyproject.toml` 中的可选依赖（graphrag, rag-lightrag）

#### 3.2.2 `deeptutor/api/routers/voice.py` - 语音路由

| 属性 | 内容 |
|------|------|
| **路径** | `deeptutor/api/routers/voice.py` |
| **当前职责** | 语音处理 API |
| **调用方/依赖方** | 被 `deeptutor/api/main.py` 注册 |
| **删除理由** | 语音功能非核心学习路径必需 |
| **影响范围** | `services/voice/`、前端语音功能 |
| **风险等级** | 🟡 中（需确认前端是否使用） |
| **删除后需清理** | API 路由注册、`services/voice/` |

#### 3.2.3 `deeptutor/services/cli_apps/` - CLI 应用服务

| 属性 | 内容 |
|------|------|
| **路径** | `deeptutor/services/cli_apps/` |
| **当前职责** | CLI 应用的目录、安装、运行管理 |
| **调用方/依赖方** | 被 `api/routers/space_cli_apps.py`、`runtime/providers/view.py` 引用 |
| **删除理由** | "CLI Apps" 功能非核心，为较新添加的功能 |
| **影响范围** | API 路由、前端 Space 功能 |
| **风险等级** | 🟡 中（需确认是否有用户在使用） |
| **删除后需清理** | `api/routers/space_cli_apps.py`、前端引用 |

#### 3.2.4 `deeptutor/services/persona/` - 人设服务

| 属性 | 内容 |
|------|------|
| **路径** | `deeptutor/services/persona/` |
| **当前职责** | AI 人设管理 |
| **调用方/依赖方** | 被 `api/routers/personas.py`、`multi_user/router.py` 引用 |
| **删除理由** | 人设功能为可选增强，非核心学习路径必需 |
| **影响范围** | API 路由、chat pipeline 中的 persona 注入 |
| **风险等级** | 🟡 中 |
| **删除后需清理** | API 路由、`agents/chat/` 中的 persona 处理 |

#### 3.2.5 `deeptutor/api/routers/dashboard.py` - 仪表盘路由

| 属性 | 内容 |
|------|------|
| **路径** | `deeptutor/api/routers/dashboard.py` |
| **当前职责** | 仪表盘数据 API |
| **调用方/依赖方** | 被 `api/main.py` 注册 |
| **删除理由** | 仪表盘为辅助功能，不是核心功能 |
| **影响范围** | 前端仪表盘页面 |
| **风险等级** | 🟡 中 |
| **删除后需清理** | 前端仪表盘页面 |

#### 3.2.6 `deeptutor/api/routers/quiz_judge.py` - 测验评判路由

| 属性 | 内容 |
|------|------|
| **路径** | `deeptutor/api/routers/quiz_judge.py` |
| **当前职责** | AI 测验评判 WebSocket |
| **调用方/依赖方** | 被 `api/main.py` 注册 |
| **删除理由** | 测验评判为可选功能 |
| **影响范围** | 前端测验功能 |
| **风险等级** | 🟡 中 |
| **删除后需清理** | WebSocket 路由、前端测验功能 |

### 3.3 低优先级可删除（需进一步确认）

#### 3.3.1 `deeptutor/capabilities/obsidian/` - Obsidian 能力

| 属性 | 内容 |
|------|------|
| **路径** | `deeptutor/capabilities/obsidian/` |
| **当前职责** | Obsidian 笔记库集成 |
| **调用方/依赖方** | 仅被 `tools/builtin/__init__.py` 和测试引用 |
| **删除理由** | 特定工具集成，非核心功能 |
| **影响范围** | Obsidian 工具、RAG 测试 |
| **风险等级** | 🟡 中（需确认是否有用户使用 Obsidian 集成） |
| **删除后需清理** | `capabilities/obsidian/` 整个目录 |

#### 3.3.2 `deeptutor/capabilities/explore_context/` - 探索上下文能力

| 属性 | 内容 |
|------|------|
| **路径** | `deeptutor/capabilities/explore_context/` |
| **当前职责** | 探索型上下文处理 |
| **调用方/依赖方** | 仅被测试引用 |
| **删除理由** | 未在 BUILTIN_CAPABILITY_CLASSES 中注册，功能可能已被 chat 能力吸收 |
| **影响范围** | 仅测试 |
| **风险等级** | 🟡 中 |
| **删除后需清理** | `capabilities/explore_context/` 整个目录 |

#### 3.3.3 `deeptutor/services/subagent/` - 子代理服务

| 属性 | 内容 |
|------|------|
| **路径** | `deeptutor/services/subagent/` |
| **当前职责** | 子代理实现（Claude Code, Codex, Gemini 等） |
| **调用方/依赖方** | 被 `capabilities/subagent/`、`api/routers/subagents.py` 引用 |
| **删除理由** | 子代理功能为高级特性，非核心学习路径必需 |
| **影响范围** | Subagent 能力、API、前端 |
| **风险等级** | 🟠 高（需确认是否有用户使用子代理功能） |
| **删除后需清理** | `capabilities/subagent/`、`api/routers/subagents.py`、`services/subagent/` |

#### 3.3.4 `deeptutor/services/codex_auth/` - Codex 认证

| 属性 | 内容 |
|------|------|
| **路径** | `deeptutor/services/codex_auth/` |
| **当前职责** | OpenAI Codex OAuth 认证 |
| **调用方/依赖方** | 被 `api/routers/auth.py` 引用 |
| **删除理由** | Codex/OAuth 为可选功能 |
| **影响范围** | OAuth 登录、Provider 配置 |
| **风险等级** | 🟠 高（CodeBuddy 依赖相关代码） |
| **删除后需清理** | `services/codex_auth/`、`services/codebuddy_auth.py` 等 |

### 3.4 需进一步确认的模块

| 模块 | 路径 | 说明 |
|------|------|------|
| `deeptutor/book/` | `deeptutor/book/` | 书籍引擎 - 34 文件, 7,685 行，被 API、CLI、测试广泛引用 |
| `deeptutor/co_writer/` | `deeptutor/co_writer/` | 协作编辑 - 3 文件, 623 行，被 API 和测试引用 |
| `deeptutor/learning/` | `deeptutor/learning/` | 学习掌握路径 - 22 文件, 4,692 行 |
| `deeptutor/partners/` | `deeptutor/partners/` | 伙伴频道 - 30 文件, 12,252 行 |

**分析**：
- **book/**: 虽然代码量大，但被 API、CLI 和测试广泛引用，且 `book/blocks/` 中的内容也被 `agents/` 模块引用。删除风险高。
- **co_writer/**: 功能独立，代码量小，可考虑保留或简化。
- **learning/**: 被 `capabilities/mastery/` 引用，是掌握路径功能的核心，需要保留。
- **partners/**: 代码量大（12,252 行），但包含 15+ 个 IM 频道适配器。如果不需要 IM 集成，可整体删除。

---

## 四、可删除的第三方依赖

### 4.1 可安全删除的依赖

| 依赖 | 说明 | 影响 |
|------|------|------|
| `manim` | 数学动画引擎 | 删除 `math_animator` 能力后可删除 |
| `graphrag` | GraphRAG 引擎 | 删除 graphrag 管道后可删除 |
| `raganything` / `liteparse` | LightRAG 依赖 | 删除 lightrag 管道后可删除 |
| `markitdown` | 可选解析引擎 | 若不使用此解析引擎 |
| `docling` | 可选解析引擎 | 若不使用此解析引擎 |
| `qrcode` | 微信二维码 | 若不需要微信伙伴 |
| `PyJWT` | MSTeams Token | 若不需要 MSTeams |
| `matrix-nio` | Matrix 频道 | 若不需要 Matrix |
| `numpy` | 数值计算 | 部分功能仍需要 |
| `perplexityai` | Perplexity SDK | 若不需要此 Provider |
| `wecom-aibot-sdk` | 企业微信 | 若不需要此频道 |
| `lark-oapi` | 飞书 | 若不需要此频道 |
| `dingtalk-stream` | 钉钉 | 若不需要此频道 |
| `slack-sdk` | Slack | 若不需要此频道 |
| `qq-botpy` | QQ 机器人 | 若不需要此频道 |
| `zulip` | Zulip | 若不需要此频道 |

### 4.2 可选保留的依赖

| 依赖 | 说明 |
|------|------|
| `anthropic` | Anthropic Provider SDK |
| `dashscope` | 阿里云 DashScope SDK |
| `oauth-cli-kit` | OAuth CLI 工具 |
| `mcp` | MCP 客户端 |
| `python-telegram-bot` | Telegram 频道 |

---

## 五、推荐的最小后端边界

### 5.1 核心功能（必须保留）

```
┌─────────────────────────────────────────────────────────────────┐
│                    最小后端边界                                    │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Entry Points:                                                  │
│  ├─ CLI (deeptutor_cli/main.py)                                │
│  └─ WebSocket API (deeptutor/api/main.py)                      │
│                                                                 │
│  Core Runtime:                                                  │
│  ├─ deeptutor/runtime/orchestrator.py  (调度)                  │
│  ├─ deeptutor/runtime/registry/        (注册表)                │
│  ├─ deeptutor/core/                     (核心协议)              │
│  └─ deeptutor/config/                   (配置)                  │
│                                                                 │
│  Capabilities:                                                  │
│  ├─ chat              (核心对话)                                │
│  ├─ deep_solve        (求解)                                    │
│  ├─ deep_question     (深度提问)                               │
│  ├─ deep_research     (深度研究)                                │
│  ├─ visualize         (可视化)                                 │
│  └─ mastery_path      (掌握路径)                               │
│                                                                 │
│  Services:                                                      │
│  ├─ llm/              (LLM 服务)                               │
│  ├─ rag/              (RAG 服务 - 仅 LlamaIndex 管道)          │
│  ├─ memory/           (记忆服务)                               │
│  ├─ session/          (会话服务)                               │
│  ├─ mcp/              (MCP 服务)                               │
│  ├─ embedding/        (嵌入服务)                               │
│  ├─ skill/            (技能服务)                               │
│  ├─ parsing/          (文档解析)                               │
│  ├─ knowledge/        (知识库管理)                             │
│  ├─ notebook/         (笔记本)                                 │
│  ├─ sandbox/          (沙箱)                                   │
│  ├─ cron/             (定时任务)                               │
│  └─ multi_user/       (多用户)                                 │
│                                                                 │
│  Tools:                                                         │
│  ├─ brainstorm, web_search, paper_search, reason                │
│  ├─ rag, read_source, read_memory, write_memory                │
│  ├─ load_tools, exec, code_execution                          │
│  ├─ list_notebook, write_note                                 │
│  ├─ web_fetch, github, ask_user, kb_files                     │
│  └─ mastery_tool, solve_tool                                   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 5.2 建议保留但可简化的功能

| 功能 | 说明 |
|------|------|
| `agents/math_animator/` | 保留代码但标记为可选，`manim` 依赖变为可选 |
| `agents/vision_solver/` | 保留但可简化 |
| `services/voice/` | 保留但可简化 |
| `services/persona/` | 保留但可简化 |

### 5.3 可安全删除的功能

| 功能 | 路径 | 代码量 |
|------|------|:------:|
| Notebook Agent | `agents/notebook/` | ~300 行 |
| 图片生成 | `services/imagegen/` + `tools/media_gen_tool.py` | ~700 行 |
| 视频生成 | `services/videogen/` | ~350 行 |
| Vision Solver | `agents/vision_solver/` | ~400 行 |
| GraphRAG 管道 | `services/rag/pipelines/graphrag/` | ~1,500 行 |
| LightRAG 管道 | `services/rag/pipelines/lightrag/` | ~1,200 行 |
| LightRAG Server | `services/rag/pipelines/lightrag_server/` | ~500 行 |
| IMA 管道 | `services/rag/pipelines/ima/` | ~400 行 |
| PageIndex 管道 | `services/rag/pipelines/pageindex/` | ~400 行 |

**预计可减少**：约 **5,750 行** 代码 + 大量可选依赖

---

## 六、裁剪清单（按风险从低到高排序）

### 阶段一：低风险裁剪（🟢）

| # | 操作 | 路径 | 影响行数 | 依赖影响 |
|---|------|------|:--------:|----------|
| 1 | 删除 Notebook Agent | `agents/notebook/` | ~300 | 无 |
| 2 | 删除 ImageGen 服务 | `services/imagegen/` | ~350 | 无 |
| 3 | 删除 VideoGen 服务 | `services/videogen/` | ~355 | 无 |
| 4 | 删除 MediaGen 工具 | `tools/media_gen_tool.py` | ~100 | 无 |
| 5 | 删除 VisionSolver | `agents/vision_solver/` | ~400 | 无 |
| 6 | 移除 GeoGebraAnalysisTool | `tools/builtin/__init__.py` 中的类 | ~80 | 无 |
| 7 | 可选：删除 Obsidian 能力 | `capabilities/obsidian/` | ~300 | 无 |
| 8 | 可选：删除 ExploreContext | `capabilities/explore_context/` | ~200 | 无 |

**小计**：约 **2,085 行**

### 阶段二：中风险裁剪（🟡）

| # | 操作 | 路径 | 影响行数 | 依赖影响 |
|---|------|------|:--------:|----------|
| 9 | 删除 GraphRAG 管道 | `services/rag/pipelines/graphrag/` | ~1,500 | graphrag |
| 10 | 删除 LightRAG 管道 | `services/rag/pipelines/lightrag/` | ~1,200 | raganything |
| 11 | 删除 LightRAG Server | `services/rag/pipelines/lightrag_server/` | ~500 | - |
| 12 | 删除 IMA 管道 | `services/rag/pipelines/ima/` | ~400 | - |
| 13 | 删除 PageIndex 管道 | `services/rag/pipelines/pageindex/` | ~400 | - |
| 14 | 删除语音 API | `api/routers/voice.py` + `services/voice/` | ~715 | - |
| 15 | 可选：删除 CLI Apps | `services/cli_apps/` + `api/routers/space_cli_apps.py` | ~1,800 | - |
| 16 | 可选：删除 Persona | `services/persona/` + `api/routers/personas.py` | ~400 | - |

**小计**：约 **6,915 行**

### 阶段三：高风险裁剪（🟠）

| # | 操作 | 路径 | 影响行数 | 依赖影响 |
|---|------|------|:--------:|----------|
| 17 | 删除 Subagent 功能 | `capabilities/subagent/` + `services/subagent/` + `api/routers/subagents.py` | ~3,800 | - |
| 18 | 删除 Codex/OAuth 功能 | `services/codex_auth/` + 相关文件 | ~500 | oauth-cli-kit |
| 19 | 可选：删除 Dashboard | `api/routers/dashboard.py` | ~200 | - |
| 20 | 可选：删除 Quiz Judge | `api/routers/quiz_judge.py` | ~150 | - |

**小计**：约 **4,650 行**

### 阶段四：可选精简（🔴 - 需评估业务价值）

| # | 操作 | 路径 | 影响行数 | 依赖影响 |
|---|------|------|:--------:|----------|
| 21 | 删除 Partners 系统 | `partners/` + `services/partners/` + `api/routers/partners.py` | ~15,000 | 15+ IM SDKs |
| 22 | 精简 Provider 列表 | `services/provider_registry.py` | ~300 | 多个 SDK |
| 23 | 删除 Book 引擎 | `book/` + `api/routers/book.py` + `deeptutor_cli/book.py` | ~7,700 | - |

**小计**：约 **23,000 行**

---

## 七、裁剪后需同步清理的内容

### 7.1 import 清理

每删除一个模块，需检查并清理以下位置的 import：
- `deeptutor/tools/builtin/__init__.py`（工具注册）
- `deeptutor/api/main.py`（API 路由注册）
- `deeptutor/runtime/bootstrap/builtin_capabilities.py`（能力注册）
- `deeptutor/runtime/registry/*.py`（注册表）
- `deeptutor/services/__init__.py`（服务导出）
- 各 `__init__.py` 文件中的 re-export

### 7.2 配置清理

- `pyproject.toml` 中的 `[project.optional-dependencies]`
- `requirements/` 目录下的依赖文件
- `deeptutor/config/` 中的默认配置
- 环境变量配置

### 7.3 API 路由清理

- `deeptutor/api/main.py` 中的路由注册
- 前端 `frontend/src/api/` 中的 API 调用

### 7.4 测试清理

- `tests/` 目录下的测试文件
- 注意：删除功能时同步删除对应测试，保持测试套件与代码一致

### 7.5 脚本清理

- `scripts/` 目录下的脚本
- Docker 相关配置文件

---

## 八、风险缓解策略

### 8.1 渐进式裁剪

建议按以下顺序逐步执行裁剪：

1. **第一阶段**：删除低风险、无调用的代码（阶段一）
2. **第二阶段**：删除可选的 RAG 管道和 API 路由（阶段二）
3. **第三阶段**：评估并删除 Subagent、Codex 等高风险功能（阶段三）
4. **第四阶段**：根据业务需求决定是否删除 Partners、Book 等大模块（阶段四）

### 8.2 验证步骤

每完成一个裁剪阶段后，执行：

```bash
# 1. 运行测试套件
pytest tests/ -v

# 2. 验证核心 CLI 命令
python -m deeptutor chat "test"
python -m deeptutor run chat "hello"
python -m deeptutor serve --port 8001

# 3. 验证 API 端点
curl http://localhost:8001/
curl -X POST http://localhost:8001/api/v1/chat

# 4. 验证 RAG 功能
python -c "from deeptutor.services.rag import RAGService; print('OK')"

# 5. 验证 LLM 调用
python -c "from deeptutor.services.llm import get_llm_client; print('OK')"
```

### 8.3 回滚策略

- 使用 Git 分支进行裁剪工作
- 每个阶段创建独立分支
- 保持可回滚性
- 完成后进行充分测试再合并

---

## 九、预计收益

### 9.1 代码量减少

| 阶段 | 减少行数 | 剩余行数 | 减少比例 |
|------|:--------:|:--------:|:--------:|
| 初始 | - | ~161,542 | - |
| 阶段一后 | ~2,085 | ~159,457 | 1.3% |
| 阶段二后 | ~6,915 | ~152,542 | 5.6% |
| 阶段三后 | ~4,650 | ~147,892 | 8.4% |
| **合计** | **~13,650** | **~147,892** | **8.4%** |

### 9.2 依赖减少

| 阶段 | 可删除依赖数 |
|------|:----------:|
| 阶段一 | 0 核心依赖 |
| 阶段二 | 2-3 个可选依赖（graphrag, rag-lightrag） |
| 阶段三 | 1-2 个可选依赖（oauth-cli-kit 等） |
| 阶段四 | 15+ IM SDKs, manim 等 |

### 9.3 模块精简

| 类别 | 初始模块数 | 阶段三后 | 减少 |
|------|:--------:|:--------:|:----:|
| Agent 子模块 | 8 | 5 | 3 |
| API 路由 | 30+ | ~25 | 5+ |
| Capability | 7 | 5 | 2 |
| RAG 管道 | 6 | 1 | 5 |
| Service 子模块 | 20+ | ~15 | 5+ |

---

## 十、结论与建议

### 10.1 总体评估

DeepTutor/Lumen 后端是一个功能丰富但相对复杂的系统。经过分析：

- **核心功能**（chat, solve, research, question, visualize, mastery_path）代码结构清晰，职责明确
- **可选功能**（RAG 管道、Partners、Subagent、Codex 等）代码量大且依赖重
- **冗余代码**（notebook agent、imagegen/videogen、vision_solver）可安全删除

### 10.2 优先级建议

1. **立即可做**：删除阶段一中的低风险项（约 2,085 行），验证无回归
2. **短期可做**：删除阶段二中的可选 RAG 管道（约 6,915 行），大幅简化 RAG 层
3. **中期评估**：根据 Lumen 实际业务需求评估阶段三中的功能
4. **长期规划**：重新评估是否需要 Partners 系统和 Book 引擎

### 10.3 核心原则

- **基于真实调用关系裁剪**，而非根据目录名称猜测
- **稳定性优先于极限精简**
- 每一步裁剪后都进行充分测试
- 保留回滚能力

---

*报告完成。此文档为阶段一（只读分析）产出，阶段二（实施裁剪）需在本报告确认后执行。*
