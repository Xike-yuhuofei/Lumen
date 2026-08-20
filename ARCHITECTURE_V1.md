# Architecture Baseline v1 — Lumen Plugin Kernel 正式架构

> **冻结日期：** 2026-08-18
> **阶段：** Architecture Migration 完成 → Product Capability Development
> **用途：** 后续回归测试基准；任何架构变更必须通过此文档验证

---

## 1. 最终目录结构

```
Lumen/
├── lumen/                          ← 新架构所有权
│   ├── kernel/                     ← Plugin Kernel（唯一架构调度器）
│   │   ├── bootstrap.py            ← Bootstrap / PluginContext 装配
│   │   ├── profile.py              ← Profile 数据结构
│   │   ├── registry.py             ← 插件注册表
│   │   ├── resolver.py             ← 服务解析器
│   │   ├── plugin.py               ← Plugin 基类 / PluginManifest
│   │   ├── events.py               ← 内核事件
│   │   ├── effects.py              ← 内核副作用
│   │   └── context.py              ← PluginContext
│   │
│   ├── runtime/                    ← Runtime Contracts + Providers
│   │   ├── contract.py             ← 全部 Runtime Contract 定义
│   │   ├── agent_loop/             ← runtime.agent_loop
│   │   │   ├── contract.py
│   │   │   └── providers/          ← legacy / langchain provider 实现
│   │   ├── llm/                    ← runtime.llm
│   │   ├── tools/                  ← runtime.tools
│   │   ├── session/                ← runtime.session
│   │   ├── prompt/                 ← runtime.prompt
│   │   └── stream/                 ← StreamBus / StreamEvent
│   │
│   ├── shared/                     ← Shared Service Contracts + Providers
│   │   ├── contract.py             ← 全部 Shared Contract 定义
│   │   ├── knowledge/
│   │   │   ├── sources/
│   │   │   ├── retrieval/
│   │   │   └── parsing/
│   │   ├── memory/
│   │   ├── notebook/
│   │   ├── rendering/
│   │   └── _util/                  ← 无依赖的纯工具函数
│   │
│   ├── modes/
│   │   └── learn/                  ← mode.learn（唯一产品 Mode）
│   │       ├── contract.py         ← LearnModeService ABC
│   │       ├── plugin.py           ← ModeLearnPlugin 实现
│   │       ├── domain/             ← 教学领域模型
│   │       ├── application/        ← 应用服务层
│   │       ├── assessment/         ← 评估 / 评分
│   │       ├── policy/             ← 教学策略
│   │       ├── adapters/           ← 存储 / learner state 适配器
│   │       └── prompts/            ← mode.learn 专属提示词
│   │
│   ├── bootstrap.py                ← LumenBootstrap + active-assembly bridge
│   ├── profile.py                  ← PRODUCTION_PROFILE + PRODUCTION_PLUGINS
│   ├── compat.py                   ← mastery_path/mastery → mode.learn 映射
│   ├── bakeoff_profiles.py         ← A/B 测试 profiles（legacy vs langchain）
│   └── agent_loop_langchain/       ← LangChain Agent Loop 评估实现
│
├── deeptutor/                      ← 现有实现（Provider 层）
│   ├── agents/chat/                ← AgenticChatPipeline（Production Agent Loop Provider）
│   ├── core/                       ← 基础设施（stream, stream_bus, tool_protocol, context）
│   ├── runtime/                    ← 工具注册表、启动器、请求合约
│   ├── services/                   ← 会话、LLM、RAG、Memory、Notebook 等真实服务
│   ├── capabilities/               ← LoopCapability 工具注入机制（非旧 Capability 架构）
│   ├── learning/                   ← 学习引擎实现
│   ├── teaching_core/              ← 教学核心
│   ├── tools/                      ← 内置工具实现
│   ├── knowledge/                  ← KB 管理
│   └── app/facade.py              ← DeepTutorApp（SDK 门面）
│
├── lumen_cli/                      ← CLI 入口
├── lumen_web/                      ← Web 包标记
└── frontend/                       ← React/Vite 前端
```

---

## 2. 依赖方向规则（冻结）

```
┌─────────────────────────────────────────────────────┐
│                    允许的依赖方向                       │
│                                                      │
│  Kernel  → 无领域依赖（纯调度）                        │
│  Runtime → Kernel, Runtime 自身, Shared (仅限 _util)  │
│  Shared  → Kernel, Shared 自身, Runtime (仅限 _util)  │
│  Modes   → Kernel, Runtime Contracts, Shared Contracts│
│  App     → Kernel, Runtime, Shared, Modes             │
│                                                      │
│  禁止：                                              │
│  ✗ Runtime → modes.*                                 │
│  ✗ Shared  → modes.*                                │
│  ✗ Mode    → 具体 Provider 实现（deeptutor.*）        │
│  ✗ Mode    → 其他 Plugin 的 Provider 模块            │
│  ✗ Kernel  → domain implementation                  │
│  ✗ 跨层 Service Locator（get_xxx() 在业务层使用）     │
└─────────────────────────────────────────────────────┘
```

### 关键约束

1. **Contract 归 Capability 所有**：Runtime Contract 在 `lumen/runtime/`，Shared Contract 在 `lumen/shared/`
2. **Provider 默认属于 Capability 内部实现**：`lumen/runtime/*/providers/` 存放 Provider
3. **Mode 只依赖 Contract**：`mode.learn` 通过 `PluginContext.require()` 获取 Contract
4. **Learn 不知道具体实现**：mode.learn 不直接 import deeptutor 代码
5. **Runtime/Shared 不知道 Learn**：禁止 `from lumen.modes` 在 runtime/ 和 shared/ 中
6. **不建立中央巨型 contracts/**：Contract 就近放在各自目录
7. **不创建 mode.chat**：chat 是 Runtime concern，不是产品 Mode

---

## 3. Runtime Contracts 清单

### runtime.agent_loop
```python
class AgentLoopService(ABC):
    async def run(self, pipeline, context, stream) -> None: ...
```
- **Provider (Production):** Legacy Provider → `AgenticChatPipeline`
- **Provider (Evaluation):** LangChain Provider → `create_react_agent` + LangGraph

### runtime.llm
```python
class LLMService(ABC):
    def build_openai_client(self, config) -> Any: ...
    async def complete(self, messages, model=None, **kwargs) -> str: ...
```

### runtime.tools
```python
class ToolService(ABC):
    def register(tool) -> None: ...
    def get(name) -> Any | None: ...
    def list_tools() -> list[str]: ...
    async def execute(name, **kwargs) -> Any: ...
    def build_openai_schemas(names=None) -> list[dict]: ...
```

### runtime.session
```python
class SessionService(ABC):
    async def ensure_session(session_id=None) -> dict: ...
    async def start_turn(payload) -> tuple[dict, dict]: ...
    async def subscribe_turn(turn_id, after_seq=0) -> AsyncIterator: ...
    async def cancel_turn(turn_id) -> bool: ...
    async def add_message(session_id, role, content, ...) -> int | str: ...
```

### runtime.prompt
```python
class PromptService(ABC):
    def load_prompt(module, agent, language="en", subdirectory=None) -> dict: ...
```

### runtime.agent
```python
class AgentService(ABC):
    async def create_pipeline(language="en", **config) -> Any: ...
```

### runtime.stream
```python
# StreamBus / StreamEvent — 事件协议 + 异步 fan-out
```

---

## 4. Shared Contracts 清单

### knowledge.sources
```python
class KnowledgeSourceService(ABC):
    def list_knowledge_bases() -> list[str]: ...
    def get_info(name=None) -> dict: ...
    def get_kb_path(name=None) -> str: ...
```

### knowledge.retrieval
```python
class KnowledgeRetrievalService(ABC):
    async def search(query, kb_name, **kwargs) -> RetrievalResult: ...
    async def initialize(kb_name, file_paths, **kwargs) -> bool: ...
    async def add_documents(kb_name, file_paths, **kwargs) -> bool: ...
```

### knowledge.parsing
```python
class KnowledgeParsingService(ABC):
    def parse(source_path, *, engine=None) -> ParsedDocument: ...
```

### memory
```python
class MemoryService(ABC):
    async def read(layer, key) -> dict | None: ...
    async def read_concat() -> str: ...
    async def overwrite(layer, key, content) -> None: ...
    async def delete_entry(layer, key, entry_id) -> bool: ...
    def overview() -> list[dict]: ...
```

### notebook
```python
class NotebookService(ABC):
    def create(name, description="", color="#3B82F6", icon="book") -> dict: ...
    def list() -> list[dict]: ...
    def get(notebook_id) -> dict | None: ...
    def add_record(...) -> dict | None: ...
    def get_records(notebook_id, record_ids=None) -> list[dict]: ...
    def remove_record(notebook_id, record_id) -> bool: ...
```

### rendering
```python
class RenderingService(ABC):
    def strip_markdown(text) -> str: ...
    def clean_thinking_tags(text) -> str: ...
```

---

## 5. mode.learn Contract

```python
class LearnModeService(ABC):
    async def start(self, path_id: str) -> dict: ...
    async def resume(self, path_id: str) -> dict | None: ...
    async def handle_turn(self, context, stream) -> None: ...
    async def get_state(self, path_id: str) -> dict: ...
```

**Implementation:** `_LearnModeServiceAdapter` (mode.learn/plugin.py)
- 通过 PluginContext 注入所有依赖
- learner state 存储在 LearningStore
- turn 通过 injected `runtime.agent_loop` 执行

---

## 6. Production Profile

```python
SHARED_PLUGINS = [
    SessionPlugin(),  # runtime.session
    PromptPlugin(),  # runtime.prompt
    ToolPlugin(),  # runtime.tools
    LLMPlugin(),  # runtime.llm
    AgentPlugin(),  # runtime.agent
    KnowledgeSourcesPlugin(),  # knowledge.sources
    KnowledgeRetrievalPlugin(),  # knowledge.retrieval
    KnowledgeParsingPlugin(),  # knowledge.parsing
    MemoryPlugin(),  # memory
    NotebookPlugin(),  # notebook
    RenderingPlugin(),  # rendering
    ModeLearnPlugin(),  # mode.learn
]

# Production Active Provider = P1 (LangGraph Thin); Legacy kept for rollback.
PRODUCTION_PLUGINS = [*SHARED_PLUGINS, AgentLoopPlugin(), LangGraphThinAgentLoopPlugin()]
PRODUCTION_PROFILE.bindings = {"runtime.agent_loop": "agent_loop.langgraph_thin"}
legacy rollback:  LUMEN_AGENT_LOOP_PROVIDER=legacy → 纯 P0 (LEGACY_AGENT_LOOP_PROFILE)
```

**Provider (Production):** P1 LangGraph Thin (`agent_loop.langgraph_thin` / `LangGraphThinProvider`) — Active Provider，通过 Profile binding elect。
**Provider (Rollback):** Legacy (`AgenticChatPipeline`) — shadowed provider，`LUMEN_AGENT_LOOP_PROVIDER=legacy` 一键回退。
**Provider (Evaluation):** LangChain Agent Loop (`create_react_agent` + LangGraph) — `bakeoff_profiles` 专用。

> 决策更新 (2026-08-20)：Production Provider 由 Legacy (P0) 切换为 P1 `langgraph_thin`
> （覆盖此前「Production = LEGACY 不可变更」的冻结结论）。

### Teaching Architecture — KEEP A（冻结 2026-08-20 / CLOSED）

**决策：Continue Candidate A — teaching-hook + generic Agent Loop 是 `mode.learn` 的正式生产教学架构。**

- **Candidate A = Production Default**：Learn turn 默认走 teaching-hook 路径（`route_learn_turn` 返回 `"hook"`），生产行为不变。
- **Candidate B = Experimental / Research Asset**：Teaching Session Graph（`lumen/modes/learn/graph/`）为 opt-in 实验资产（`LUMEN_LEARN_GRAPH_CANDIDATE=1`，默认 off），不作为待 Promotion 的活动候选。仅作实验、研究与未来需求参考。
- **Teaching Architecture Experiment：CLOSED**（Phase-3 → Phase-4b → Phase-4c 已收口红温，详见 `tests/modes/learn/eval/bakeoff/out_phase*/` 各报告与 `phase4c_report.md`）。

**证据要点（可复现）：**
- Phase-4c 策略敏感 learner（`StrategySensitiveLearner`）证明自身具备诊断力（scaffolded 1.0 vs assessment-only 0.225，delta +0.775），说明 A/B 若存在真实教学差异会被观测到。
- 在该可区分 learner 下，A/B 在全部 material 细胞仍逐字 parity：action / strategy / mechanism 序列全等，outcome（independent success / mastery / retention / transfer）相等。
- Candidate B 的 multi-session continuity 仅 preserve 教学状态、不产出学习增量（increment_from_continuity = 0）。
- 结论：A 与 B 由同一共享 TeachingEngine 驱动，B 的图/运行时表示不改变教学决策，无法产生教学效果增量；其已验证价值属**审计 / 重放 / 跨会话连续性等架构-运维能力**，不足以抵消额外复杂度。

**重新开启 A/B Teaching Architecture 决策的触发条件（需出现其一）：**
1. 出现新的真实产品需求或教学机制，仅 B（明确教学 Session Graph / 显式教学流程）能承载且 A 无法等效替代；
2. 出现足以推翻上述 parity 结论的新事实（如真实 learner 上 A/B 存在可测量且稳定的教学效果差异）；
3. 出现新的、在真实场景下必须由显式图化教学流程才能满足的运维/审计强约束。

**冻结语义：** 不 Promotion B、不删除 B、不因本次决策进行无必要的大规模重构或架构清理；不得在没有上述新证据的情况下重新开启 Teaching Architecture 实验。

---

## 7. 入口点运行时链路

### WS / CLI / SDK Learn 请求
```
请求 (capability=mode.learn | mastery_path | mastery)
  → TurnRuntimeManager.start_turn()
  → _resolve_learn_service()
  → LumenBootstrap.ensure_active_bootstrap()
  → resolve_mode() → "mode.learn"
  → PluginContext.optional("mode.learn")
  → LearnModeService.handle_turn()
  → injected runtime.agent_loop.run()
  → StreamBus 事件流
  → 会话持久化
```

### WS / CLI / Cron 通用 turn
```
请求 (capability=chat | 其他)
  → TurnRuntimeManager.start_turn()
  → _resolve_agent_loop_service()
  → LumenBootstrap.ensure_active_bootstrap()
  → PluginContext.optional("runtime.agent_loop")
  → agent_loop.run(context, stream, language)
  → StreamBus 事件流
  → 会话持久化
```

### Cron
```
Cron job 触发
  → _execute_chat_job()
  → resolve_agent_loop_service()
  → runtime.agent_loop.run()
  → 结果追加到会话
```

---

## 8. 已删除的 Legacy 组件

| 组件 | 文件 | 删除状态 |
|------|------|----------|
| MasteryPathCapability | (不存在) | ✅ 从未作为类存在，仅为 transport 兼容名 |
| ChatCapability | `deeptutor/agents/chat/capability.py` | ✅ 已删除 |
| ChatOrchestrator | `deeptutor/runtime/orchestrator.py` | ✅ 已删除 |
| CapabilityRegistry | `deeptutor/runtime/registry/capability_registry.py` | ✅ 已删除 |
| BUILTIN_CAPABILITY_CLASSES | `deeptutor/runtime/bootstrap/builtin_capabilities.py` | ✅ 已删除 |
| BaseCapability | `deeptutor/core/capability_protocol.py` | ✅ 已删除 |
| deeptutor/runtime/bootstrap/__init__.py | 空壳 bootstrap | ✅ 已删除 |

---

## 9. 兼容层清单

| 项目 | 位置 | 存在理由 |
|------|------|----------|
| `mastery_path`/`mastery` → `mode.learn` | `lumen/compat.py` | 外部 CLI/API 兼容名 |
| `deeptutor.services.file_io` → `lumen.shared._util.file_io` | `deeptutor/services/file_io.py` | 旧 import 路径 |
| `deeptutor.utils.json_parser` → `lumen.shared._util.json_parser` | `deeptutor/utils/json_parser.py` | 旧 import 路径 |
| `deeptutor.capabilities/` (LoopCapability) | `deeptutor/capabilities/` | 聊天循环工具注入（非旧 Capability 架构） |
| `deeptutor/app/facade.py` | `deeptutor/app/facade.py` | SDK 门面 |
| LangChain bakeoff profiles | `lumen/bakeoff_profiles.py` | A/B 测试 |

---

## 10. Architecture Gates 清单

文件：`tests/kernel/test_architecture_gates_phase7.py`

| Gate | 验证内容 |
|------|----------|
| `test_kernel_does_not_import_domain_implementations` | Kernel 不 import agent/llm/rag/learning/teaching/learn/news/review |
| `test_mode_learn_does_not_import_concrete_providers` | mode.learn 不 import langchain/langgraph/llamaindex/deeptutor |
| `test_mode_learn_does_not_import_other_plugins_providers` | mode.learn 不 import lumen.runtime*/lumen.shared* (仅限非 _util) |
| `test_plugin_providers_do_not_cross_import_sibling_providers` (×3) | Runtime/Shared/Modes 不跨 import 兄弟 Plugin 的 Provider |
| `test_legacy_capability_shell_modules_removed` | 旧 Capability shell 文件不存在 |
| `test_runtime_does_not_import_modes` | Runtime 不 import lumen.modes |
| `test_shared_does_not_import_modes_or_runtime_providers` | Shared 不 import lumen.modes / lumen.runtime |
| `test_no_chat_mode_exists` | lumen/modes/ 下只有 learn/ |
| `test_turn_entries_use_runtime_contract_not_direct_pipeline` (×2) | turn_runtime.py / cron executor 不直接 import agentic_pipeline |
| `test_no_production_import_of_legacy_capability_shell` (×5) | deeptutor/ 和 lumen/ 不 import 5 个 legacy shell 模块 |

---

## 11. 测试基线

| 测试类别 | 数量 | 状态 |
|----------|------|------|
| pytest 后端（不含 faiss） | 2016 passed, 7 skipped | ✅ |
| pytest kernel tests | 175 passed | ✅ |
| pytest CLI tests | 9 passed | ✅ |
| pytest app facade | 10 passed | ✅ |
| Architecture Gates | 17 passed | ✅ |
| 前端 Playwright E2E | 34/34 passed | ✅ |
| 前端 build | ✅ 成功 | ✅ |
| ruff lint | All checks passed | ✅ |

**已知环境问题：** faiss 测试 `test_llamaindex_faiss_vector_store.py` 在 `test_new_index_persists_faiss_and_ranks_by_cosine` 触发 segfault（`Fatal Python error: Aborted`）。判定为 faiss 1.15.0 + numpy + torch 版本兼容性问题，与架构变更无关。

---

## 12. 冻结规则

1. **不得重新讨论已冻结的 Architecture Invariants**（见 goal.md）
2. **不得在无 bake-off 证据的情况下切换 Production Agent Loop Provider**
3. **不得为目录美观创建无意义 abstraction**
4. **不得大规模 blind deeptutor → lumen rename**
5. **新增 Product Mode 必须在 modes/ 下创建目录并通过 Architecture Gate 验证**
6. **删除兼容层必须在所有内部消费者已切换、测试已更新后进行**
7. **任何跨 Runtime/Shared→Modes 的 import 新增必须通过 Architecture Gate 审查**
