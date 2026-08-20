# Perceived Latency Integration Gap / System Mapping v1（感知等待集成缺口 / 系统映射 v1）

> 状态：**FROZEN BASELINE**（T5｜感知等待集成缺口 / 系统映射，可作为 T6｜实施阶段的缺口基线）
> 冻结标记：`FROZEN_BASELINE = "t5-perceived-latency-integration-gap-system-mapping-v1"`（验收见 §15）
> 日期：2026-08-20 · 输入：冻结的 T1 `PERCEIVED_LATENCY_GAP_AUDIT.md`（G1–G8 / S1–S6）+ 冻结的 T2 `PERCEIVED_WAITING_STATE_MODEL_V1.md` + 冻结的 T3 `PERCEIVED_LATENCY_METRICS_V1.md` + 冻结的 T4 `WAITING_EXPERIENCE_DESIGN_SPEC_V1.md`
> 依据：当前真实代码（带行号）、运行链路（WS/TurnRuntime/Agent Loop/LLM/Tool）、冻结的 T1 真实运行测量与日志（§3：8.256s 静默；§11.7：退避 5/10/20s）
> 关系：**只引用** T1/T2/T3/T4 已冻结语义，不修改任何状态语义 / 指标定义 / 体验规范；只建立真实系统能力与缺口基线，**不实施修复**

---

## 0. 范围、方法与证据基准（不破坏冻结基线）

本文档回答一个问题：**Lumen 当前端到端感知等待相关运行链路，相对已冻结的 T2 状态机 / T3 指标契约 / T4 体验规范，哪些能力已实现、哪些存在但未贯通、哪些真正缺失**，并给出后续实施阶段的最小工程工作清单。它**不**设计解决方案、不实施 UI、不改变事件协议、不新增 instrumentation。

- **证据基准（非设计文档推断）**：
  1. 代码事实（本文件 §2–§8 均给出 `file:line` 可追溯位置）；
  2. 冻结的 T1 真实运行测量（单回合 `session`(13ms)→静默 8.256s→`content` 逐 token→`done`(10s)，T1 §3/§11.6）；
  3. 冻结的 T1 运行日志（LLM 静默退避 `attempt 1/9…5.0s→10.0s→20.0s`，T1 §11.7）。
  4. 本阶段未新增任何运行实验（T5 为映射基线；T1 的测量与日志已是冻结的真实证据，且本文件逐项确认当前代码仍与 T1 描述一致）。
- **生产 Provider 事实**：`runtime.agent_loop` 生产默认 = **P1 `agent_loop.langgraph_thin`**（[profile.py](file:///Users/xike/Documents/Docs/Lumen/lumen/profile.py#L54-L68) `PRODUCTION_PROFILE.bindings={"runtime.agent_loop":"agent_loop.langgraph_thin"}`）；Legacy(P0) shadowed。因此**本映射以 P1 生产路径为准**，Legacy 仅作为对照（其独有能力标注为"仅 legacy，生产未触发"）。
- **能力分类（贯穿全文）**：已实现 / 已存在但未接通 / 部分实现 / 缺失 / 按冻结设计明确不需要实现。

> **一致性红线**：凡"首反馈 / 首有效结果 / 静默窗口 / 状态切换 / 终态"的映射，必须与 T2 状态机、T3 指标边界、T4 体验规范逐一对齐；识别到的任何"生产路径缺失"是**缺口基线**，不是本阶段要修复的缺陷。

---

## 1. 端到端真实运行链路映射（完成标准 #1）

```
[Frontend] user submit ──► handleSend (App.tsx L3244)
   │ 同 tick：setStreaming(true)+setStreamPhase('正在处理…') (L3316-3317)  [E1]
   │ wsRef.send({type:'start_turn', ...}) (L3321-3338)
   ▼
[Transport] UnifiedWSClient.send (ws.ts L180) ──(WS /api/v1/ws)──►
[Server] unified_websocket (unified_ws.py L50)
   │ start_turn ──► TurnRuntimeManager.start_turn (turn_runtime.py L692)
   │    └─► 持久化 session/turn ──► _publish_live_event SESSION (L868-875) [M1 终点]
   │    └─► create_task(_run_turn) (L878)
   ▼
[TurnRuntime] _run_turn (L1479)
   │ ContextBuilder.build ──► _emit_context_event 过滤 source∈{context,context_builder} (L1683-1687)  [S2 隐藏]
   │   ├─ 上下文构建 / 可选 LLM 摘要 (context_builder._summarize L182)  [静默]
   │   └─ Kernel/agent_loop 按需装配 (L1978 _resolve_agent_loop_service)  [S3 冷启动]
   │ _iter_agent_turn(L1408) / _iter_learn_turn(L1351) ──► StreamBus 生命周期
   ▼
[Agent Loop] P1 langgraph_thin adapter (plugin.py L493 run)
   │ _RealLumenModel.generate (L113) ──► OpenAI 兼容流式 (engine/client)
   │    └─ 每 chunk ──► stream.content(...) (L158-166)   [content 事件，首个非空→G]
   │ _RealLumenToolRuntime.execute (L326) ──► stream.tool_call / tool_result (L330/L341/L351/L359)  [R/T]
   │    └─ ask_user 暂停 ──► stream.emit(WAIT_FOR_INPUT) (L304-315)  [PIN]
   │ 终止协议：result + done (L680-687)；失败→error+done (L593-605/L633-647)
   ▼
[LLM] shared/_util/llm ──► OpenAI 兼容 HTTP（cloud_provider.py / local_provider.py）
   │ 静默指数退避重试（settings.py retry.max_retries=8, factory.py L27-29）  [S5 静默，无 bus 事件]
   ▼
[Tool / Retrieval] runtime.tools (ToolService.execute)
   │ builtin 工具返回 ToolResult（file_tools/rag/web_fetch/web_search…）
   │ 事件由 agent loop seam 发（工具自身不发事件）
   ▼
[Response / Terminal] turn_runtime 主循环 (L1986-2005)
   │ 事件 publish（_publish_live_event L2217，seq 分配 L2229-2238）
   │ done 延迟至尾段统一发（pending_done_event L1990-1992 → L2088）
   │ 终态：done(completed)→OK；error(failed,turn_terminal)→ER；cancel→CA；idle timer→TO
   │ done 后 session_meta 标题 (L2090-2103 → L2248 _maybe_generate_session_title)
   ▼
[Transport back] subscribe_turn (L1162) 重放/去重/合成终态  ──WS──► 前端 onmessage (ws.ts L155)
   ▼
[Frontend] handleStreamEvent (App.tsx L3118) ──► deriveThinkingPhase (L1628) / eventsToBlocks (sessions.ts L250)
   │ 渲染：无可见块→处理指示（L1872-1879）；有内容→renderBlock 真实内容（L1857-1868）
   │ done → setStreaming(false)（E5）；error → 尾部错误块（E6）；question → QuizAnswerCard（E8）
```

**链路结论**：当前端到端**事件通道完整贯通**（submit → session → content* → tool_call/tool_result → done/error），且 seq 去重 / resume 重放 / 终态闩锁 / 前端非破坏渲染全部真实存在。**缺口不在"通道"而在"信号丰富度与度量层"**（详见 §4–§7）。

---

## 2. 当前真实事件 → T2 P 状态（完成标准 #2 前半）

> 依据 T2 §5/§11.4 决定性白名单；对每个事件标注五态：**生产 / 传输 / 过滤 / 消费 / 终态行为**。

| 事件 `type` | 决定性（T2） | P 映射 | 生产（谁发） | 传输 | 过滤 | 前端消费 | 终态行为 |
|---|---|---|---|---|---|---|---|
| `session` | 否（非决定性） | 停留 `S` 入口 | **已实现**：turn_runtime L868-875 | ✅ | — | 取 turnId 后 return（App L3125） | — |
| `content`(非空) | 是 | →`G`（唯一来源） | **已实现**：P1 `_RealLumenModel` L158-166 逐 chunk | ✅ | — | **已消费**：eventsToBlocks 拼接（sessions L289-294） | 首个非空→G；之后维持 G |
| `content`(空) | 否 | 维持 | P1 不产生（generate 过滤空 text，L158-160） | — | — | — | 无 |
| `thinking` | 否（文案级） | 维持 `S` 文案 | **缺失（生产未触发）**：仅 legacy（agent_loop.py L673/L700）、labeled_step（L220-264）、notebook analysis（被过滤） | — | — | 前端分支存在但**死分支**（deriveThinkingPhase L1649） | 无 |
| `stage_start`/`stage_end` | 否（文案级） | 增强文案、不迁移 | **缺失（生产未触发）**：context_builder 发（source="context_builder"，L276/L340）但被 turn_runtime **过滤**（L1684-1685）；notebook analysis 同 | — | **后端已产生但被过滤** | 前端 `STAGE_PHASE_LABELS` 分支存在但生产不触发 | 无 |
| `progress` | 否（文案级） | 增强文案 | **部分实现**：P1 仅发空文案 narration 标记（L218-228）与终止警告（L627-632） | ✅ | — | deriveThinkingPhase 支持（L1637-1640） | 空文案→"正在处理…"（噪声，无可见影响） |
| `tool_call` | 是 | 检索类→`R`；其余→`T` | **已实现**：P1 `_RealLumenToolRuntime` L330-336 | ✅ | — | **已消费**：deriveThinkingPhase→`TOOL_PHASE_LABELS`（L1632-1634） | 决定 R/T 类属（T2 §2.2） |
| `tool_result` | 是（确认性） | 确认/保留 `R/T` | **已实现**：P1 L341-364 | ✅ | — | **已消费**：→"正在分析结果…"（L1635） | 不改变类属 |
| `sources` | 是 | →`R` | **缺失（生产未触发）**：仅 legacy（agentic_pipeline L1019、agent_loop L241）；P1 从不发 | — | — | deriveThinkingPhase 分支存在（L1636）但生产不触发 | 无 |
| `result` | 否 | 不推进 | **已实现**：P1 L680 | ✅ | — | eventsToBlocks 追加文本（sessions L295-298）；deriveThinkingPhase 无分支→回退文案（噪声，T2 §6 已记） | 紧邻 done |
| `wait_for_input` | 是（终态-暂停） | →`PIN` | **已实现**：P1 L304-315（ask_user 暂停） | ✅ | — | **已传输但前端未消费**：前端类型集不含它（ws.ts L3-18），PIN 由 `tool_call.args.questions` 推断（sessions L265-287） | PIN；idle 豁免（App L3088-3092） |
| `error` | 终态 | →`ER`(failed)/`CA`(cancelled)/`TO` | **已实现**：P1 L593-605/L633-647；turn_runtime 取消 L2110-2113 / 异常 L2169-2175 | ✅ | — | **已消费**：eventsToBlocks 尾部 status 块（sessions L311-317）；streaming=false（App L3139-3142） | 终态闩锁（I1） |
| `done` | 终态 | →`OK`(completed)/`CA`/`ER` | **已实现**：P1 L681-687；turn_runtime L2088（合成/补 status） | ✅ | — | **已消费**：setStreaming(false)、重建 blocks（App L3126-3133） | 终态闩锁 |
| `session_meta` | 否（终态后） | 已是 OK，不推进 | **已实现**：turn_runtime L2355（done 后标题） | ✅ | — | **已传输但前端忽略**（App L3125）——**按设计正确**（T2 G7/T4 §4.6） | 无 |

> 传输层事实（`connected/reconnecting/disconnected`）**不产生事件**：纯前端 WS 客户端内部状态（ws.ts L131-238），服务端不推送、也不作为 WS 事件存在（见 §4-TR1）。这与 T2 §1.2 一致（传输覆盖正交、非事件）。

### 2.1 P 状态 ←→ 当前系统对应关系（完成标准 #2 后半）

| T2 P 状态 | 当前系统是否可达 | 如何到达（真实代码） | 用户可见反馈（现状） |
|---|---|---|---|
| `idle` ℐ | ✅ | 无在途 Turn；`streaming==false`（App L2890） | 可发送、无指示 |
| `S` starting | ✅ | `handleSend` submit（L3316-3317）；`submitLockRef||streaming` 守卫（L3246） | 处理指示 + 文案（L1872-1879） |
| `R` retrieving | ✅（经 tool_call 类属） | P1 tool_call(rag/kb_files/read_source)（L330）→ deriveThinkingPhase（L1632-1634） | "正在检索资料…/正在阅读资料…" |
| `T` tooling | ✅ | P1 tool_call(非检索)（L330）→ deriveThinkingPhase | "正在联网搜索…/正在运行代码…" 等 |
| `G` generating | ✅ | 首个非空 content（P1 L158-166）→ eventsToBlocks 产生文本块 → showAnswer=true（L1857） | 真实流式内容为主（renderBlock）；处理指示消失 |
| `PIN` paused_input | ✅（间接） | ask_user tool_call（args.questions）→ question 块（sessions L265-287）→ QuizAnswerCard（App L1496） | 答题卡片；无处理指示（showAnswer 因 question 块为真） |
| `OK` completed | ✅ | done(completed)（P1 L681 / turn_runtime L2088）→ App L3126-3133 | 停止流式、保留内容 |
| `ER` failed | ✅ | error(failed,turn_terminal)（P1 L593-605/L633-647；turn_runtime L2169-2175） | 尾部错误块（非破坏） |
| `CA` cancelled | ✅ | 用户 cancel（App L3454-3459）→ turn_runtime L1115-1131 → error("Turn cancelled")+done(cancelled)（L2110-2122） | 停止、保留已渲染内容 |
| `TO` timeout | ✅ | 前端 idle timer（App L3113-3116 failTurnIdle，chatTimeout 默认 180s，settings L42-45） | 非破坏超时块（L3098-3102） |

> **关键观察**：前端**没有显式的 T2 P 状态机实现**——`streaming:boolean + streamPhase:string + showAnswer(是否有可见块)` 是"隐式状态"（派生自事件与块渲染），与 T2 状态机**近似等价但非一等公民**。对用户可见语义（R/T/G/PIN/终态）当前映射正确，但**无法直接支撑 T3 的 M6（time_in S/R/T/G）与确定性重放校验**（见 §6-W1）。

---

## 3. T4 E1–E8 ↔ 当前前端 / UI 能力（完成标准 #3）

| T4 反馈元素 | 当前能力 | 实现位置 | 分类 | 说明 |
|---|---|---|---|---|
| **E1 即时活动指示** | ✅ 同 tick | `handleSend` L3316-3317（`setStreaming(true)`+`setStreamPhase('正在处理…')`，与 send 同批渲染）；渲染 L1872-1879（`.agent-processing` + `aria-live=polite`） | 已实现 | 本地即时反馈，非决定性事件（T4 §4.1）；**满足 D1** |
| **E2 状态文案** | ✅ | `deriveThinkingPhase`（L1628-1653）+ `setStreamPhase`（L3135） | 已实现 | 由事件驱动；thinking/progress/stage 文案分支存在但生产多不触发（§4-W2/W3） |
| **E3 阶段/工具指示** | ✅ | `TOOL_PHASE_LABELS`（L1598-1609）由 tool_call 驱动（L1632-1634） | 已实现 | 工具名粒度；子步骤隐藏（T4 §6.1 符合） |
| **E4 流式内容** | ✅ | eventsToBlocks content 拼接（sessions L289-294）+ renderBlock text（L1548-1549） | 已实现 | 首个非空 content 即显示；**G 唯一来源正确** |
| **E5 终态结果** | ✅ | done → setStreaming(false)、重建 blocks（App L3126-3133） | 已实现 | 停止流式、保留内容、清指示 |
| **E6 终态异常块** | ✅ | error → eventsToBlocks 尾部 status 块（sessions L311-317）+ renderBlock status（L1565-1571）；TO 块（App L3098-3102）；CA 保留流式件 | 已实现 | 非破坏（尾部追加）符合 D7/P6 |
| **E7 传输覆盖提示** | ⚠️ 部分 | 仅重连**耗尽后** `onClose` → `setConnectError(STREAM_CONNECT_ERROR)` 横幅（App L3171/L3188、L3674-3676）；**无 `reconnecting` 状态暴露**、无断开→重连→恢复的状态机 UI | 部分实现 | 见 §4-TR1：`connected/reconnecting/disconnected` 为 ws.ts 内部态，未映射到 UI 层 |
| **E8 暂停态卡片** | ✅ | question 块（sessions L265-287）+ `QuizAnswerCard`（App L1496-1544） | 已实现 | 无处理指示；idle 豁免（App L3088-3092）符合 D6/P5 |

> T4 §4.5（G 中 E1/E2 降级为次要角标）现状 = 处理指示**整体消失**（showAnswer=true 后不再渲染 L1872），真实内容为主——满足"不再显示大号正在处理…块"；"边角生成中角标"为 T4 的示例性可选项，不强制。

---

## 4. 关键事件 / 能力逐项核查（完成标准 #5、#6、#7）

> 核查结论统一使用五态区分：**后端没有产生 / 后端已产生但被过滤 / 已传输但前端未消费 / 前端已支持但生产链路未触发 / 已完整贯通**。

### W1 · `content`（已完整贯通 ✅）
- 生产：P1 `_RealLumenModel.generate` 逐 chunk `stream.content`（[plugin.py](file:///Users/xike/Documents/Docs/Lumen/lumen/runtime/agent_loop/providers/langgraph_thin/plugin.py#L158-L166)）；最终轮无工具时该文本即答案（L238-239），不重复 emit（L613-618）。
- 传输/消费：`eventsToBlocks` 拼接（[sessions.ts](file:///Users/xike/Documents/Docs/Lumen/frontend/src/app/sessions.ts#L289-L294)），空 content 被 `shouldAppendEventContent` 过滤。
- 终态：首个非空→G（T2 I2）；与 T1 实测一致（`content` 8.269s 为首 token）。

### W2 · `thinking`（前端已支持但生产链路未触发 ⚠️）
- 生产：**P1 从不发射**。全仓唯一发射点 = legacy 引擎（[agent_loop.py](file:///Users/xike/Documents/Docs/Lumen/lumen/runtime/agent_loop/providers/legacy/agent_loop.py#L673-L700)）、engine `labeled_step.py`（L220-264，legacy 专属）、notebook `analysis_agent.py`（L118，context 通道被过滤）。
- 前端：`deriveThinkingPhase` 有 `thinking → '正在思考…'` 分支（App L1649）——**死分支**。
- 结论：T2 §5 已记载（"P1 不发射 thinking"）。对 T4：`S` 内文案升级（A2）在 P1 下实际只停留在静态"正在处理…"。**不改变协议即可解决**（P1 seam 可选发射），但**按 T4 §5.1 A2 属允许项而非必须项**。

### W3 · `stage_start` / `stage_end`（后端已产生但被过滤 ⚠️）
- 生产：context_builder `_summarize` 发 `STAGE_START/END` + `progress`（[context_builder.py](file:///Users/xike/Documents/Docs/Lumen/lumen/runtime/session/context_builder.py#L214-L282)），source=`"context_builder"` → 被 turn_runtime `_emit_context_event` **过滤**（[turn_runtime.py](file:///Users/xike/Documents/Docs/Lumen/lumen/runtime/session/turn_runtime.py#L1683-L1687)）。
- 前端：`STAGE_PHASE_LABELS` 分支存在（App L1614-1622、L1641-1648）——生产不触发。
- 结论：P1 主路径无 stage 事件；T2 §4 已把摘要阶段并入 `S` 合法隐藏（G3/S2）。**按 T4 设计允许**（摘要并入 S 合法静默）；若未来要"告知正在摘要"才需放开过滤。

### W4 · `progress`（部分实现 ⚠️）
- 生产：P1 仅两处——(a) 工具轮前文 narration 标记 `progress("")`（[plugin.py](file:///Users/xike/Documents/Docs/Lumen/lumen/runtime/agent_loop/providers/langgraph_thin/plugin.py#L217-L228)，空文案，仅让 turn_runtime 排除持久化）；(b) 终止警告 `progress("Turn stopped: …")`（L627-632）。context_builder 的 progress 被过滤（同 W3）。
- 前端：`deriveThinkingPhase` 支持 progress（L1637-1640）。
- 结论：T1 §8 "progress 能力闲置"在 P1 下仍然成立（生产几乎不发）。对 T4：**A2 允许但非必须**。

### W5 · `tool_call` / `tool_result`（已完整贯通 ✅）
- 生产：P1 `_RealLumenToolRuntime.execute`（[plugin.py](file:///Users/xike/Documents/Docs/Lumen/lumen/runtime/agent_loop/providers/langgraph_thin/plugin.py#L326-L365)）tool_call→execute→tool_result，含失败路径（L339-344）与 ask_user 暂停路径（L346-357）。工具自身不产事件。
- 前端：`TOOL_PHASE_LABELS` 驱动 E3（App L1598-1609/L1632-1634）；`tool_result`→"正在分析结果…"（L1635）。
- 终态：R/T 类属由最近 tool_call kind 决定（T2 §2.2）——前端文案与其一致；**无子进度（T4 G4/S4 符合，禁子进度）**。
- 注意：检索工具（rag/kb_files/read_source）通过 tool_call 到达 R 是通的；但 `sources` 事件驱动的 R（T2 §5）在 P1 下**从不触发**（见 W6）。

### W6 · `sources`（后端没有产生 ⚠️）
- 生产：**P1 从不发射**。全仓唯一发射点 = legacy（[agentic_pipeline.py](file:///Users/xike/Documents/Docs/Lumen/lumen/runtime/agent_loop/providers/legacy/agentic_pipeline.py#L1019)、[agent_loop.py](file:///Users/xike/Documents/Docs/Lumen/lumen/runtime/agent_loop/providers/legacy/agent_loop.py#L241)）。`artifact_attachments`（[artifact_attachments.py](file:///Users/xike/Documents/Docs/Lumen/lumen/runtime/session/artifact_attachments.py#L54-L84)）读取 SOURCES 仅对 legacy 生效。
- 前端：`deriveThinkingPhase` 有 `sources → '正在检索资料…'`（L1636）——生产不触发。
- 结论：T2 §5 将 `sources` 列为决定性→R 的白名单事件，但 P1 生产路径不产生。**R 状态仍可达（经检索 tool_call）**，故 P 状态映射不受影响；`sources` 的"来源列表呈现/artifact 聚合"能力在 P1 下未贯通。若 T6 需要来源展示或生成文件卡片，需在 P1 端补齐（事件协议缺口 / 生产未产生）。

### W7 · `wait_for_input`（已传输但前端未消费 ⚠️）
- 生产：P1 ask_user 暂停时 `stream.emit(WAIT_FOR_INPUT)`（[plugin.py](file:///Users/xike/Documents/Docs/Lumen/lumen/runtime/agent_loop/providers/langgraph_thin/plugin.py#L302-L315)）；`bus.wait_for_input` 亦存在（[bus.py](file:///Users/xike/Documents/Docs/Lumen/lumen/runtime/stream/bus.py#L278-L314)）。
- 传输：✅ 事件上 wire（unified_ws `submit_user_reply` 透传 [unified_ws.py](file:///Users/xike/Documents/Docs/Lumen/lumen/app/api/routers/unified_ws.py#L242-L276)）。
- 前端：**类型集不含 `wait_for_input`**（[ws.ts](file:///Users/xike/Documents/Docs/Lumen/frontend/src/api/ws.ts#L3-L18)）；PIN 由 `tool_call.args.questions` 推断（sessions L265-287）。
- 结论：与 T2 §1.1 PIN 注记完全一致（"事件本身未消费"）。**PIN 语义功能可用**（question 卡 + idle 豁免），但 (a) 前端无显式 PIN 状态（影响 T3 M6p 的 `t_wi/t_ur` 采集与 T4 §7 的显式语义）；(b) 若 T6 要按 T2 §8"断线时 PIN 等重连恢复"的精确语义，需消费该事件。

### W8 · `error` / `done` / `cancel` / `TO`（已完整贯通 ✅）
- 终态链路全部真实存在（见 §2.1）；`_synthesize_done/error`（turn_runtime L1261-1309）为订阅恢复路径的兜底，保证前端 `streaming` 必然复位。

### TR1 · `transport`（connected/reconnecting/disconnected）（部分实现 ⚠️）
- 现状：`UnifiedWSClient` 内部持有（[ws.ts](file:///Users/xike/Documents/Docs/Lumen/frontend/src/api/ws.ts#L131-L238)）：心跳 30s / 超时 45s（L98-99）、重连 ≤5 次指数退避 base 200ms（L100-101）、`attemptReconnect`（L226-238）、onopen 时 `resume_from`（L146-152）、onmessage 时 seq 去重（L162）。服务端对 `ping` 回 `pong`（unified_ws L146-152）。
- 缺口：**`reconnecting` 状态未暴露给 UI**（App 仅在耗尽后 `onClose` 出 `connectError` 横幅，L3171/L3188）；`disconnected` 无显式时间戳记录（影响 T3 M7a 的 `t_disc_detected`，见 §6）；服务端不推送连接状态事件（T2 §1.2 本就定义传输态为客户端持有，故不属协议缺口，属**前端消费/暴露缺口**）。
- 对照 T4 E7：断线/重连提示目前只有"耗尽后红色横幅"（由真实传输机制驱动 ✅），但**缺少"重连中"的中间提示**与"恢复后清除"的完整状态机；`streaming` 在断线期间保持（T2 I8 正确），需 idle timer 兜底（已存在）。

### L1 · LLM 层（静默重试，按设计隐藏 ✅ / 但 instrumentation 缺失）
- 生产：`shared/_util/llm`（[factory.py](file:///Users/xike/Documents/Docs/Lumen/lumen/shared/_util/llm/factory.py#L27-L29)、[settings.py](file:///Users/xike/Documents/Docs/Lumen/lumen/shared/_util/llm/settings.py#L22-L33)）指数退避重试（默认 max_retries=8），发生在 HTTP 客户端层，**不向 bus 发任何事件**。
- 结论：T1 §11.7 日志（5/10/20s 退避）与当前代码一致；T2 §8 S5 / T4 B4 明令**隐藏**（不暴露重试次数/退避）——**设计正确，无需修改**。但该静默对 T3 M5（max silent gap）的观测需要**决定性事件到达间隔**才能度量（见 §6）。

---

## 5. 能力存在但未贯通 / 真正缺失 / 应继续隐藏（完成标准 #6、#7、#8）

### 5.1 能力已存在但未贯通（及证据）

| # | 能力 | 类型 | 现状 | 证据 |
|---|---|---|---|---|
| U1 | `thinking` 事件 | 前端已支持但生产未触发 | P1 从不发射；前端分支为死分支 | §4-W2；App L1649；plugin.py 无 thinking |
| U2 | `progress` 事件 | 生产几乎不发（能力闲置） | P1 仅 narration 空标记 + 终止警告 | §4-W4；T1 §8 |
| U3 | `stage_start/stage_end` + `stage` | 后端已产生但被过滤 | context_builder 发→turn_runtime 过滤 | §4-W3；turn_runtime L1683-1687 |
| U4 | `sources` 事件（→R 白名单） | 后端没有产生 | 仅 legacy 发；P1 不发 | §4-W6；agentic_pipeline L1019 |
| U5 | `wait_for_input` 事件 | 已传输但前端未消费 | 前端类型集不含；PIN 从 question 推断 | §4-W7；ws.ts L3-18 |
| U6 | `reconnecting/disconnected` 传输态 | 前端内部态未暴露到 UI | 无重连中提示、无 disconnected 时间戳 | §4-TR1；ws.ts L131-238；App L3171 |
| U7 | `session_meta`（标题） | 已传输但前端忽略 | 按 T2 G7/T4 §4.6 **设计正确**，不计缺口 | App L3125；turn_runtime L2248 |
| U8 | `result` 空 content 文案回退 | 已完整贯通但映射噪声 | `deriveThinkingPhase` 无 result 分支→回退"正在处理…"（瞬间，无可见影响，因紧邻 done） | T2 §6；App L1628-1653 |

### 5.2 真正缺失、必须新增的工程能力

| # | 缺失能力 | 所属层级 | 为什么必须 | 依赖 |
|---|---|---|---|---|
| N1 | **感知时钟层（instrumentation）** | Frontend | T3 全部指标以客户端单调时钟为唯一基准（T3 §1）；现前端 `Date.now()` 仅做心跳、无 `performance.now` 到达时刻 | T3 §1/§2 |
| N2 | **决定性事件清洗 + T2 P 状态机推导** | Frontend | T3 M5/M6/M4s 与可重放校验需要决定性白名单清洗与确定性状态段推导；现前端只有隐式派生 | T2 §2.1/§5/§11.4；T3 §3.2-3.3 |
| N3 | **SYS_WAIT 记账 + 分桶聚合 + baseline 归档** | Frontend/收集器 | T3 §4–§9 的排除规则、维度五元组、P50/P95/P99、min_n、invalid 原因 | T3 §4–§9 |
| N4 | **PIN 显式消费（`wait_for_input` + `t_wi/t_ur`）** | Frontend（消费缺口）/ 事件协议 | T3 M6p 与 T4 §7 的显式 PIN 语义；现为 question 推断 | T2 §8；T4 §7；T3 M6p |
| N5 | **传输状态可见化（reconnecting/disconnected → E7 状态机）** | Frontend | T4 E7 要求断线/重连提示由传输层真实事实驱动且有完整状态（含"重连中"）；现只有耗尽后横幅 | T2 §1.2/I8；T4 E7/§9 |
| N6 | **长静默升级提示（T4 §5.3，C2 校准后）** | Frontend（体验） | T4 §5.3：超过 P95 后温和提示"仍在处理、可停止/重试"；`CALIBRATION_PENDING` 未填前不实现 | T3 M5(P95)；T4 C2 |
| N7 | **T4 §11.1 静态审查自动化** | Frontend（测试/工程） | 同 tick 首反馈、首反馈本地性、传输事实驱动为 T4 立即生效的验收项，现无自动化检查 | T4 §11.1 |

### 5.3 按 T2/T4 设计原则应继续隐藏（不应实现用户可见反馈）

| 隐藏项 | 依据 | 现状 |
|---|---|---|
| 上下文摘要内部 / 摘要阶段细节 | T2 §4 S2 / §7；T4 G3（并入 S 合法静默） | 已被过滤 ✅ |
| Kernel/agent_loop 冷启动细节 | T2 §4 S3 / G6 | 无事件 ✅ |
| LLM 重试次数 / 退避时长 / provider / 模型名 | T2 §7；T4 B4/F6 | 无事件 ✅ |
| token 计数 / 工具参数 / 工具返回值原文 / 调用轮次 | T4 §6.3 信息暴露边界 | tool_call 只带工具名 + args（args 前端不渲染）✅ |
| `seq` / 恢复机制 / 队列内部 | T2 §7；T4 §6.3 | 前端不显示 seq ✅ |
| 标题生成（session_meta） | T2 G7；T4 §4.6 | 前端忽略 ✅ |
| 检索子调用 / top-k / 分块 / embedding 细节 | T4 §6.1（R 仅工具名粒度） | 不产生 ✅ |
| 伪 ETA / 伪进度 / 无依据百分比 | T4 F1/F3/F5 | 现前端无任何 ETA/进度条实现 ✅（**无需修改**） |

---

## 6. T3 M1–M8 可采集性矩阵（完成标准 #4）

> 结论先行：**当前无任何感知延迟 instrumentation 可"直接采集"**——T3 要求的事件到达时刻、动作/计时器时刻、决定性清洗、状态段推导、SYS_WAIT 记账在代码中均不存在（已验证：前端无 `performance.now` 到达时刻；后端事件 `timestamp` 为服务端时钟，按 T2 I11/T3 §1 不属感知口径；`turn_events` 持久化的是服务端 `timestamp+seq`，仅可用于 B 平面诊断与重放，不可作感知指标）。

| 指标 | 定义（T3） | 当前可采集性 | 需补的 instrumentation | 当前无法可靠计算的原因 |
|---|---|---|---|---|
| **M1** TTA | `a(session)−t_submit` | ⚠️ 需补 | `onmessage` 到达时刻 + `t_submit` | 无客户端单调时钟层 |
| **M2** TTFD | `a(e_0)−t_submit`（首决定性） | ⚠️ 需补 | 决定性白名单分类 + 到达时刻 | 同上 |
| **M3** TTFMR | `a(content_first_nonempty)−t_submit` | ⚠️ 需补 | 首非空 content 到达时刻 | 同上 |
| **M4** Total | `τ_terminal − t_submit` | ⚠️ 需补 | 终态到达时刻（done/error/cancel/timer） | 同上 |
| **M4s** System Perceived | `M4 − Σ_user − Σ_disc` | ❌ 需补 | PIN 段 `[t_wi,t_ur]` + disconnect 段记录 | 依赖 N4（PIN 消费）与 N5（disconnect 时间戳） |
| **M5** Max Silent Gap | 决定性到达间隔（仅系统等待区） | ⚠️ 需补 | 决定性序列 + 断线/PIN 遮蔽判定 | 依赖 N2/N4/N5 |
| **M6** Time in S/R/T/G | 状态段 `SYS_WAIT` 累计 | ❌ 需补 | 显式 T2 状态机推导（N2） | 前端无状态机 |
| **M6p** Time in PIN | `Σ(t_ur_k − t_wi_k)` | ❌ 需补 | `wait_for_input` 消费 + reply 时刻（N4） | 事件未消费 |
| **M7** Disconnect（a/b/c） | 检测滞后/失联时长/失联终止 | ❌ 需补 | `t_last_live`/`t_disc_detected`/`t_recovered`（N5） | ws.ts 无显式时间戳 |
| **M8** Timeout/Cancel/Failure | `τ_TO`/`t_cancel`/`t_error` | ⚠️ 需补 | idle timer 触发时刻、cancel 动作时刻 | 无动作时刻记录 |

**结论**：M1–M8 **全部**需要补 instrumentation（无一可直接采集）。M4s/M6/M6p/M7 还额外依赖前端对 PIN 与 disconnect 的**显式建模**（N4/N5），仅靠纯事件时间戳无法可靠计算。这属于 T3 的"采集实现"范畴，按 T3 §1/§15 明确标注为**实施阶段（T6+）工作**，本阶段不落地。

---

## 7. Gap 汇总（完成标准 #10、#11）

### 7.1 按层级 / 类型分类的 Gap

| Gap | 类型 | 严重度 | 影响范围 | 层级 | 证据 |
|---|---|---|---|---|---|
| G-TR1 断线/重连无 UI 状态（reconnecting 未暴露；仅耗尽后横幅） | transport 缺口 + 前端消费缺口 | 🔴 高 | 断线场景下用户无"重连中"反馈；与 T4 E7 完整状态机有差距；另：断线下新 submit 被守卫拦截（T2 §2.4"先 CA 再新 S"路径未实现，用户需等 TO/停止才能重发） | Frontend/Transport | ws.ts L131-238；App L3171/L3188；§9 I5/I10 行 |
| G-INS1 T3 instrumentation 全缺（到达/动作/计时器时刻） | instrumentation 缺口 | 🔴 高 | M1–M8 全部不可采集；T4 C1–C4 无数据回填；baseline 无法建立 | Frontend（+收集器） | 全仓无 `performance.now` 感知时钟（§6） |
| G-INS2 无显式 T2 P 状态机（前端） | instrumentation 缺口（采集前提） | 🟠 中 | M6/M5/M4s 与可重放校验不可行；T4 §9 决策表无落地载体 | Frontend | App L1628-1653（隐式派生） |
| G-PIN1 `wait_for_input` 未消费 | 事件协议缺口 + 前端消费缺口 | 🟠 中 | PIN 语义功能可用但非显式；M6p 不可采；T2 §8 精确语义（断线等重连）缺载体 | Frontend/WS 协议 | ws.ts L3-18；plugin.py L302-315 |
| G-P1 `thinking`/`stage_start`/`progress`/`sources` 生产路径不发射/被过滤 | 事件协议缺口（信号丰富度） | 🟡 低（T4 允许） | 用户可见文案升级（T4 A2）受限；`sources`→R 白名单事件在 P1 缺失 | Agent Loop/ContextBuilder | §4-W2/W3/W4/W6 |
| G-EXP1 长静默升级提示缺失（T4 §5.3） | 体验缺口 | 🟡 低（`CALIBRATION_PENDING`） | P95 后无"仍在处理/可停止"提示 | Frontend | T4 C2；当前无实现 |
| G-EXP2 `G` 态"生成中"角标缺失 | 体验缺口 | 🟡 低（T4 示例项） | 进入 G 后处理指示整体消失，无次要角标 | Frontend | App L1872-1879 |
| G-N1 `result` 空 content 文案回退 | 体验缺口（映射噪声） | 🟢 极低（瞬间，无可见影响） | `deriveThinkingPhase` 回退"正在处理…"（紧邻 done） | Frontend | T2 §6；App L1628-1653 |

### 7.2 明确"无需修改"结论（完成标准 #9 后半 / #8）

| 项 | 结论 | 依据 |
|---|---|---|
| `content`/`tool_call`/`tool_result`/`error`/`done`/`cancel`/`TO` 终态链路 | ✅ 已完整贯通，无需修改 | §2.1/§4-W1/W5/W8 |
| 摘要过滤（G3/S2）、冷启动（G6/S3）、重试隐藏（G2/S5） | ✅ 按 T4 设计允许隐藏，无需修改 | §5.3 |
| 工具无子进度（G4/S4） | ✅ 符合 T4 §6.1（禁子进度），无需修改 | §4-W5 |
| 标题生成忽略（G7/S6） | ✅ 按 T4 §4.6 设计正确，无需修改 | §4-U7 |
| 重复提交防护（G8） | ✅ 已实现，无需修改 | App L3246；T2 I5/I10 |
| 伪 ETA/伪进度 | ✅ 现状无任何实现，天然合规（T4 F1/F3/F5） | §5.3 |

---

## 8. G1–G8 / S1–S6 → 真实工程位置追溯（完成标准 #9）

| 项 | 真实工程位置 | 缺口结论 | 无需修改 / 需新增 |
|---|---|---|---|
| **G1 / S1** 首 token 静默 | P1 `_RealLumenModel` 首个 content 前无任何事件（[plugin.py](file:///Users/xike/Documents/Docs/Lumen/lumen/runtime/agent_loop/providers/langgraph_thin/plugin.py#L113-L166)）；前端保持 E1+E2（App L1872-1879）；T1 实测 8.256s（T1 §3） | 合法静默并入 `S`（T2 §4）；体验上无长静默升级提示 | M3 采集需 N1/N2（G-INS1/2）；长静默升级为 G-EXP1（N6） |
| **G2 / S5** LLM 静默重试 | `shared/_util/llm` 指数退避（[factory.py](file:///Users/xike/Documents/Docs/Lumen/lumen/shared/_util/llm/factory.py#L27-L29)）；无 bus 事件；T1 §11.7 日志 | 按 T4 B4/F5 合法隐藏；idle timer 兜底已存在 | 无需修改（隐藏正确）；M5 需 N1/N2 观测 |
| **G3 / S2** 摘要被过滤 | context_builder 发（[context_builder.py](file:///Users/xike/Documents/Docs/Lumen/lumen/runtime/session/context_builder.py#L214-L282)）→ turn_runtime 过滤（[turn_runtime.py](file:///Users/xike/Documents/Docs/Lumen/lumen/runtime/session/turn_runtime.py#L1683-L1687)） | 按 T4 允许（并入 S 合法静默） | 无需修改；若未来告知用户需放开过滤（G-P1） |
| **G4 / S4** 工具无子进度 | P1 仅 tool_call/tool_result（[plugin.py](file:///Users/xike/Documents/Docs/Lumen/lumen/runtime/agent_loop/providers/langgraph_thin/plugin.py#L326-L365)）；前端仅工具名（App L1598-1609） | 符合 T4 §6.1（禁子进度） | 无需修改 |
| **G5** 断线不复位 | ws.ts 心跳/重连（[ws.ts](file:///Users/xike/Documents/Docs/Lumen/frontend/src/api/ws.ts#L131-L238)）；耗尽后 `onClose`→横幅（App L3171）；`streaming` 保持 | T2 I8 正确（P 不终结）；但**无重连中 UI、无 disconnected 时间戳** | G-TR1（N5）需新增；TO 兜底已存在 |
| **G6 / S3** 冷启动 | turn_runtime `_resolve_agent_loop_service`（L1978）+ Kernel 装配；无事件 | 并入 S 合法静默（T2 §4） | 无需修改 |
| **G7 / S6** 标题生成 | turn_runtime `_maybe_generate_session_title`（[turn_runtime.py](file:///Users/xike/Documents/Docs/Lumen/lumen/runtime/session/turn_runtime.py#L2248)）→ session_meta（L2355）；前端忽略（App L3125） | 按 T2 G7/T4 §4.6 设计正确 | 无需修改 |
| **G8** 重复提交 | App `submitLockRef||streaming` 守卫（[App.tsx](file:///Users/xike/Documents/Docs/Lumen/frontend/src/app/App.tsx#L3244-L3246)）；Composer `canSend`（L2054） | 已实现；T2 I5/I10 满足 | 无需修改 |

=> **G1–G8、S1–S6 全部映射到真实工程位置，无遗漏**；其中 5 项（G3/G4/G6/G7/G8）明确"无需修改"，3 项（G1/G2/G5）为"合法隐藏 + 度量/可见化需新增"。

---

## 9. 关键不变量 / T4 禁止模式 vs 现状核对

| T2 不变量 / T4 禁止模式 | 现状核对 | 结论 |
|---|---|---|
| I1 终态不可变 | done/error 后 `streaming=false`；`subscribe_turn` 合成终态 | ✅ 一致 |
| I2 真因推进（G 仅由非空 content） | 前端 `showAnswer` 由文本块触发；`thinking` 不产生可见块 | ✅ 一致 |
| I3 无假进度（计时器仅产 TO） | idle timer→`failTurnIdle` 仅追加超时块 + cancel | ✅ 一致 |
| I5/I10 单 Turn、至多一活跃 | `submitLockRef` + `streaming` 守卫（App L3246）保证不并行；但 **T2 §2.4 的"断线下新 submit → 先把旧 Turn 判 CA 再进新 S"路径未实现**——断线期间 `streaming` 保持 true，新 submit 被守卫直接拦截，用户只能等 idle timer（TO）或点停止后才能重新发送（对不变量安全，但缺 T2 §2.4 定义的"新 submit 强制旧 CA"便捷路径） | ✅ 不变量一致；行为为 T2 §2.4 的**更严格子集**（安全但少一条便捷路径，记入 G-TR1 附注） |
| I6 seq 单调去重 | 服务端 seq 分配（turn_runtime L2229-2238）+ `subscribe_turn` 去重（L1182-1238）+ 前端 lastSeq（ws.ts L162） | ✅ 一致 |
| I7 终态互斥先到者胜 | done 处理在 error 前分支；idle timer 与后端终态由 `streaming` 状态互斥 | ✅ 一致 |
| I8 传输非终态 | 断线时 `streaming` 保持、P 不终结 | ✅ 一致 |
| F1/F3/F5 伪进度/伪 ETA/动画掩盖 | 现前端无任何进度条/ETA/加速转圈 | ✅ 天然合规 |
| F4 无意义阶段轮换 | 无计时器驱动阶段切换 | ✅ 合规 |
| F7 "思考中"冒充生成 | `thinking` 不产可见块；无"正在思考"覆盖内容 | ✅ 合规 |
| F8 用户思考表现为系统处理 | `failTurnIdle` 对 question 块豁免（App L3088-3092）；PIN 无处理指示 | ✅ 合规 |
| F9 破坏性终态 | error/TO/cancel 均尾部追加、保留已见内容 | ✅ 合规 |
| F10 超时与后端终态并存 | TO 先到者胜（`streaming` 置 false 后 send 被 `submitLock`/`streaming` 拦截） | ✅ 一致 |

> 前端无显式状态机但**行为上与 T2 不变量一致**（隐式派生 + 非破坏渲染）；唯一的精确语义差距在 §4-W7（PIN 未显式建模）与 §4-TR1（断线无显式时间戳/UI），二者均已列入 §7 Gap。

---

## 10. 后续实施阶段的最小工程工作清单（完成标准 #12）

> 只定义"缺什么、必须达到什么"，不规定具体实现方案；全部在 T6+ 实施，本阶段不落地。

| # | 工作项 | 必须达到的验收标准（引用冻结契约） |
|---|---|---|
| W-I1 | 前端感知时钟层 | 在 WS `onmessage` 边界以 `performance.now()` 记录每个事件到达时刻；`submit`/`cancel`/`submit_user_reply`/idle timer 触发均记录客户端单调时刻；非单调/缺失→样本 `invalid(clock)`（T3 §1/§7） |
| W-I2 | 决定性清洗 + P 状态机推导 | 实现 T2 §5/§11.4 决定性白名单清洗 + T2 §2.1 状态机确定性推导；同一有序日志重放得到一致状态序列（T2 I9；T3 §11） |
| W-I3 | SYS_WAIT 记账 + 分桶 + baseline | 实现 T3 §4 排除（PIN 用户思考、disconnect 失联、终态后）；§5 场景桶；§6 维度五元组；§7 P50/P95/P99 + min_n + invalid 分布；§9 baseline JSON 结构（schema 版本化） |
| W-I4 | PIN 显式消费 | 前端类型集加入 `wait_for_input`；显式进入/离开 `PIN`；记录 `t_wi/t_ur`；满足 T4 §7（PIN 无处理指示、idle 豁免）与 T3 M6p |
| W-I5 | 传输状态可见化 | `reconnecting/disconnected/connected` 暴露为 UI 可消费状态；E7 提示只由传输层真实事实驱动（心跳超时/WS 断开/重连耗尽），禁止静默推断（T4 E7/§5.2 B7/§9）；记录 `t_last_live/t_disc_detected/t_recovered`（T3 M7a/b） |
| W-I6 | 长静默升级（校准后） | 仅当 T3 采集满足 `M5(P95)` 有效样本后，实现 T4 §5.3 温和升级提示；`CALIBRATION_PENDING` 未填前不实现（T4 C2） |
| W-I7 | T4 静态审查自动化 | 实现 T4 §11.1 静态审查项自动化：同 tick 首反馈、首反馈本地性（E1≠TTFD/M2/M3）、传输事实驱动、禁止模式扫描 F1–F10、非破坏性、PIN 豁免、内容-状态分离 |
| W-I8 | （可选，信号丰富度）P1 seam 补发 thinking/progress 文案级事件 | 仅当 T4 A2"文案温和升级"被判定为必须时；不改变任何 P 状态语义（T2 §7 文案级事件不迁移） |

> **依赖关系**：W-I1/I2/I3 是 T3 采集与 baseline 的前提；W-I4/I5 是 M6p/M7/M4s 与 T4 E7 精确语义的前提；W-I6 依赖 W-I3 的 P95 数据；W-I7 可在 W-I1-I5 之后随 UI 一并验收。**T2/T4 的"隐藏项"（§5.3）一律不进入本清单。**

---

## 11. 与 T1/T2/T3/T4 的一致性对照（完成标准 #8）

| 冻结契约 | 本映射引用 | 一致性 |
|---|---|---|
| T2 状态集合/转换表/白名单/不变量 I1–I11 | §2/§4/§9 | 逐项核对：当前系统行为与不变量一致；前端为隐式派生、行为等价 |
| T2 三平面/三条时间轴 | §6（感知时钟=客户端） | 一致；当前无感知时钟层（属缺口 N1，非语义冲突） |
| T3 M1–M8/SYS_WAIT/分桶/分位 | §6 采集性矩阵 | 只引用不修改；明确全部需补 instrumentation |
| T4 E1–E8/D1–D7/P1–P7/禁止模式/验收框架 | §3/§5/§9/§10 | E1–E6/E8 已实现；E7 部分实现（G-TR1）；D1–D7 行为一致 |
| T1 G1–G8/S1–S6 | §8 | 全部映射到真实工程位置，无遗漏 |

=> **与 T1/T2/T3/T4 完全一致，无新增语义矛盾。**

---

## 12. 验收框架自评（对照 T4 §11 / T3 §10）

| T4 §11.1 静态审查项 | 当前系统 |
|---|---|
| 同 tick 首反馈（E1） | ✅ 通过（App L3316-3317） |
| 首反馈本地性（E1≠TTFD/M2/M3） | ✅ 通过（E1 为本地 ack，不产生/不缩短任何指标；指标采集本就不存在） |
| 状态映射一致性（无新增 P 状态/无合并冲突） | ✅ 通过（前端隐式状态与 T2 状态集一致） |
| 事件驱动性（升级可回溯决定性事件） | ✅ 通过（tool_call/content 驱动 E3/E4） |
| 传输事实驱动（断线只由传输层真实机制） | ✅ 通过（`connectError` 仅由重连耗尽触发；无静默推断）——但**状态机不完整**（G-TR1，无 reconnecting/disconnected 显式建模） |
| 禁止模式扫描 F1–F10 | ✅ 通过（无任何进度/ETA/伪阶段实现） |
| 非破坏性（ER/CA/TO 尾部追加） | ✅ 通过（sessions L311-317；App L3098-3107） |
| PIN 豁免 | ✅ 通过（App L3088-3092） |
| 内容-状态分离 | ✅ 通过（showAnswer 后处理指示消失） |

> 静态审查项**全部通过**。T3 度量项（档位边界/长静默升级/超时安抚/断线可见化）因 instrumentation 与数据缺失保持 `CALIBRATION_PENDING`（按 T3 §10 校准前不判 FAIL）。

---

## 13. 输出交付边界（完成标准 #12/#13）

- **本阶段交付**：真实系统映射（§1）、事件↔P 状态（§2）、E1–E8↔UI（§3）、M1–M8 采集性矩阵（§6）、Gap 汇总（§7）、G1–G8/S1–S6 追溯（§8）、最小工程工作清单（§10）、验收自评（§12）。
- **明确不在此阶段交付**：任何 instrumentation 实现、UI 改动、事件协议变更、生产代码修改。

---

## 14. 后续实施阶段输入契约（T6 输入边界）

本映射输出给 T6（实施）的契约：

1. **缺口基线清单**（§7）：7 类 Gap，含严重度 / 影响范围 / 层级 / 证据，分类为体验 / 事件协议 / instrumentation / transport / 前端消费。
2. **最小工程工作清单**（§10）：W-I1–W-I8，每项带"必须达到"的冻结契约验收标准。
3. **无需修改结论**（§7.2/§8）：G3/G4/G6/G7/G8 与全部隐藏项（§5.3）不得被 T6 无谓改动。
4. **采集前提**（§6）：T3 M1–M8 全部待 instrumentation；T6 必须先落地 W-I1–W-I5 方可采集与建立 baseline。

> **边界规则**：T6 任何改变等待语义的改动必须先通过 T4 §11 验收框架；度量项以 T3 baseline 复测。本阶段**不进入 T6**（见 §15）。

---

## 15. 修正验收与 FROZEN BASELINE 声明

> 完成标准逐项核验，全部通过后正式冻结本 T5。

| 完成标准 | 落实 |
|---|---|
| ① 端到端感知等待相关运行链路真实系统映射 | §1（Frontend→WS→TurnRuntime→Agent Loop→LLM→Tool/Retrieval→Response/Terminal 全链路，带行号） |
| ② T2 全部状态与当前事件/模块对应 | §2.1（S/R/T/G/PIN/OK/ER/CA/TO 全部可达且证据充分） |
| ③ T4 E1–E8 与当前前端/UI 能力对应 | §3（E1–E6/E8 已实现；E7 部分实现） |
| ④ T3 M1–M8 可采集性矩阵 | §6（可直接采集=0；需补 instrumentation=M1–M8 全部；当前无法可靠计算=M4s/M6/M6p/M7） |
| ⑤ 关键事件生产/传输/过滤/消费/终态逐项确认 | §4 W1–W8/TR1/L1 |
| ⑥ "能力已存在但未贯通"位置及证据 | §5.1 U1–U8 |
| ⑦ 真正缺失必须新增的工程能力 | §5.2 N1–N7 |
| ⑧ 按 T2/T4 应继续隐藏的内部能力 | §5.3（摘要/冷启动/重试/模型名/token/seq/标题/检索细节/伪 ETA） |
| ⑨ G1–G8 / S1–S6 全部映射到真实工程位置 | §8（无遗漏；5 项无需修改、3 项合法隐藏+度量/可见化需新增） |
| ⑩ 每项 Gap 严重度/影响范围/层级/证据 | §7.1 |
| ⑪ 区分体验/事件协议/instrumentation/transport/前端消费缺口 | §7.1 类型列 |
| ⑫ 最小工程工作清单（只定义缺什么/必须达到什么） | §10 W-I1–W-I8（不规定实现方案） |
| ⑬ T5 PASS / FAIL 验收结论 | 见下 |
| ⑭ 全部通过后标记 FROZEN BASELINE | 见下 |

**T5 验收结论（完成标准 #13）**：
- **PASS（作为系统映射与缺口基线）**。理由：
  1. 系统映射完整：全链路（§1）、事件→P 状态（§2）、E1–E8（§3）、M1–M8（§6）均基于当前真实代码（带行号）与冻结的 T1 真实测量/日志，证据充分；
  2. G1–G8/S1–S6 全部映射到真实工程位置，无遗漏（§8）；
  3. 所有 Gap 可追溯：7 类 Gap 均带严重度/影响范围/层级/证据（§7.1）；最小工程工作清单已定义"缺什么/必须达到什么"（§10）；
  4. T4 §11.1 静态审查项全部通过（§12）；T3 度量项 `CALIBRATION_PENDING`（校准前不判 FAIL，符合 T3 §10）。
- **同时明确**（作为 T6 的输入，不影响 T5 PASS）：存在 7 类必须由 T6 处理的缺口（§7），其中 **T3 instrumentation（M1–M8 全部）为最大空白**，PIN 显式消费（W-I4）与传输状态可见化（W-I5）为精确满足 T4 E7 / T2 §8 语义的必要条件。

**FROZEN BASELINE 声明**：上述 14 项完成标准全部通过。**T5 per `PERCEIVED_LATENCY_SYSTEM_MAPPING_V1.md` 正式标记为 `FROZEN BASELINE`**（`FROZEN_BASELINE = "t5-perceived-latency-integration-gap-system-mapping-v1"`）。**不实施修复 / 不进入 UI / 事件协议 / instrumentation 的实际改造阶段**（T6+），仅交付冻结的系统映射与缺口基线。

——
