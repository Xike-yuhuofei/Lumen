# Perceived Waiting State Model v1（感知等待状态模型 v1）

> 状态：**FROZEN BASELINE**（T2 语义契约，可作为 T3｜Perceived Latency Metrics 输入） · 只定义状态与转换 · **不实现 UI / 不改生产代码**，不进入 T3
> 冻结标记：`FROZEN_BASELINE = "t2-perceived-waiting-state-model-v1"`（验收见 §13）
> 日期：2026-08-20 · 输入：`PERCEIVED_LATENCY_GAP_AUDIT.md`（G1–G8 / S1–S6）+ 真实事件能力
> 依据代码：`lumen/runtime/stream/events.py`、`turn_runtime.py`、P1 `langgraph_thin/plugin.py`、前端 `frontend/src/app/App.tsx`、`api/ws.ts`

---

## 0. 三平面模型（区分三类"状态"）

任何"状态"必须落在下列某个平面，禁止混用，否则会导致"用内部状态冒充用户状态"或"用假进度掩盖真实等待"：

| 平面 | 定义 | 本质 | 是否暴露给用户 |
|---|---|---|---|
| **B：后端内部执行状态** | 服务端在一次 Turn 内真实执行的阶段（上下文构建、LLM 生成、工具执行、重试退避、标题生成…） | 真实的算法/IO 推进，部分对 WS 不可见 | 否 |
| **O：可观测系统状态** | **客户端单调时钟**上可复现的事实：(a) 收到的 WS 事件流（带 `seq`）；(b) 传输层状态（connected/reconnecting/disconnected）；(c) 用户本机动作（提交 `submit`、`cancel`、`submit_user_reply`）；(d) 空闲计时器触发——**(a)–(d) 全部落在同一个客户端时钟时间轴** | 从真实事实可复现的证据轨迹（含客户端到达时刻） | 部分，经映射后 |
| **P：用户应感知状态（本模型产出）** | 从 O 平面（客户端单调时钟上的可观测事实 + `seq`）**确定性推导**的，驱动 UI 呈现的最小充分状态 | 状态机的节点 | 是（即用户界面上的等待/结果语义） |

**核心不变量（贯穿全文档）**：P 状态只由 **O 平面**推导。O 平面的输入是全球唯一的：(A) **客户端单调时钟**上记录的可观测事实（WS 事件**到达**时刻、用户本机动作、传输层事实、空闲计时器触发），(B) 事件携带的 `seq`（仅用于**定序/去重**，不携带时间）。**服务端时间戳不属于 O 平面**，仅供 B 平面内部诊断与关联（见 §11）。任何 P 状态转换都不得由"伪装的确定性进度"或"服务端时钟"触发（见 §9 I3/I11）。

---

## 1. 状态集合与精确定义

### 1.1 主状态机（Pipeline State，P 平面）

一个 Turn 的感知状态机。`S` = STARTING，`R` = RETRIEVING，`T` = TOOLING，`G` = GENERATING，`PIN` = PAUSED_INPUT，终态 `OK/ER/CA/TO`。

| 状态 | 分类 | 精确语义 | 触发进入的唯一来源 | 用户看到什么（现状） |
|---|---|---|---|---|
| **idle** `ℐ` | 初始/静止 | 当前没有在途 Turn。| 初始；或任意终态后用户发起新 Turn / 重置 | 可发送、无进行指示 |
| **starting** `S` | 活动·**等待首个价值/决定性事件** | 已提交，已过首个可见反馈（现状为同步"正在处理…"，或 `thinking/progress` 等**文案级**反馈），但**尚未收到任何决定性事件**（无非空 content 价值 token、无 tool/检索 信号）。`thinking/progress` 只提升文案、**不退出 S**。涵盖 S1 首 token 等待、S2 上下文摘要（被服务端过滤）、S3 Kernel 冷启动、S5 LLM 静默重试——这些后端内部推进对 P 平面**都不可见，且合法**。| 客户端 `submit`（§0 O 平面事实，§2.1） | 静态"正在处理…"+动画圆点 |
| **retrieving** `R` | 活动·中间工作 | 已收到检索/来源类决定性事件（`sources`，或检索类工具 `tool_call`：rag/kb_files/read_source 等），正在取回资料；还未进入生成。| `tool_call`/`sources`（检索类） | "正在检索/阅读资料…" |
| **tooling** `T` | 活动·中间工作 | 已收到**非检索**工具的 `tool_call`（且尚无后续 content），工具正在执行/分析其结果 `tool_result`。现状仅两端事件，**无子进度**（G4）。| `tool_call`（非检索类）/`tool_result` | "正在调用 X… / 正在分析结果…" |
| **generating** `G` | 活动·**产出值** | 已到达**首个非空 `content` token**（=首个有价值结果）后，答案正流式生成。**`G` 仅由非空 `content` 进入**；`thinking/progress/stage_start` 属文案级反馈，**不进入 G**（无 content 即无价值产出，见 §7）。| 首个非空 `content` | "正在生成回答…" |
| **paused_input** `PIN` | 活动·**等用户输入** | Turn 暂停，等待用户对 `ask_user` 答题；空闲超时对非输入端豁免（Audit §11.5）。| 后端 `WAIT_FOR_INPUT`（现状前端从 question 卡片推断，事件本身未消费——Audit §8） | 答题卡片，无进度指示 |
| **completed** `OK` | 终态 | 收到 `done`（status=completed）→ 回合成功结束。| `done`(completed) | 停止流式、保留已生成内容 |
| **failed** `ER` | 终态 | 收到终态 `error`（status=failed，`turn_terminal`）→ 回合失败。| `error`(failed) | 尾部错误状态块 |
| **cancelled** `CA` | 终态 | 用户/前端停止，或收到 `error("Turn cancelled")+done`（status=cancelled）。| 用户 cancel / `cancel_turn`→ cancelled | 停止、保留残留流式件 |
| **timeout** `TO` | 终态 | **前端**空闲计时器触发（`chatTimeout` 内无任何事件），非后端状态；追加超时错误并 `cancel_turn`。| 前端 idle timer（非 PIN） | "等待回复超时…"错误块 |

### 1.2 传输层正交覆盖状态（Transport Overlay）

与主状态机**正交**、由前端 WS 客户端持有，不与 P 状态互斥：

| 传输状态 | 语义 |
|---|---|
| `connected` | WS OPEN，有实时事件通道 |
| `reconnecting` | 断线后 seek 重连（指数退避 ≤5 次，Audit §11.3） |
| `disconnected` | 重连耗尽 / 心跳超时，事件通道丢失 |

> 语义规定：`disconnected` **不是** P 终态，不自动终结 `S/R/T/G/PIN`；它只改变"后续可达路径"（见 §2.4、§8）。

---

## 2. 完整合法状态转换关系

### 2.1 转换表（合法边）

```
ℐ --submit（新 Turn，submitLock 通过）--> S

S --tool_call(检索类)|sources --> R
S --tool_call(非检索) --> T
S --content(非空) --> G
S --thinking/progress（若出现）--> S   （文案级反馈，不产生推进，见 §5/§7）

R --tool_result --> R                （保持；tool_result 不改变 R/T 类属）
R --content(非空) --> G
R --tool_call(非检索) --> T
R --tool_call(检索) --> R

T --content(非空) --> G
T --tool_call(非检索)/tool_result --> T
T --tool_call(检索)|sources --> R

G --content --> G                     （流式延续）
G --tool_call(检索) --> R             （多步 Agent：生成后再度检索）
G --tool_call(非检索) --> T           （多步 Agent）

S/R/T/G --WAIT_FOR_INPUT --> PIN
PIN --submit_user_reply --> S          （恢复后由后续真实事件继续推进）
PIN --cancel --> CA

S/R/T/G/PIN --done(status=completed) --> OK
S/R/T/G/PIN --error(status=failed, turn_terminal) --> ER
S/R/T/G/PIN --user/backend cancel（cancelled）--> CA
S/R/T/G（非 PIN）--idle timer 到时 --> TO

（任意终态）--submit / 重置 --> S        （下一 Turn）
（任意活动态 / 终态）+ disconnected → 见 §2.4 传输通道
```

### 2.2 各类转换的分类

- **首反馈后进入活动**：`S` 是提交后第一个 P 状态（初始活动态）。
- **活动间推进**：`S⇄R⇄T⇄G`（Agent 内多轮工具/生成可往复，非单调，见 §2.3 例）。
- **暂停/恢复**：`*→PIN→S`。
- **终结**：`*→OK|ER|CA|TO`（一次且仅一次，见 §9 I1）。
- **重启**：终态→下一次 `submit`。

> **确定性子规则（无歧义目标）**：每条合法边都映射到**唯一确定**的目标状态。尤其 `R`/`T` 的类属**只由最近到达的决定性 `tool_call` 的 kind（检索类→`R`，非检索类→`T`）决定**；`tool_result`/`sources→R` 只"确认保留"当前类属，**绝不产生 `R|T` 之类的合并目标**。从 `S` 出发，第一个决定性事件若为非空 `content`→`G`，若为检索 `tool_call`/`sources`→`R`，若为非检索 `tool_call`→`T`，三者互斥且唯一。

### 2.3 多步 Agent 的合法往复（澄清"活动不是单调的"）

单轮 chat（Audit §3）为 `S→G→OK`。但带工具的多步 Agent 是 `S→R→G→T→R→G→OK`。因此从 `G` 回到 `R/T` **合法**（是真实的第二个阶段，而非状态倒退）。约束：任何活动→活动的迁移都必须由**新的、更高的、真实的事件**驱动；"因为没等够"或"因为 UI 要求"而回退是不合法的（见 §9 I4）。

### 2.4 传输层可达路径（disconnected 覆盖）

```
(任意 P 状态) --断线/重连耗尽--> (P 状态保持，传输=disconnected)
disconnected 期间：
  S/R/T/G --idle timer--> TO            （超时终结，允许）
  *  --用户 cancel--> CA
  R/G（前端已渲染 token）--无事件，保持--> （等待；用户可点停止）
disconnected --重新连接并 resume_from(自 lastSeq 重放)--> 恢复原 P 状态
disconnected --用户新 submit（submitLock 允许时）--> ① 先把未终结旧 Turn 判为 **CA**（用户主动放弃，本地取消，流式件按取消语义保留）② 再进入新 `S`
```

> **disconnected 下新 submit 的语义（消除与 I5/I10/I1 的冲突）**：不得在旧 Turn 上叠加新 `S`。新 `submit` 先把旧 Turn 标为**取消 `CA`**（明确终态，终态闩锁 I1 生效），使旧 Turn 不再活动，然后才进入新 `S`。这样始终满足：**任意时刻至多一个 P 活动态（I10）**、**`S` 只从 `idle`/终态后经一次 `submit` 进入（I5）**、旧 Turn 先达终态再启动（I1）。旧 Turn 迟到/残留事件因 turn_id/session_id 与新 Turn 不同而自然隔离（见 §9 冲突处理第 6 条）。

---

## 3. 每个转换的触发事件/条件（汇总表）

| 转换 | 触发 | 条件/卫式 |
|---|---|---|
| `ℐ→S` | 前端 `start_turn` | submitLock 通过、`streaming==false`、非在途（G8 防重复） |
| `S→R` | `tool_call`(rag/kb_files/read_source…) 或 `sources` | 事件 seq>当前 lastSeq |
| `S→T` | `tool_call`(web_search/web_fetch/code_execution…) | 同上 |
| `S→G` | `content` 且 content 非空 | 首个有价值结果（唯一来源；thinking/progress 不产生 G，见 §7） |
| `R/T→G` | `content` 非空 | — |
| `G→R/T` | 新一轮 `tool_call` | 真实多步阶段，seq 递增 |
| `*→PIN` | `WAIT_FOR_INPUT` | 后端暂停；现状以前端 question 块推断 |
| `PIN→S` | `submit_user_reply` | 收到答案，Turn 恢复 |
| `*→PIN→CA` | `cancel_turn` | 用户停止 |
| `*→OK` | `done`(status=completed) | 终态闩锁（I1） |
| `*→ER` | `error`(status=failed, turn_terminal) | 终态闩锁 |
| `*→CA` | `error("Turn cancelled")+done`(cancelled) 或用户 cancel | 终态闩锁 |
| `*→TO` | 前端 idle timer 到时（非 PIN） | 无任何事件灌入，非 WAIT_FOR_INPUT |

---

## 4. 后端真实执行状态 → 感知状态（平面 B → P 映射规则）

| 后端真实执行阶段 | 对 WS 是否可观测 | 映射到 P | 暴露/合并/隐藏 |
|---|---|---|---|
| 手动/持久化、分配 turn 并发 `session` [turn_runtime L871] | `session` 事件（O 可见） | 停留在 `S` 的入口（session 非决定性，见 §6） | 隐藏事件本身；前端用它取 turnId |
| 上下文构建 + 可选 LLM 摘要 [context_builder `summarize_context`] | **被服务端过滤**（`_emit_context_event` 丢弃 source∈{context,context_builder}，turn_runtime L1683–1687） | `S`（无变化） | **隐藏**（S2/G3） |
| Kernel/agent_loop 按需装配、LangGraph 编译 [turn_runtime L1978] | 无事件 | `S` | **隐藏**（S3/G6） |
| 首次 `model.generate`（TTFT） | 首 token 前无事件（P1） | `S` | **隐藏**（G1/S1）——这是本模型最大的合法静默区 |
| LLM 逐 token 输出 | `content` 事件 | `G` | **暴露**（首个有价值结果） |
| LLM 静默指数退避重试（5/10/20s…）[lumen.jsonl] | **无事件** | 仍在 `S`（原地不动） | **隐藏**（G2/S5），严禁伪造进度 |
| 工具调用开始 | `tool_call` | `R`/`T` | **暴露**（仅工具名，无子进度 G4） |
| 工具执行中/返回 | `tool_result` | 仍 `R`/`T`（"正在分析结果…"） | 暴露到"分析中"，子步骤隐藏 |
| ask_user 暂停 | `WAIT_FOR_INPUT` | `PIN` | **暴露**（答题卡片） |
| 正常完成 | `done`(completed) | `OK` | **暴露** |
| 终端异常 | `error`(failed, turn_terminal) | `ER` | **暴露**（尾部错误块） |
| 取消 | `error("Turn cancelled")+done`(cancelled) | `CA` | **暴露** |
| done 后生成标题 [turn_runtime L2197/2330] | `session_meta`（前端忽略） | 已是 `OK`，事件非决定性 | **隐藏**（G7） |

> 规则要点：**只有映到 `G/R/T/PIN/终态` 的事件才推进 P 的状态**；映到 `S` 的所有后端内部推进（摘要、冷启动、TTFT、重试退避）**在 P 平面零变化，且这是合法且有意的**——它们真实存在但按"非决定性"原则不外露。

---

## 5. 当前已有事件 → 感知状态（O → P 映射规则）

> 依据 `StreamEventType`（events.py）与前端 `deriveThinkingPhase`（App.tsx L1628–1653）。

| 事件 `type` | 是否决定性（影响 P） | 映射 | 备注 |
|---|---|---|---|
| `session` | 否 | 不改变（保留 `S`） | 仅用于取 turnId；前端直接 return [App L3125] |
| `session_meta` | 否 | 不改变 | 前端忽略（G7） |
| `thinking` | 否（文案级） | **维持 `S`**（文案"正在思考…"）；**不进 `G`**（无 content 即无价值产出） | P1 不发射（Audit §8） |
| `stage_start` | 否（文案级） | 按 `stage` 增强当前态文案（`STAGE_PHASE_LABELS`）；**不产生状态迁移** | P1 不发射 stage_start；context_builder 的已被过滤 |
| `stage_end` | 否（仅配对） | 不寂寞推进 | — |
| `content`(非空) | 是 | → `G` | 首个非空即首个有价值结果（G 唯一来源） |
| `content`(空) | 否 | 维持 | deriveThinkingPhase 对空 content 会回退文案（真实坑，见 §6） |
| `tool_call` | 是 | 检索类→`R`；其余→`T` | 用 `TOOL_PHASE_LABELS`（App L1598）；决定 R/T 类属 |
| `tool_result` | 是（确认性） | 确认/保留当前 `R/T`（"正在分析结果…"） | 不改变类属（G4 无子进度） |
| `progress` | 否（文案级） | 增强当前态文案（"正在{msg}…"） | P1 几乎不发（Audit §8 闲置能力） |
| `sources` | 是 | → `R` | — |
| `result` | 否 | 不推进（紧邻 done） | 现状会使 `deriveThinkingPhase` 回退为"正在处理…"（真实坑，见 §6） |
| `error` | 终态 | → `ER`（failed）/经 `CA`（cancelled） | 依 metadata.status |
| `done` | 终态 | → `OK`（completed）/`CA`（cancelled）/`ER`（failed） | 依 metadata.status；backend 默认 completed [turn_runtime L2088/2222] |
| `wait_for_input` | 终态-暂停 | → `PIN` | 前端类型集不含它，现状从 question 块推断（Audit §8） |

---

## 6. 前端可见状态 ↔ 后端真实执行状态之间的缺口（对应 Audit §7）

缺口由模型语义显式标注，作为"P 状态与 B 状态允许不一致"的**受控说明**，而非缺陷：

| 缺口 | 后端（B） | 前端现状（O 呈现） | 模型语义 |
|---|---|---|---|
| S1 首 token | 在 TTFT/配装中 | 静态"正在处理…"、`S` | 合法静默；P=Start 有意不细分 |
| S2 摘要 | 在做整轮 LLM 摘要 | 事件被过滤、`S` | 合法隐藏 |
| S5 重试退避 | 在指数退避 | 无事件、`S` 不动 | 合法隐藏，**严禁假进度** |
| S4 工具 | 工具执行中 | 仅工具名 `T` | 暴露到工具粒度，子步骤隐藏 |
| `result` 空 content | 即将 done | `deriveThinkingPhase` 回退"正在处理…" | **真实文案回退**（非模型所需，是映射噪声；记入 §6 待 T3 修正） |
| G7 标题生成 | done 后 ≤20s | `session_meta` 被忽略 | 属 `OK` 之后的非决定性事件 |
| G5 断线 | 后端可能仍在跑 | `streaming` 保持、横幅 | 传输覆盖层 `disconnected`；非 P 终态 |

> 模型明确定义这些不一致**哪些必须缩短（S1）、哪些允许存在（S2/S5 隐藏）**，为 T2→T3 提供判定依据。

---

## 7. 暴露 / 合并 / 隐藏规则（原则性结论）

**暴露为用户独立 P 状态**：
- `S`（等待首个价值/决定性事件）、`G`（生成中=首个有价值结果）、`R`/`T`（中间工作）、`PIN`（等输入）、`OK/ER/CA/TO`（终态）。

**合并（不单列 P 状态）**：
- `thinking`/`progress` → **并入当前活动态（`S`/`R`/`T`/`G`）的文案**，属**文案级反馈**；它们**不产生状态迁移、绝不进入 `G`**（无 content 即无价值产出）。`thinking` 在 `S` 内提升为"正在思考…"。
- `stage_start`（若发出）→ 仅增强当前态文案，不产生迁移（见 §5）。
- `sources` → 并入 `R`（检索的文案风味，`sources` 为决定性→`R`）。
- 上下文摘要、冷启动、TTFT、重试退避 → 全部并入 `S`（隐藏内部步骤，不制造多状态）。

**隐藏（内部 B 状态，禁止上屏）**：
- 具体 LLM provider/模型名、调用轮次、token 计数。
- 重试尝试次数与退避时长（S5）。
- 上下文摘要内部、Kernel 装配细节（S2/S3）。
- 标题生成（G7）、seq/恢复机制、队列/等待内部细节。

原则：**用户状态颗粒度 = 用户能据此做决策的最小充分集**；技术步骤（每次重试、每次检索子调用、每次摘要）**不属于**用户状态，绝不因此新增 P 状态。

---

## 8. 特殊情形的状态语义（对应 Audit §8 要求）

| 情形 | P 语义 | 传输层/终态交互 |
|---|---|---|
| **静默运行**（S1/S2/S3/S5 内） | 处于 `S`；无事件则 P 不动 | 合法；由 idle timer 兜底终结 |
| **LLM 重试/退避**（S5） | 仍在 `S`（零变化） | **明令禁止**用"正在重试第 N 次"这类假进度；若退避序列超 idle timer，由前端 `TO` 终结（G2 超时不同步风险，须由 T3 度量） |
| **工具/检索执行**（S4） | `T`/`R`，仅工具名 | 无子进度是现状；模型不杜撰子阶段 |
| **WAIT_FOR_INPUT**（PIN） | `PIN`，**豁免 idle 超时** | 仅 `submit_user_reply` 或 `cancel` 离开；断线则等重连恢复 |
| **取消** | `CA`（保留已渲染流式件，Audit §12.7 不变量） | 终态闩锁；终态后事件全部丢弃 |
| **超时** | `TO`（前端判定） | 与后端终态互斥（先到者胜，§9 I7） |
| **连接异常** | P 状态保持（不终结）；传输=`disconnected` | 只产生 `TO`（timer）或 `CA`（用户）；重连后 `resume_from(lastSeq)` 重放恢复 |

---

## 9. 非法状态转换与冲突/异常事件处理原则

**非法转换（禁止）**：
- 从非终态活动态直接 → `idle`（必须经 `OK/ER/CA/TO` 终结；`disconnected` 不省略该终结步骤）。
- 非终态活动态二次 `submit`（G8 防重复；client 用 submitLock 拦截）。
- 从 `PIN` 由 idle timer → `TO`（PIN 豁免）。
- 任何由"UI 需求/等待时长"触发的活动态伪造迁移（如"等 5 秒就当在思考"）——违反 I3。

**冲突事件处理原则（统一规则，确定性、可回放）**：
1. **终态闩锁（I1）**：到达任终态后，新到事件一律丢弃（幂等）。首个终态胜出，"done 迟到 vs idle 超时 / 取消 racing done"均适用。
2. **seq 单调守卫（I6）**：seq < 当前 lastSeq 的迟到/重播事件丢弃；`resume_from` 从 lastSeq 续播，保证可回放。
3. **活动事件须真实且递增（I4）**：`G→R/T` 回退只允许携带更高 seq 的真实新工具阶段；否则视为陈旧丢弃。
4. **传输与终态正交（I8）**：`disconnected` 不终结任何 P 状态；终结只能由 `OK/ER/CA/TO` 到达。
5. **非决定性/文案级事件（I2 附）**：`session/session_meta/result/空 content/thinking/progress/stage_start/stage_end` 不触发迁移（thinking/progress/stage_start 仅增强当前态文案，见 §5/§7）；映射噪声（如 `result` 导致文案回退）不作为状态转换，另记入 T3 度量修正。
6. **Turn 隔离（配合 I10）**：事件按 `(session_id, turn_id)` 归属；新 Turn 的 `S` 启动后，旧 Turn（已判 `CA` 或其他终态）的迟到/残留事件因 `turn_id` 不同而**不作用于新 Turn**（见 §2.4）。

**可用于自动化测试的状态机不变量**：

- **I1 终态不可变**：进入 `{OK,ER,CA,TO}` 后任意后续事件不改变状态（终态闩锁、幂等）。
- **I2 真因推进**：`*→G` 仅由非空 `content` 触发；`thinking/progress/stage_start` 不得产生 `G`；任何计时器/合成事件不得产生 `G`。
- **I3 无假进度**：计时器唯一能力是从非 PIN 活动态派发 `TO`；不产生 `S→R/T/G` 之类推进。
- **I4 活动因果**：每次活动↔活动迁移都对应一条 seq 递增的真实事件；无事件则活动态原样保持。
- **I5 单 Turn 启动**：`S` 只从 `idle`（或终态后）经一次 `submit` 进入；任何活动态再次 `submit` 为非法并被忽略。`disconnected` 下新 `submit` 必须先把未终结旧 Turn 判为 `CA` 再进入新 `S`（见 §2.4）。
- **I6 seq 单调**：处理顺序内 seq 非降；<lastSeq 丢弃。
- **I7 终态互斥**：`TO` 与后端 `OK/ER` 互斥；先到者胜；`CA` 可由用户或 cancelled 达成且唯一。
- **I8 传输非终态**：`disconnected` 不改 P 终态；仅 `OK/ER/CA/TO` 是 P 终态。
- **I9 可重放确定性**：给定同一有序事件日志（每个决定性事件记录**客户端到达时刻 + seq**），从冷客户端重放得到**完全一致**的状态序列、终态与感知延迟（hard 输入给测试）。
- **I10 至多一活跃**：任意时刻至多一个非终态 Turn 处于 P 活动态。
- **I11 时间轴单一**：感知状态与指标的时钟统一为**客户端单调时钟**；服务端 `timestamp` 不驱动任何 P 状态或感知指标（仅 B 平面诊断）；`seq` 仅定序、非时间（见 §11）。

---

## 10. 覆盖 Gap Audit 场景（G1–G8 / S1–S6 自检）

| 待覆盖项 | 模型覆盖位置 |
|---|---|
| G1 / S1 首 token 静默 | §1 `S`；§4 TTFT 隐藏；§9 I2 真因推进（无假进度） |
| G2 / S5 LLM 静默重试 | §1/§4/§8 重试；§9 I3 禁假进度、I7 后端终态与 TO 互斥 |
| G3 / S2 摘要被过滤 | §4 上下文摘要合并进 `S`；§8 静默运行 |
| G4 / S4 工具无子进度 | §1 `T/R`；§4 工具粒度暴露、子步骤隐藏 |
| G5 断线不复位 | §1.2 传输覆盖层；§8 连接异常；§9 I8 |
| G6 / S3 冷启动 | §4 Kernel 装配并入 `S` |
| G7 标题生成 | §5/§6/§7 `session_meta` 非决定性隐藏 |
| G8 重复提交 | §9 I5/I10 submitLock 守卫 |
| 成功完成 / 失败 / 取消 / 超时 | §1 终态 `OK/ER/CA/TO`；§3 触发 |
| 等待用户输入 | §1 `PIN`；§2.1 `*→PIN→S`；§8 WAIT_FOR_INPUT |

=> 全部覆盖，无遗漏。

---

## 11. T3｜Perceived Latency Metrics v1 所需的状态与时间边界定义

> 只给**边界定义**，不做指标实现（T3）。

### 11.1 三条时间/顺序轴的严格分工（消除前后端 wall-clock 混用）

| 轴 | 载体 | 用途 | 是否驱动 P 状态/感知指标 |
|---|---|---|---|
| **客户端感知时间轴** | 客户端**单调时钟**（`performance.now`/前端时钟），记录事件**到达**时刻、用户本机动作（`submit`/`cancel`/`submit_user_reply`）、空闲计时器触发时刻 | **一切感知延迟指标的时钟**（`t_*`、`gap`、`max_silent`、`time_in`） | **是（唯一）** |
| **服务端诊断时间轴（B 平面）** | 后端 wall-clock / 服务端单调时钟：事件 `timestamp` 字段、日志时戳，`trace_id` 关联 | 内部定位、重试/耗时/关联诊断 | **否**（仅供 B 平面诊断与关联） |
| **顺序轴 `seq`** | 事件携带的递增序号（turn 内） | 定序、去重、`resume_from` 续播、可回放确定性 | 否（不为时间；重放时与客户端到达时刻共同记录） |

> **规则**：P 状态与感知指标**必须**取客户端到达时刻。服务端 `timestamp` 只作关联与诊断，混用会因网络抖动与时钟偏移使"感知延迟"失真——G2 超时不同步、S1 静默窗口测不准即属此类（I11）。

### 11.2 关键时刻基元（全部为客户端单调时钟）
- `t_submit`：前端发出 `start_turn` 的客户端时刻。
- `t_session`：首个 `session` 事件到达客户端时刻。
- `t_first_decisive`：首个**决定性**事件（首个 `tool_call/sources/content(非空)…`）到达客户端时刻；`latency_first_phase = t_first_decisive − t_submit`。
- `t_first_token`：首个非空 `content` 到达客户端时刻；`latency_first_token = t_first_token − t_submit`（**对应审计 S1，首个有价值结果**）。
- `t_done`：`done` 到达客户端时刻；`latency_total = t_done − t_submit`。
- `t_user_reply`：`PIN` 内 `submit_user_reply` 发出的客户端时刻（**剔除 PIN 段"用户思考时长"，不计入系统等待**）。

### 11.3 静默、终态、断线边界（同客户端轴）
- **静默**：非终态活动态内相邻**决定性**事件的客户端到达间隔 `gap_i = t_{e_{i+1}} − t_{e_i}`；`max_silent = max gap_i`（审计 §3 实测 8.256s 即此量）；`time_in(S)` = S 内累积时长。
- **终态**：`OK`(done=completed) / `ER`(error=failed) / `CA`(cancel 事件或§2.4 用户放弃) / `TO`(空闲计时器触发)。`TO` 的 `t`=计时器客户端触发时刻；其余=对应终态事件到达客户端时刻。
- **断线**：`disconnected` 开始=最后一次收到事件/心跳超时的客户端时刻；结束=重连成功（`resume_from`）或 `TO/CA`。

### 11.4 交付 T3 的事件白名单
- **决定性**（触发 P 迁移，度量轴）：`{content(非空), tool_call, sources, tool_result(保留 R/T 类属), wait_for_input, done, error}` ＋ 用户 `cancel`/空闲计时器。
- **文案级/非决定性**（不迁移，仅增强文案或忽略）：`{thinking, progress, stage_start, stage_end, session, session_meta, result, content(空)}`。
- T3 以决定性白名单为测量轴，规避 `result`/空 `content` 的文案回退噪声（§6）；文案级事件只贡献文案、不进感知延迟分母。**可回放**要求重放日志同时记录每个决定性事件的**客户端到达时刻 + seq**（配合 I9）。

---

## 12. 代表性事件轨迹验证（含确定性推导与可回放演示）

> 记法：事件流（`session`/`thinking`/`tool_call(类)`/`tool_result`/`content`/`sources`/`WAIT_FOR_INPUT`/用户`cancel`/`reply`/`done`/`error`/空闲计时器）→ 推导出的 **P 状态序列** → **终态**。文案级事件（`thinking`/`progress`/`stage_start`）只增文案、不改变状态序列。

| # | 场景 | 事件轨迹 | P 状态序列 → 终态 | 依据 |
|---|---|---|---|---|
| T1 | **正常生成**（chat，Audit §3 实测） | `session → content(nonempty) → content… → result → done(completed)` | `S → G(−→ 维持 G) → OK` | §1/§5；空/`result` 非决定性 |
| T2 | **工具/检索** | `session → tool_call(rag) → tool_result → content(nonempty) → done` | `S → R(保持) → G → OK` | §2.1（R 的 tool_result 保持） |
| T3 | **多步 Agent** | `session → tool_call(rag) → tool_result → content → tool_call(web_fetch) → tool_result → content → done` | `S → R → G → T → G → OK` | §2.1/§2.3（G→T 为真实新阶段） |
| T4 | **WAIT_FOR_INPUT** | `session → content → WAIT_FOR_INPUT → (user reply) → content → done` | `S → G → PIN → S → G → OK` | §2.1（PIN 豁免 idle 超时） |
| T5 | **重试静默**（S5） | `session → (后端退避，无事件) → content(nonempty) → done` | `S → S(原地) → G → OK`（**无假进度**） | §1/§8/S5；I3 |
| T6 | **断线恢复** | `session → content → [disconnected→reconnect→resume_from] → done` | `S → G →(传输变化，P 保持 G)→ OK` | §1.2/§2.4/§8；I8 |
| T7 | **取消** | `session → content → (user cancel) → error("Turn cancelled")+done(cancelled)` | `S → G → CA` | §2.1/§8；终态闩锁 |
| T8 | **超时** | `session → (无事件直到计时器) → idle timer 触发` | `S → TO` | §2.1/§9 I3（timer 仅产 TO） |
| T9 | **竞态·done vs cancel** | `session → content → (同刻到达) done(completed) 先于 cancel 处理` | `S → G → OK`（迟到 cancel 丢弃） | I1/I7 先到者胜 |
| T10 | **竞态·done 迟到 vs TO** | `session → (记时器先触发) → TO；随后迟到 done` | `S → TO`（迟到 done 丢弃） | I1/I7 先到者胜 |
| T11 | **断线后新 submit** | `session → content → [disconnected→新 submit] → 新 session → content → done` | 旧 `S → G → CA`；新 `S → G → OK`（**并行活动态不出现**） | §2.4；I5/I10/I1 |
| T12 | **thinking 不产生 G** | `session → thinking → content(nonempty)` | `S →(thinking 文案级，仍 S)→ G` | I2/I11 语义；G 只由 content 进入 |

**同一轨迹重放一致性（完成标准 #10）**：对任意一行（如 T3 或 T11），把同一有序事件日志（每个决定性事件带**客户端到达时刻 + seq**）从冷客户端重放，得到的 **P 状态序列与终态逐一对齐**——因为：(a) 每条合法边目标唯一（§2.2），状态由决定性事件集决定；(b) 终态先到者胜且闩锁（I1/I7）；(c) 文案级事件不影响状态；(d) T11 中旧 Turn 因 `turn_id` 隔离且先判 `CA`，重放结果唯一。故满足确定性、可解释、可测试、可回放（I9 的 "hard" 输入即上表轨迹）。

---

## 13. 修正验收与 FROZEN BASELINE 声明

> 完成标准逐项核验，全部通过后正式冻结本 T2。

| 完成标准 | 落实 |
|---|---|
| ① 5 项语义冲突全部明确一致解决 | Conflict 1→§1.1/§2.1/§5/§7/I2（thinking 不进 G）；Conflict 2/4→§0/§11/I11（O 平面=客户端单调时钟，含用户动作；三条时间轴分工）；Conflict 3→§2.1/§2.2（R/T/T 类属唯一确定，消除 `R|T`）；Conflict 5→§2.4/I5/I10/冲突处理第 6 条（断线下新 submit 先 CA） |
| ② `G`/首 token/首个有价值结果无定义歧义 | `G`=首个非空 `content` 到达（§1.1/§5）；thinking/progress/stage_start 均不产生 G（I2/§7） |
| ③ 合法转换目标唯一 | §2.2 确定性子规则；`R|T` 已删除 |
| ④ P 状态可观测输入边界统一自洽 | §0：O 平面=客户端单调时钟事实(a–d)+seq；服务端时间不属 O |
| ⑤ 三条时间轴职责分明 | §11.1 表；感知=客户端单调时钟，诊断=服务端，定序=seq |
| ⑥ disconnected/resume/cancel/timeout/新 Turn 与单活跃/终态一致 | §2.4/§8/§9 I5/I7/I8/I10/冲突第 6 条；轨迹 T6/T7/T8/T11 验证 |
| ⑦ 全部不变量重验证无内部冲突 | §9 I1–I11；T1–T12 一致 |
| ⑧ G1–G8、S1–S6 仍全部覆盖 | §10 自检 => 无遗漏 |
| ⑨ 代表性轨迹验证 | §12 T1–T12（正常生成/工具检索/多步/WAIT_FOR_INPUT/重试静默/断线恢复/取消/超时/竞态） |
| ⑩ 同一轨迹重放一致 | §12 重放说明（确定性来源 I1/I4/I6/I7/I9） |
| ⑪ T3 边界严谨但未实现 T3 | §11 只给边界定义；本节明确不进入 T3 实现 |
| ⑫ 冻结 | 本条目即声明（见下） |

**结论**：上述 12 项完成标准全部通过。**T2 per `PERCEIVED_WAITING_STATE_MODEL_V1.md` 正式标记为 `FROZEN BASELINE`**（`FROZEN_BASELINE = "t2-perceived-waiting-state-model-v1"`，见文档头部）。该基线作为后续 T3｜Perceived Latency Metrics 的统一语义输入；**不实施 UI / 不改生产代码 / 不进入 T3 实现**。

---