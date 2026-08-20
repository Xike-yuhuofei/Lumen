# Perceived Latency Gap Audit（感知等待时间缺口审计）

> 状态：现状基线 · 审计完成 · **不实施修复**
> 日期：2026-08-20 · 范围：Lumen 前台主要用户链路（AI 对话 / Agent Loop / LLM / Tool Calling / Retrieval / 结果返回）
> 生产 Agent Loop：P1 `agent_loop.langgraph_thin`（`lumen/profile.py` binding），Legacy(P0) 为 shadowed 回退。
> 证据基准：代码 + 真实运行测量 + 运行日志，见 §11。

---

## 1. 审计目标与方法

- **只审计，不设计解决方案、不改生产代码/UI/交互/架构。**
- 关注**感知等待**（用户视角），而非后端真实性能优化。
- 区分五类时刻（沿用题干要求）：①请求提交 ②首次可感知反馈 ③中间状态反馈 ④首个有价值结果 ⑤最终结果；并识别静默区间、卡死误判、前后端状态缺口、重复提交与取消/超时风险。
- 证据来源（非仅源码推断）：
  1. **代码**：`frontend/src/app/App.tsx`、`api/ws.ts`、`api/sessions.ts`；后端 `turn_runtime.py`、`context_builder.py`、`unified_ws.py`、P1 `langgraph_thin/plugin.py`、`evolution/providers/langchain_thin.py`。
  2. **真实运行测量**：对运行中的后端（`ws://localhost:8001/api/v1/ws`）发出一次真实 `start_turn`，逐步记录每个 WS 事件的到达时刻（§3）。
  3. **运行日志**：`data/user/logs/lumen.jsonl`（LLM 静默重试 + 超时的带时戳证据）。

---

## 2. 端到端链路与事件模型

用户提交 → 前端 → WS `/api/v1/ws` → `TurnRuntimeManager.start_turn` →（`session` 事件）→ `_run_turn`：

```
提交 → [session 事件 ~立即] → 上下文构建(可含LLM摘要，事件被过滤) → Kernel/agent_loop 装配与 LangGraph 编译
     → P1 agent_node 首次 model.generate（TTFT）→ content 流式 → [tool_call/tool_result…] → result → done
```

**事件到达顺序（实测 & 代码一致）**：`session`（13ms）→（静默 ~8.26s）→ `content` 逐 token → `result` → `done`。

前端消费（`App.tsx`）：submit 时立即 `setStreaming(true)`+`streamPhase='正在处理…'`；`handleStreamEvent` 对每个事件 `deriveThinkingPhase` 更新阶段文案，`eventsToBlocks` 重建气泡；`done`/`error` 置 `streaming=false`。

---

## 3. 主机场景：AI 对话（chat，无工具）——真实测量

请求：`"用一句中文介绍一下你自己。"`，capability=chat，空工具。逐步记录：

| t (s) | +Δ(s) | type | stage | 说明 |
|---|---|---|---|---|
| 0.000 | — | *(send)* | | 前端已显示"正在处理…"+停止按钮（同tick） |
| 0.013 | 0.013 | session | | turn_id/session_id 到位（前端据此拿到 turnId） |
| 8.269 | **8.256** | content | responding | **首个可见内容 token** |
| 8.31–9.99 | ~0.04 | content×40 | responding | 逐 token 平滑流出 |
| 9.993 | 0.045 | result | | content=空（答案在 metadata，不重复拼接） |
| 10.000 | 0.007 | done | | status=completed |

- 回合总时长 **≈10.0s**；其中 **前 8.26s（82%）只有静态"正在处理…"，无任何阶段变化**。这是本回合唯一的、持续时间最长的静默区间（`MAX_SILENT_GAP=8.256s`，落在 `session→首个 content`）。
- 首次可感知反馈=立即（动态圆点 + "正在处理…"）；首个有价值结果=8.27s；最终结果=10.0s（`done`）。
- 结论可复现：对运行中后端重发同请求即可复测（见 §11.6）。

> 注：该测量使用后端当时激活的 Qwen 系模型（TTFT 占主导）；不同 provider 的数字会变，但**结构缺口**（首个 content 之前没有 thinking/stage/progress 事件）由代码决定（§11.6），与模型无关。

---

## 4. 各场景"呈现给用户的状态/反馈"矩阵

| 场景 | 请求提交 | 首次可感知反馈 | 中间状态反馈 | 首个有价值结果 | 最终结果 |
|---|---|---|---|---|---|
| chat 简单回合 | 输入清空、气泡出现 | 同tick："正在处理…"+圆点+停止 | 首个content前无阶段变化 | 首个 content token | done→停止流式 |
| 长历史触发摘要 | 同上 | 同上（**摘要阶段被服务端过滤**） | 无（等待1轮额外LLM摘要） | 摘要+agent后首token | done |
| 首次回合(Kernel冷启动) | 同上 | 同上(仅"正在处理…") | 无 | agent 首 token | done |
| 工具调用(检索/搜索/代码) | 同上 | tool_call→"正在调用/检索工具…" | 仅静态工具label，**无子进度/百分比** | 工具返回后 agent 首 token | done |
| 错误(终端异常) | 同上 | 同tick疑惑文案 | — | — | error 事件→尾部错误status块+停止 |
| LLM 静默重试 | 同上 | 同tick"正在处理…" | **无（重试完全不可见）** | （重试成功后）首 token | （若超时→前端超时错误） |
| 取消 | 停止按钮→handleCancel | | cancel→error("Turn cancelled")+done | | streaming=false |
| 后端不可达 | 同tick"正在处理…" | ~6s 后 reconnect 尽→红色 connectError 横幅 | 无 | — | 仅当用户点停止或180s空闲超时 |

---

## 5. 静默区间清单（用户侧"无任何变化/无实质进展"时段）

| # | 区间 | 时长(实测/推定) | 前端呈现 | 证据 |
|---|---|---|---|---|
| S1 | submit → 首个 content（TTFT+上下文集装） | **8.26s（实测）** | 静态"正在处理…"+圆点 | §3 实测；§11.6 |
| S2 | 长历史 → LLM 摘要阶段 | 1 次完整 LLM 回合（数秒，推定≤20s） | 静态"正在处理…" | `context_builder.py` `_summarize`；`turn_runtime.py` 过滤 §11.1 |
| S3 | 首次回合 Kernel/agent_loop 装配 | 秒级（一次性） | 静态"正在处理…" | `turn_runtime.py:1978` 按需 boot |
| S4 | 工具执行期间（检索/搜索/代码） | 工具耗时（数秒至更长） | 静态工具 label，无子进度 | P1 `plugin.py` 仅 tool_call/tool_result |
| S5 | LLM 静默重试（指数退避） | 5s→10s→20s…（逐次） | 无任何变化 | §11.7 带时戳日志 |
| S6 | done 后的后端标题生成 | 至多 20s | 前端已停，无标题更新 | `turn_runtime.py:2197,2330` |

---

## 6. 用户可能误判为"卡死"的具体场景

1. **S1**：提交后 8s+ 只有动画圆点、文案不变 —— 尤其当模型 TTFT 用满预算或网络慢时，用户无法判断"还在首token还是卡死"。
2. **S5**：LLM 静默退避重试（日志实测 5/10/20s 级递增），**前端全程无变化**，是"黑盒等待"的典型；若退避序列长度 > 前端180s空闲超时，后端仍在重试时前端会先报"等待回复超时"并 `cancel_turn`，两端状态不一致。
3. **S3**（服务端重启后首回合）：Kernel 冷启动被算进首token等待，前端无"正在启动/初始化"提示。
4. 后端不可达：WS 连不上时点"发送"，前端立刻进入"正在处理…"，直至 ~6s 才出红色 connectError 横幅，且 `streaming` 不会自动复位，仍需用户点"停止"或等 180s 空闲超时。

---

## 7. 前端可见状态 ↔ 后端真实执行状态之间的缺口

| 后端真实阶段 | 前端可见 | 原因 |
|---|---|---|
| 上下文摘要（summarize） | 无，"正在处理…" | `turn_runtime._emit_context_event` 过滤 `source in {context, context_builder}`，客户端收不到 | 
| LLM 重试/退避 | 无 | 重试发生在 `llm.provider_core.base`，不向 bus 发事件 |
| 首token等待(TTFT) | 无阶段 | P1 在首个 content 前不发 thinking/stage/progress |
| 工具执行中 | 静态工具 label | P1 只发 tool_call/tool_result |
| 后端生成标题(done后) | 不生效 | 前端 `handleStreamEvent` 对 `session_meta` 直接 `return` |

---

## 8. 已存在但未被有效利用的状态/事件能力

- **`progress` 事件**（`bus.progress` + 本地化文案 `stream.progress`）：legacy/engine 会发出丰富进度；P1 只在终止警告时发；context_builder 的 `summarize_context` progress 被服务端过滤。前端 `deriveThinkingPhase` 支持 progress 文案，但生产 P1 几乎不发 → 能力闲置。
- **`thinking` 事件**：事件类型、前端"正在思考…"分支都存在，但 P1 生产路径**从不发射** → 该提示实际是死分支。
- **`stage_start/stage_end` + `stage` 字段**：前端可按 `stage` 映射中文阶段，但 P1 不发射 stage_start；context_builder 发的被过滤。
- **`session_meta`（后端 LLM 标题）**：前端忽略 → 生成结果浪费。
- **`WAIT_FOR_INPUT`**：P1 ask_user seam 发此事件，前端类型集不含它，仅靠 `tool_call.args.questions` 出题卡 → 事件本身未消费。
- 现有 **`chatTimeout` 空闲超时**（默认180s）+ **ask_user 等待豁免** 是已部署的保护，但缺"等待时长/节奏"的可见化。

---

## 9. 按严重程度整理的感知等待体验问题清单

| 级别 | ID | 问题 | 主要证据 |
|---|---|---|---|
| 🔴 高 | G1 | 首token前静默窗口无阶段/无进度（S1，实测8.26s） | §3, §11.6 |
| 🔴 高 | G2 | LLM 静默指数退避重试完全不可见，用户误判卡死；可能超时不同步 | §5 S5, §11.7 |
| 🟠 中 | G3 | 长历史回合触发LLM摘要，阶段被服务端过滤，多付一整轮等待却不告知 | §5 S2, §11.1 |
| 🟠 中 | G4 | 工具执行（检索/搜索/代码）无子进度，仅静态label（P1） | §5 S4, §11.2 |
| 🟠 中 | G5 | 后端不可达时卡在"正在处理…"，~6s后横幅但streaming不复位 | §6.4, §11.3 |
| 🟡 低 | G6 | 首回合Kernel冷启动计入等待，无"初始化"提示 | §5 S3 |
| 🟡 低 | G7 | done后标题生成(≤20s)前端不消费 | §8 session_meta |
| 🟡 低 | G8 | 重复提交风险已由 streaming+submitLock 缓解（评估低），但依赖同步flush时序 | §11.4 |

---

## 10. 每项结论 → 证据/复现

| 结论 | 证据（类型） | 复现/定位 |
|---|---|---|
| 首可见反馈同tick(L1) | 代码 | `App.tsx:3316-3319` submit 即 `setStreaming(true)`+`setStreamPhase('正在处理…')` |
| 首token前无阶段变化(§3) | 代码+实测 | `handleStreamEvent` 仅事件驱动；实测8.26s无事件(§11.6) |
| 摘要阶段被过滤( G3) | 代码 | `turn_runtime.py:1683-1687` 过滤；`context_builder.py:276,217` 发 stage/progress |
| 重试不可见(G2) | 日志 | `lumen.jsonl` 5s/10s/20s 退避(§11.7) |
| 工具无子进度(G4) | 代码 | P1 `plugin.py:326-365` 仅 tool_call→tool_result |
| 连接失败不复位(G5) | 代码 | `ws.ts:226-238` onClose→onClose回调仅设 connectError；streaming 保持 |
| 空闲超时180s+ask_user豁免 | 代码 | `settings.ts:42`,`App.tsx:3082-3116` |
| done后标题生成≤20s | 代码 | `turn_runtime.py:2197,2330` |
| session_meta被忽略(G7) | 代码 | `App.tsx:3125` `if type in {session,session_meta} return` |

---

## 11. 关键证据（代码/日志摘录）

- 11.0 **实测首token窗口**：`ws://localhost:8001` 单回合逐步事件（§3）→ `MAX_SILENT_GAP=8.256s`。复现：重跑同一 `start_turn`。
- 11.1 上下文事件被过滤：[turn_runtime.py](file:///Users/xike/Documents/Docs/Lumen/lumen/runtime/session/turn_runtime.py#L1683-L1687) `if event.source in {"context","context_builder"}: return`；摘要会触发 [context_builder.py](file:///Users/xike/Documents/Docs/Lumen/lumen/runtime/session/context_builder.py#L426-L432) 的整轮 LLM。
- 11.2 P1 工具仅两端事件：[plugin.py](file:///Users/xike/Documents/Docs/Lumen/lumen/runtime/agent_loop/providers/langgraph_thin/plugin.py#L326-L365) `tool_call`→`execute`→`tool_result`，无子进度。
- 11.3 WS 连接失败处理：[ws.ts](file:///Users/xike/Documents/Docs/Lumen/frontend/src/api/ws.ts#L226-L238) 重连耗尽→onClose→仅 `setConnectError`，`streaming` 保持。
- 11.4 重复提交防护：[App.tsx](file:///Users/xike/Documents/Docs/Lumen/frontend/src/app/App.tsx#L3246) `if (submitLockRef.current||streaming) return`；Composer `canSend=…&&!streaming`。
- 11.5 空闲超时与 ask_user 豁免：[App.tsx](file:///Users/xike/Documents/Docs/Lumen/frontend/src/app/App.tsx#L3082-L3092)。

- 11.6 实测脚本（可复现）：对本机运行中后端发 `start_turn`，逐步打印各事件到达时刻。已用并删除对应临时脚本；等价步骤见 §3。**运行行为证据**。
- 11.7 运行日志（静默重试，带时戳）：`data/user/logs/lumen.jsonl`：
  - `00:02:06 LLM transient outage (attempt 1/2)` → `00:02:09 LLM transient error (attempt 1/9), retrying in 5.0s` → `00:02:14 …attempt 2/9…10.0s` → `00:02:24 …attempt 3/9…20.0s` → `00:02:44`（约 36s 仍失败）。
  - `agent_log loop round failed after 1 round(s); forcing finish: Request timed out.`（回合内超时）。
  这些重试期间后端不向 WS 推送任何事件 → 用户侧仅见静态阶段文案。**日志证据**。

---

## 12. T2｜Perceived Waiting State Model 所需事实输入（只给事实，不设计 T2）

1. **时刻基元**：request_submitted / first_visible_feedback / first_intermediate_state / first_value_token / turn_result / turn_done（对应 §3 实测时刻）。
2. **上游事件流**：`session`→(`thinking|stage_start|progress`? 注：P1 目前不发)→`content*`→`tool_call/tool_result`→`result`→`done`；以及被服务端过滤的 `context_builder` 事件（`summarize_context`/progress）——T2 需要其喂给监控的分发语义。
3. **阶段映射数据**：`TOOL_PHASE_LABELS / STAGE_PHASE_LABELS`（App.tsx §前端）与后端各 `stage`/`progress` 文案的对应关系；`event.stage="responding"` 字符串未被使用。
4. **计时/超时参数**：前端 `chatTimeout`（默认180s，范围30–1800，空闲型，非总时长）、WS 心跳30s/超时45s、重连≤5次指数退避、标题生成 `wait_for` 20s。
5. **静默区间的最小可观测单位**：S1(实测8.26s)、S2(≥1完整LLM轮)、S4(工具全程无子进度)、S5(退避5/10/20s级)、S6(≤20s)。
6. **"卡死"判定所需的反向事实**：※ LLM 静默重试不与前端事件对齐（后端在跑，前端无变化）；※ 连接失败后 `streaming` 不复位；※ ask_user 停顿应豁免于空闲超时。
7. **取消/重试事实**：停止→`cancel_turn`→error("Turn cancelled")+done；重试→`regenerate`(回退)。T2 需承载"取消后的残留流式件被保留"这一不变量。

---

*（审计至此结束，未实施任何修复。）*