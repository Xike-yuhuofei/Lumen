# Teaching Core

`teaching_core` 是 Lumen 的显式教学决策层，位于现有 `knowledge`（资料/RAG）与
`learning`（Mastery Path 状态、测评、复习）之上。

它解决三个问题：

1. **Teaching Knowledge Model**：把材料从普通文本块提升为“可教学对象”。
2. **Teaching Knowledge Graph**：表达先修、解释、示例、纠错、测评等教学关系。
3. **Teaching Engine**：根据学习目标、学习者状态和教学图，确定下一步教学动作。

## 目录

```text
deeptutor/teaching_core/
├── models.py      # Teaching Knowledge Model + Engine contracts
├── graph.py       # Teaching Knowledge Graph
├── engine.py      # deterministic Teaching Engine
├── adapters.py    # 与现有 deeptutor.learning 的最小适配
└── tests/         # 教学决策单测
```

## 边的方向

统一使用 `source --relation--> target`：

- `A --prerequisite_of--> B`：A 是 B 的先修。
- `E --explains--> B`：E 用于解释 B。
- `X --example_of--> B`：X 是 B 的示例。
- `C --corrects--> M`：C 用于纠正误概念 M。
- `Q --assesses--> B`：Q 用于测评 B。

## 决策优先级

`TeachingEngine` 是纯决策层，不调用 LLM、不读写数据库：

```text
active misconception
    ↓
unmastered prerequisite
    ↓
first exposure → explain
    ↓
low mastery → example / explanation
    ↓
partial mastery → assess
    ↓
all targets mastered → complete
```

`TeachingDecision.trace` 保留最小决策轨迹，便于回放、测试和后续实验。

## 与现有 learning 的关系

现有 `deeptutor.learning` 继续负责：

- `LearningProgress`
- mastery 计算
- grading
- spaced review
- Mastery Path policy

`teaching_core` 不替代这些能力，而是增加“教学知识结构 + 教学动作选择”的上层语义。

`learner_state_from_progress()` 可以把现有 `LearningProgress` 投影为 Teaching Engine
所需的 `LearnerState`，但不会凭空推断先修关系或误概念关系。

## 下一阶段

当前版本是无存储、无 LLM 的最小内核。后续可依次接入：

1. 文档解析/RAG → Teaching Knowledge Model 抽取器；
2. SQLite 持久化 Teaching Knowledge Graph；
3. `TeachingDecision` → tutor prompt / tool orchestration；
4. 作答结果 → LearnerState / `LearningProgress` 更新闭环。
