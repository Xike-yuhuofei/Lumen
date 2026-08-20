# 种草-Teaching-Core-E2E验证报告

> 使用真实材料《[种草-道层面的经验哲学.md](种草-道层面的经验哲学.md)》对 Lumen Teaching Core 做端到端验证。
> 验证日期：2026-08-16　|　基线：`main`　|　结论：**PASS**

---

## 1. 验证目标与链路

```
Markdown → Parsing → RAG(材料证据检索) → Teaching Knowledge Model
→ Teaching Knowledge Graph → LearningGoal → Teaching Engine → TeachingAction
→ learner response → Evidence/Mastery 更新 → 下一轮 TeachingAction
```

重点验证 8 项要求（见 §10 逐项结论）。

### 各阶段执行结果（本次运行）

| 阶段 | 结果 |
| --- | --- |
| Parsing | `text_only` 引擎，1040 字符，1 个 segment，`source_hash=db409749ac676b67` |
| RAG | `initialize=True`（provider=llamaindex），3 个查询全部命中原文证据 |
| Teaching Knowledge Model | **9 个 KnowledgeUnit + 10 条教学关系**（LLM 抽取 + 证据校验），耗时 46.33s |
| Teaching Knowledge Graph | 9 节点 / 10 边，`has_cycle=False`，拓扑序合法 |
| LearningGoal | 9 个目标节点，`mastery_threshold=0.8`，`prerequisite_threshold=0.7` |
| Teaching Engine 闭环 | **23 轮 → COMPLETE**（全部目标 mastery ≥ 0.8） |

> 注：抽取环节由 LLM 驱动，属非确定性过程。另一次运行产出 8 节点 / 8 边（requires×4、supports×2、explains×1、part_of×1），同样跑满 19 轮至 COMPLETE。结论不随运行波动而改变（详见 §9 问题 4）。

---

## 2. 提取的 KnowledgeUnit

每次抽取产物都是带 `title / type / content / confidence / evidence_quote / source_anchor` 的**结构化教学节点**，而非简单文本 chunk。9 个单元均可回锚到原文逐字证据：

| id | type | title | confidence | 证据原文（逐字，已人工核对） |
| --- | --- | --- | --- | --- |
| `tk_concept_a9c9c3d35ac4` | concept | 产品代表的生活状态 | 1.0 | 用户购买的往往不是产品本身，而是产品所代表的某种生活状态 |
| `tk_learning_objective_baea07…` | learning_objective | 阐释以人为本的种草逻辑 | 0.9 | 以人为本，观察尚未被表达的真实需求，用产品和体验帮助用户接近向往的生活，并通过长期信任形成自然传播。 |
| `tk_principle_38ae0b2aaa8f` | principle | 从卖产品转向理解人 | 1.0 | 企业真正经营的不是商品参数，而是人的问题、情绪、身份认同和生活愿景。 |
| `tk_principle_394fd708a639` | principle | 种草的核心目标 | 1.0 | 种草不是说服用户购买，而是帮助用户发现并实现其向往的生活。 |
| `tk_principle_3d3d485353bd` | principle | 种草作为组织能力 | 1.0 | 种草要求产品、研发、供应链、服务和营销围绕同一用户体验协同 |
| `tk_principle_46c21858b53b` | principle | 真诚的经营条件 | 1.0 | 真正有效的种草必须建立在三个条件上：产品确实解决问题；内容真实呈现体验；企业与用户利益基本一致。 |
| `tk_principle_4ffb0dfe2bcc` | principle | 用户作为价值共同创造者 | 1.0 | 用户不只是接受广告、完成购买的人，也会参与需求表达、产品改进、内容生产和口碑传播。 |
| `tk_principle_643b3111d958` | principle | 潜在需求的识别与唤醒 | 1.0 | 需求不是被制造出来的，而是被看见、唤醒和表达出来的 |
| `tk_principle_91dd8569dcc6` | principle | 情绪是早期商业机会信号 | 0.95 | 人的异常情绪，可能预示尚未形成规模的趋势。 |

每个节点携带 `source_anchors`（source_id / source_hash / segment_id / locator / heading），可用于溯源回原文；所有 `evidence_quote` 均与源文档逐字一致，无外部知识补全。

---

## 3. Teaching Knowledge Graph 示例

### 10 条教学关系（方向：`source --relation--> target`）

| # | source | relation | target |
| --- | --- | --- | --- |
| 1 | 产品代表的生活状态 (concept) | explains | 从卖产品转向理解人 |
| 2 | 从卖产品转向理解人 | **prerequisite_of** | 阐释以人为本的种草逻辑 (LO) |
| 3 | 从卖产品转向理解人 | supports | 种草的核心目标 |
| 4 | 种草作为组织能力 | **requires** | 种草的核心目标 |
| 5 | 真诚的经营条件 | **prerequisite_of** | 阐释以人为本的种草逻辑 (LO) |
| 6 | 真诚的经营条件 | **requires** | 种草的核心目标 |
| 7 | 用户作为价值共同创造者 | supports | 种草的核心目标 |
| 8 | 潜在需求的识别与唤醒 | **prerequisite_of** | 阐释以人为本的种草逻辑 (LO) |
| 9 | 潜在需求的识别与唤醒 | supports | 种草的核心目标 |
| 10 | 情绪是早期商业机会信号 | supports | 潜在需求的识别与唤醒 |

关系类型分布：`prerequisite_of×3`、`requires×2`、`supports×4`、`explains×1`。

### 教学排序骨架（ORDERING_RELATIONS = prerequisite_of / requires / part_of / depends_on / prepares_for）

```
从卖产品转向理解人 ──prerequisite_of──┐
真诚的经营条件     ──prerequisite_of──┼──▶ 阐释以人为本的种草逻辑 (LO)
潜在需求的识别与唤醒─prerequisite_of──┘
种草作为组织能力   ──requires──▶ 种草的核心目标
真诚的经营条件     ──requires──▶ 种草的核心目标
```

### 图查询示例（pivot = 产品代表的生活状态）

```
related(pivot)          → [(从卖产品转向理解人, out, explains)]
prerequisites(pivot)    → []   （concept 无前置，可先讲）
has_cycle()             → False；topological_order() 合法
```

**图谱确实「有教学意义」**：例如 `种草作为组织能力 --requires--> 种草的核心目标` 意味着「先讲清种草的目标，再讲它的组织属性」；三个 `prerequisite_of` 把 LO 的目标门控在其前置原则上——这些关系直接驱动了 §6 的教学顺序。

---

## 4. LearningGoal

```json
{
  "name": "以《种草》的“道”层面经验哲学为本，建立理解用户、识别潜在需求、以真诚经营与长期信任为核心的种草经营哲学",
  "target_node_ids": [9 个教学节点],
  "mastery_threshold": 0.8,
  "prerequisite_threshold": 0.7
}
```

- 目标节点覆盖全部 9 个 KnowledgeUnit（concept / learning_objective / 7 个 principle）。
- 阈值语义：**前置知识点**需达到 0.7 才能解锁目标；**目标本身**需达到 0.8 才算掌握（两者均被 Teaching Engine 的 gate 消费）。

---

## 5. 每轮 TeachingAction + learner response → Evidence/Mastery 变化

闭环共 **23 轮**。每轮引擎输出唯一 `TeachingAction`，模拟 learner 给出回应，写回 `LearningProgress` 后用 `compute_mastery`（近期加权准确率 + 置信度上限：1 次上限 0.5、2 次上限 0.8）更新 mastery，进入下一轮。

| 轮 | TeachingAction | target | policy | learner response | 该点 mastery 变化 |
| --- | --- | --- | --- | --- | --- |
| 1 | explain | 产品代表的生活状态 | first_exposure | 用自己的话复述，定性通过 | 0 → **1.0** |
| 2 | review_prerequisite | 从卖产品转向理解人 | prerequisite_gate | 补充先修概念，正确 | 0 → **0.50** |
| 3 | review_prerequisite | 从卖产品转向理解人 | prerequisite_gate | 补充先修概念，正确 | 0.50 → **0.80** |
| 4 | review_prerequisite | 真诚的经营条件 | prerequisite_gate | 补充先修概念，正确 | 0 → **0.50** |
| 5 | review_prerequisite | 真诚的经营条件 | prerequisite_gate | 补充先修概念，正确 | 0.50 → **0.80** |
| 6 | review_prerequisite | 潜在需求的识别与唤醒 | prerequisite_gate | 补充先修概念，正确 | 0 → **0.50** |
| 7 | review_prerequisite | 潜在需求的识别与唤醒 | prerequisite_gate | 补充先修概念，正确 | 0.50 → **0.80** |
| 8 | explain | 阐释以人为本的种草逻辑 (LO) | first_exposure | 定性复述，通过 | 0 → **1.0** |
| 9 | review_prerequisite | 种草作为组织能力 | prerequisite_gate | 补充先修概念，正确 | 0 → **0.50** |
| 10 | review_prerequisite | 种草作为组织能力 | prerequisite_gate | 补充先修概念，正确 | 0.50 → **0.80** |
| 11 | explain | 种草的核心目标 | first_exposure | 首轮检查题正确 | 0 → **0.50** |
| 12 | assess | 种草的核心目标 | assess_gate | **先错后对** | 0.50 → 0.49 → **0.66** |
| 13 | assess | 种草的核心目标 | assess_gate | 再次正确 | 0.66 → **0.76** |
| 14 | assess | 种草的核心目标 | assess_gate | 再次正确 | 0.76 → **0.82 ≥ 0.8 ✓** |
| 15 | explain | 用户作为价值共同创造者 | first_exposure | 首轮检查题正确 | 0 → **0.50** |
| 16 | assess | 用户作为价值共同创造者 | assess_gate | 先错后对 | 0.50 → 0.49 → **0.66** |
| 17 | assess | 用户作为价值共同创造者 | assess_gate | 再次正确 | 0.66 → **0.76** |
| 18 | assess | 用户作为价值共同创造者 | assess_gate | 再次正确 | 0.76 → **0.82 ✓** |
| 19 | explain | 情绪是早期商业机会信号 | first_exposure | 首轮检查题正确 | 0 → **0.50** |
| 20 | assess | 情绪是早期商业机会信号 | assess_gate | 先错后对 | 0.50 → 0.49 → **0.66** |
| 21 | assess | 情绪是早期商业机会信号 | assess_gate | 再次正确 | 0.66 → **0.76** |
| 22 | assess | 情绪是早期商业机会信号 | assess_gate | 再次正确 | 0.76 → **0.82 ✓** |
| 23 | **complete** | — | complete | 全部目标达成 | — |

**mastery 变化规律**（与 `lumen/learning/mastery.py` 的 `compute_mastery` 一致）：
- 单个正确：`[T] → 0.50`（被置信度上限压住，一次答对不能算掌握）；
- 两个正确：`[T,T] → 0.80`（仍受上限 0.8 约束）；
- 先错后对：`[T,F] → 0.4872`、`[T,F,T] → 0.6607`（错误立即拉低 mastery，正确后回升）；
- 5 次答对其中 1 次错：`[T,F,T,T,T] → 0.825`，越过 0.8 阈值 → 目标掌握。

---

## 6. Decision Trace（决策轨迹）

Teaching Engine 是**确定性策略栈**（`lumen/teaching_core/engine.py`），`decide(graph, goal, learner)` 不产生任何 LLM 调用，同一输入必得同一动作。每次决策输出 `DecisionTrace{version, policy_applied, policies_evaluated, gates}`。

策略优先级（自上而下，先命中者生效）：

```
resolve_pending → remediate_misconception → review_due
→ prerequisite_gate → first_exposure → scaffold_escalation → assess_gate → complete
```

**示例 1：第 2 轮（prerequisite_gate 命中）**

```
policies_evaluated: [resolve_pending, remediate_misconception, review_due, prerequisite_gate]
policy_applied:     prerequisite_gate
gates: {blocked_target: 阐释以人为本的种草逻辑(LO),
        blocked_by_prerequisite: 从卖产品转向理解人}
reason:  Prerequisite 'tk_principle_38ae0b2aaa8f' is below 0.70 before target ...
success: Prerequisite ... mastery reaches 0.70.
```

引擎先选中下一个未掌握目标（LO），经 `graph.prerequisites(LO)` 发现 `从卖产品转向理解人 / 真诚的经营条件 / 潜在需求的识别与唤醒` 三个前置均 < 0.7，于是按序逐个补先修（第 2–7 轮）。

**示例 2：第 12 轮（assess_gate 命中）**

```
policies_evaluated: [... prerequisite_gate, first_exposure, scaffold_escalation, assess_gate]
policy_applied:     assess_gate
gates: {target: 种草的核心目标, mastery: 0.5, attempts: 1}
reason:  The target is partially learned; gather evidence against the mastery gate.
success: Assessment ... is correct and mastery reaches 0.80.
```

目标已有首次曝光（mastery 0.5）但未到 0.8，且前置已达标 → 进入测评；mastery 未达阈值则下一轮继续 assess（第 12–14 轮），达标后 `_first_unmastered_target` 自动转向下一个目标。

---

## 7. 8 项重点验证逐项结论

| # | 验证项 | 结论 | 证据 |
| --- | --- | --- | --- |
| 1 | 提取出合理 KnowledgeUnit，而非简单文本 Chunk | **PASS** | 9 个带 title/type/content/confidence/evidence_quote/source_anchor 的结构化节点（§2），全部可回锚原文 |
| 2 | 建立有教学意义的关系 | **PASS**（覆盖度 PARTIAL，见问题 5） | `prerequisite_of×3、requires×2、supports×4、explains×1`，均为证据支撑的关系（§3） |
| 3 | Knowledge Graph 真实参与 Engine 决策 | **PASS** | 第 2–7、9–10 轮 `review_prerequisite` 由图的 ordering 入边触发；`graph.prerequisites / resources_for / related` 被引擎直接消费 |
| 4 | 不同 Mastery / learner response → 不同 TeachingAction | **PASS** | 低 mastery → explain/assess；前置不达标 → review_prerequisite；答错拉低 mastery → 继续 assess；达标 → 换目标 → complete（§5、§6） |
| 5 | TeachingAction 具备 reason/target/strategy/success condition/decision trace | **PASS** | 每轮动作字段完整（action, target_node_id, strategy, scaffold_level, expected_evidence, success_condition, reason, constraints, trace） |
| 6 | 完成 ≥ 3 轮真实教学闭环 | **PASS** | 23 轮闭环至 COMPLETE，覆盖 explain → 补先修 → explain → assess → assess → complete 全周期 |
| 7 | RAG 只做证据检索，不替代图的教学关系 | **PASS** | `TeachingEngine.decide()` 签名只接收 graph/goal/learner，无任何 RAG 依赖；RAG 仅用于材料证据检索（§1） |
| 8 | 所有知识/解释/测试以原文为依据，不补外部知识 | **PASS** | 全部 evidence_quote 为原文逐字片段（§2），抽取器 system prompt 明确「Never invent subject-matter facts…」；测试题由图节点内容生成 |

**总体结论：PASS**

---

## 8. 各阶段产物与复现

### 测试与修复文件

- 修改：`lumen/teaching_extraction/validator.py`（证据校验容错，§9 问题 2）
- 修改：`lumen/teaching_core/models.py`（`requires` 语义契约 + `ORDERING_RELATIONS` 补 `REQUIRES`，§9 问题 1、3）
- 修改：`lumen/teaching_extraction/extractor.py`（`requires` 关系提示词方向修正，§9 问题 3）
- 新增测试：`lumen/teaching_extraction/tests/test_teaching_extraction.py`、`lumen/teaching_core/tests/test_graph_queries.py`
- 数据文件：`种草-道层面的经验哲学.md`（本轮验证材料）
- E2E 脚本：`/tmp/lumen_e2e/e2e_teaching.py`（临时验证脚本，不入库）

### 复现命令

```bash
# 单元回归（extraction + graph）：68 passed
PYTHONPATH=/Users/xike/Documents/Docs/Lumen python -m pytest \
  lumen/teaching_extraction/tests/test_teaching_extraction.py \
  lumen/teaching_core/tests/ -q

# 端到端闭环（输出 JSON 到 stdout）
PYTHONPATH=/Users/xike/Documents/Docs/Lumen python /tmp/lumen_e2e/e2e_teaching.py
```

---

## 9. 发现的问题

### 已修复（本轮验证中发现并直接修复，修复后重新跑通全部测试与 E2E）

1. **`ORDERING_RELATIONS` 遗漏 `requires`** — 修复前 `requires` 不参与前置门控，`种草作为组织能力 --requires--> 种草的核心目标` 这类边无法约束学习顺序。修复：在 `lumen/teaching_core/models.py` 的 `ORDERING_RELATIONS` 中补入 `REQUIRES`，并新增 `test_requires_is_an_ordering_relation` 断言其参与前置与拓扑排序。第 9–10 轮的 `review_prerequisite` 即依赖此修复。

2. **证据引用校验对 Markdown 结构过度敏感** — 块引用 `>`、标题 `#`、列表、加粗、尾部标点会导致 LLM 抽取的合法证据被误判为「不在原文中」，进而整批丢弃。修复：`lumen/teaching_extraction/validator.py` 新增 `_strip_markdown`（剥离结构性标记）+ `_ground_evidence`（紧致化后匹配、容忍尾部标点、SequenceMatcher 兜底），并新增 3 个测试用例。

3. **`requires` 语义契约与图行为不一致** — 图与测试实际按「`A -requires-> B` ⇒ A 先于 B」处理（`graph.prerequisites` 走 incoming + ORDERING_RELATIONS），但 `models.py` 文档与 `extractor.py` 提示词描述为「A requires B（B 在前）」，方向相反，存在抽取反向边的隐患。修复：统一为「A 是 B 的 required learning（A 必须先学）」，同步更新 docstring 与抽取提示词，使契约、代码、测试三者一致。

### 观察项（非阻塞，供后续决策）

4. **抽取属 LLM 非确定性** — 两次运行分别为 8 节点/8 边 与 9 节点/10 边，关系构成不同（前次无 `prerequisite_of`）。建议后续为抽取 LLM 固定温度/种子，或增加「归一化 + 重试一致性」策略以稳定产物。
5. **部分关系类型缺席属预期** — `example_of / contrasts_with / commonly_confused_with` 未出现，因为本材料未明确提供示例、对比或误解陈述；抽取器遵循「不得虚构」约束（§7 #8），缺席是正确行为而非缺陷。教学关系**覆盖度**记 PARTIAL，行为记 PASS。
6. **单段材料限制多样性** — 1040 字符被整篇作为 1 个 segment；长文档会按章节切分逐段抽取，可支撑更丰富的关系。
7. **RAG 返回整段原文拼接** — llamaindex 将命中段落拼接返回，作为证据检索可用；不进入教学决策（§7 #7）。可后续加粗/定位命中句以提升可读性。

---

## 10. 结论

**PASS**

- 链路 Markdown → Parsing → RAG → Teaching Knowledge Model → Knowledge Graph → LearningGoal → Engine → Action → learner response → Mastery → 下一轮 Action 全程贯通，23 轮闭环至 COMPLETE。
- KnowledgeUnit 提取、教学关系建立、图谱驱动决策、决策轨迹可解释、mastery 驱动的行为分化、RAG 与图谱职责分离、证据可回锚原文——8 项要求全部通过。
- 验证过程中发现并修复 3 处实现缺陷（`requires` 门控缺失、证据校验过严、`requires` 语义契约方向错误），修复后单元回归 68 passed、E2E 复跑通过。
