# Goal: Complete Lumen Architecture Convergence

你现在进入 **Goal Mode**。

你的任务不是执行某一个预先指定的 Batch，而是持续分析当前仓库状态、规划下一步、修改、验证、重新评估，直到下面定义的 **Final Goal** 全部满足。

不要重新设计已经冻结的顶层架构。

---

## Final Goal

将 Lumen 从 DeepTutor 遗留架构完整收敛到以下正式架构：

```text
Lumen
├── Kernel
├── Runtime
├── Shared
├── Modes
└── App
```

最终正式产品 Mode：

```text
modes/
├── learn/
├── news/      # 未来产品能力，可以尚未实现
└── review/    # 未来产品能力，可以尚未实现
```

`chat` **不是产品 Mode**。

最终运行关系应是：

```text
App / WS / CLI / Cron
        │
        ├── Learn request
        │      ↓
        │   mode.learn
        │      ↓
        │   runtime.agent_loop
        │
        └── Generic agent turn
               ↓
            Runtime
               ↓
        runtime.agent_loop
```

Generic agent turn 可以最终形成：

```text
runtime.turn
```

或：

```text
runtime.chat
```

根据当前代码选择最简单、职责最清晰的方案。

**禁止创建 `mode.chat`。**

---

# Architecture Invariants

以下决策已经冻结，不得重新讨论或推翻。

1. Contract 归 Capability 所有。
2. Provider 默认属于 Capability 内部实现。
3. Mode 只依赖 Contract，不依赖具体 Provider。
4. Learn 不知道 Agent Loop / RAG / LLM 的具体实现。
5. Runtime / Shared 基础设施不知道 Learn。
6. 不建立中央巨型 `contracts/`。
7. Provider 不是必需顶层目录。
8. 不创建 `mode.chat`。
9. 不为了目录美观创建无意义 abstraction。
10. 不做全仓 blind `deeptutor → lumen` rename。
11. Global singleton 可以作为 implementation 存在。
12. 要消灭的是跨层 Service Locator dependency，而不是 singleton 本身。

---

# Production Agent Loop

当前 Production Provider：

```text
Legacy Agent Loop Provider
→ AgenticChatPipeline
```

LangChain 当前结论：

```text
CONTINUE EVALUATION
```

因此：

**不得因为 LangChain 更新、更现代或代码更漂亮就切换 Production Provider。**

只有存在新的、明确的 bake-off 证据证明其达到替换标准，才允许提出 Provider 切换建议。

本 Goal 默认：

```text
Production = Legacy Provider
```

---

# Learn Final State

正式 Learn 必须是：

```text
request
→ mode.learn
→ runtime.agent_loop contract
→ Production Agent Loop Provider
```

最终不得存在：

```text
MasteryPathCapability
```

作为正式 Product Capability。

旧名称：

```text
mastery_path
mastery
```

如果仍有兼容需要，只允许存在于：

```text
transport / compatibility boundary
        ↓
mode.learn
```

不得重新实例化旧 Capability。

当确认所有有效客户端均使用 `mode.learn` 后，可以删除 compatibility alias。

---

# Legacy Capability Architecture Final State

最终删除旧的：

```text
MasteryPathCapability
ChatCapability
ChatOrchestrator
CapabilityRegistry
BUILTIN_CAPABILITY_CLASSES
```

以及只为旧多 Capability 产品入口架构存在的：

* manifest
* registration
* routing
* shell
* facade
* compatibility glue
* dead tests
* dead comments
* dead fields

但是：

**只能在其有效职责已经迁入正确所有者之后删除。**

禁止先删代码，再补架构。

---

# Chat / Generic Agent Turn Migration

当前 generic chat 中仍然有效的职责必须保留，例如：

* Agent Loop invocation
* context building
* StreamBus lifecycle
* cancellation
* settlement
* completion events
* session lifecycle
* tool execution
* cron execution
* CLI execution

这些职责应根据语义进入：

```text
Runtime
```

或：

```text
App
```

而不是形成新的 Product Mode。

最终目标：

```text
WS generic turn
CLI generic turn
Cron generic turn
        ↓
同一个 Runtime Contract
        ↓
runtime.agent_loop
```

避免三个入口各自维护不同 orchestration。

---

# Existing Production Capabilities

以下代码即使仍位于 `deeptutor/`，也不能因为名称旧而删除：

* AgenticChatPipeline
* Legacy Agent Loop
* ToolRegistry
* Session / TurnRuntime
* RAG
* Memory
* Notebook
* LLM
* Streaming
* Tool Calling
* reason
* brainstorm
* Learn / Teaching 所需真实实现

判断标准始终是：

> **目标 Lumen 是否仍需要这个行为？**

而不是：

> 文件路径是不是 `deeptutor/`。

---

# Physical Ownership Goal

逐步确保真实实现拥有正确 Source of Truth：

```text
Kernel   → lumen/kernel
Runtime  → lumen/runtime
Shared   → lumen/shared
Modes    → lumen/modes
App      → lumen/app 或正式 App assembly 边界
```

Compatibility facade 可以暂时存在。

只有满足：

1. 所有内部消费者已切换；
2. 测试已切换；
3. 无动态 import；
4. 无外部兼容要求；

之后才删除 facade。

不要为了“完成 namespace 迁移”而移动仍稳定工作的代码。

---

# Service Locator Convergence

逐步把：

```text
Consumer
↓
get_xxx()
```

收敛为：

```text
Consumer
↓
Contract
↑
Provider
```

但不要机械消灭：

```text
get_tool_registry()
get_memory_store()
get_notebook_manager()
get_session_store()
get_llm_client()
...
```

如果它们仍是 Provider 内部合法的进程级实现，可以保留。

目标是：

**业务层和跨层消费者不直接依赖 Service Locator。**

---

# Test Philosophy

不要以测试数量作为目标。

每个测试只问：

> 它保护的行为，在最终 Lumen 中是否仍然存在？

如果存在：

```text
KEEP / UPDATE
```

如果行为已经消失：

```text
DELETE
```

Migration history 本身不值得永久保留测试。

必须长期保留：

* Contract tests
* Architecture Gates
* Runtime behavior tests
* Learn behavior tests
* Tool Calling
* Streaming
* Session
* RAG
* Memory
* Notebook
* LLM
* Provider behavior
* WS / CLI / Cron integration
* Production Agent Loop regression

---

# Execution Strategy

持续循环：

```text
Inspect
↓
Identify highest-value architectural delta
↓
Design smallest safe batch
↓
Implement
↓
Targeted tests
↓
Architecture gates
↓
Full regression
↓
Inspect again
```

每一批必须：

* 小
* 可验证
* 可回滚
* 单一目标
* 不混入无关重构

不要一次进行：

* 大规模 rename
* 大规模目录移动
* 大规模删除
* 大规模 abstraction 重写

---

# Decision Priority

当存在多个可执行任务时，按以下优先级：

```text
1. 删除已经完全死亡的代码
2. 消除阻塞下一阶段的依赖
3. 将错误 ownership 的活职责迁入正确层
4. 删除旧 architecture shell
5. 消除跨层 service locator
6. 清理 compatibility facade
7. namespace 最终收敛
8. architecture hardening
```

不要为了 namespace cleanliness 提前执行第 7 步。

---

# Architecture Gates

持续维护自动化 Architecture Gates，至少验证：

### Learn

```text
mode.learn
→ runtime.agent_loop
```

并禁止：

```text
mode.learn → ChatOrchestrator
mode.learn → ChatCapability
mode.learn → MasteryPathCapability
```

### Generic Agent Turn

最终禁止：

```text
App / WS / CLI / Cron
→ CapabilityRegistry
```

而要求：

```text
App / WS / CLI / Cron
→ Runtime Contract
```

### Dependency Direction

禁止：

```text
Runtime → modes.learn
Shared → modes.learn
Mode → concrete Provider
```

### Legacy

最终禁止 production import：

```text
MasteryPathCapability
ChatCapability
ChatOrchestrator
CapabilityRegistry
```

---

# Final Acceptance Criteria

只有以下全部满足，Goal 才算完成。

## Architecture

* [ ] Kernel / Runtime / Shared / Modes / App 边界清晰。
* [ ] Learn 正式入口只有 `mode.learn`。
* [ ] 不存在 `mode.chat`。
* [ ] Generic agent turn 属于 Runtime。
* [ ] WS / CLI / Cron generic turn 使用统一 Runtime 入口。

## Legacy Capability System

* [ ] `MasteryPathCapability` 已删除。
* [ ] `ChatCapability` 已删除。
* [ ] `ChatOrchestrator` 已删除。
* [ ] `CapabilityRegistry` 已删除。
* [ ] 旧 builtin Capability 注册体系已删除。
* [ ] 没有 production consumer 依赖旧 Capability architecture。

## Runtime

* [ ] Production Agent Loop 仍通过 `runtime.agent_loop` Contract 调用。
* [ ] Legacy Provider 是否继续 Production 由 bake-off 证据决定，而不是架构迁移决定。
* [ ] Streaming / cancellation / settlement / completion lifecycle 完整保留。

## Dependency Injection

* [ ] Mode 依赖 Contract。
* [ ] Runtime / Shared 不知道 Learn。
* [ ] 跨层 Service Locator usage 已清理。
* [ ] Provider 内部合法 singleton 可以保留。

## Compatibility

* [ ] 所有 facade 都有明确存在理由。
* [ ] 无消费者的 facade 已删除。
* [ ] `mastery_path/mastery` alias 若已无兼容需要则删除。
* [ ] 不存在重复业务实现。

## Quality

* [ ] Architecture Gates 全绿。
* [ ] targeted tests 全绿。
* [ ] full backend regression 全绿。
* [ ] frontend build / tests 全绿。
* [ ] CLI / WS / Cron smoke 全绿。
* [ ] ruff / typecheck 无本 Goal 新增问题。

---

# Autonomous Goal Mode Rules

你可以自主：

* 审计代码
* 搜索依赖
* 设计 Batch
* 修改代码
* 增删测试
* 新增 Architecture Gate
* 移动职责
* 删除确认死亡的 Legacy
* 运行测试并修复回归

不要每完成一个小步骤就询问用户下一步。

只要 Final Goal 尚未满足，就继续：

```text
inspect → plan → execute → verify
```

如果发现原计划与真实代码冲突：

**以当前代码和冻结 Architecture Invariants 为准，重新规划最小安全路径。**

不要为了遵循旧 Batch 编号而做错误修改。

---

# Stop Conditions

只有以下情况停止：

### SUCCESS

全部 Final Acceptance Criteria 满足。

输出：

1. Final Architecture
2. Removed Legacy Components
3. Remaining Compatibility（若有）
4. Architecture Gate Results
5. Full Regression Results
6. Production Runtime Chain
7. 尚未完成但明确属于未来产品开发而非架构迁移的事项

### BLOCKED

只有遇到无法在代码或测试中自行解决的外部阻塞才停止，例如：

* 缺失外部凭证
* 必须由用户决定的产品语义
* 第三方服务不可访问
* 不可恢复的数据迁移风险

不要因为：

* 修改范围较大
* 测试失败
* 依赖复杂
* Legacy 很多
* 需要多个 Batch

而停止 Goal Mode。

这些都属于你需要继续解决的问题。
