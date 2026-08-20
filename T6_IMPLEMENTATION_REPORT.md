# T6 Implementation Report — Perceived Latency 最小必要工程改造

> 状态：**COMPLETE / READY FOR T7**（T6｜实施）
> 日期：2026-08-20 · 输入：冻结的 T1–T5（`PERCEIVED_LATENCY_SYSTEM_MAPPING_V1.md` 的 `W-I1–W-I8` 为实施边界）
> 范围：仅前端（`frontend/src/`）+ 前端测试；**不修改**任何后端生产代码、事件协议、T2 状态语义、T3 指标定义、T4 体验规范。
> 原则：所有用户可见反馈均来源于真实可观测事实；`G` 仍只由非空 `content` 进入；PIN 用户思考不计系统等待；transport 状态只由传输层真实事实置位。

---

## 0. 结论摘要

T5 冻结的 `W-I1–W-I8` 中 **6 项已实施（W-I1/I2/I3/I4/I5/I7）**，**2 项给出"不需要实施"结论（W-I6 / W-I8）**。T3 M1–M8 全部具备可靠采集所需的 instrumentation（§2）。前端新增确定性 P 状态机（可重放），`wait_for_input` 被正式消费，transport 状态（reconnecting/disconnected/recovered）按 T4 契约可见化。T4 §11.1 静态审查实现自动化并通过。代表性链路（正常生成/检索/工具/多步/PIN/静默重试/断线恢复/取消/超时/失败/完成）全部验证通过，seq 去重、终态竞态、重复提交无回归。

**验证基线**：
- 单元测试：`vitest run` → **42 passed / 0 failed**（状态机 T2 §12 T1–T12、指标 T3 §12 T1–T12、静态审查、tracker/buckets）
- e2e：前端相关 37 项全过（含新增 3 项 perceived instrumentation）+ 后端无关异常用例 X1/X6/X8 全过
- `tsc -b --noEmit` ✅ · `eslint src`（新增模块 0 error 0 warning）✅ · `vite build` ✅

---

## 1. 实际完成项（映射 W-I1–W-I8 → 实现）

### W-I1 · 前端感知时钟层 ✅
- 新增 [clock.ts](file:///Users/xike/Documents/Docs/Lumen/frontend/src/lib/perceived/clock.ts)：`performance.now()` 单调时钟 + 时钟可用性（`invalid(clock)` 依据，T3 §1/§7）。
- [ws.ts](file:///Users/xike/Documents/Docs/Lumen/frontend/src/api/ws.ts#L188-L202)：在 WS `onmessage` 边界以 `performance.now()` 记录每个事件**到达时刻**，挂到 `event.clientArrivalAt`（客户端专属、不回传服务端）。
- [App.tsx](file:///Users/xike/Documents/Docs/Lumen/frontend/src/app/App.tsx)：`submit`（t_submit）、`submit_user_reply`（t_ur）、`cancel`（t_cancel）、idle timer（t_TO）均记录客户端单调时刻。
- 时钟职责隔离：服务端 `timestamp`（B 平面诊断）与 `seq`（仅定序/去重）职责保持不混用（T2 §11.1 / T3 §1）。

### W-I2 · 决定性清洗 + T2 P 状态机推导 ✅
- 新增 [state.ts](file:///Users/xike/Documents/Docs/Lumen/frontend/src/lib/perceived/state.ts)：
  - `cleanDecisive`：T3 §11 CLEAN——seq 去重（I6）、终态闩锁（I1，终态后**全部**事件丢弃）、决定性白名单（`content(非空)/tool_call/sources/tool_result/wait_for_input/done/error`，T2 §5/§11.4）。
  - `deriveStateSequence`：T2 §2.1 转换表确定性推导；同刻终态先到者胜（I7，事件优先于用户动作，T9）；G 只由非空 content 进入（I2）；PIN 豁免 idle（I3/D6）；R/T 类属由最近 tool_call kind 决定（T2 §2.2）。
  - `replayTrace`：同一有序日志重放得到一致状态序列（I9）。
- 单元测试覆盖 T2 §12 T1–T12 全部轨迹 + 竞态 + 重放一致性（I9）。

### W-I3 · SYS_WAIT 记账 + 分桶 + baseline 数据结构 ✅
- 新增 [metrics.ts](file:///Users/xike/Documents/Docs/Lumen/frontend/src/lib/perceived/metrics.ts)：M1–M8 全部指标（T3 §3），SYS_WAIT 排除 PIN 用户思考 + disconnect 失联 + 终态后（T3 §4）；一致性断言 `M4−M4s == Σ_user + Σ_disc`（`invalid(overlap_error)`）；invalid 原因枚举（missing_ack/missing_decisive/no_value/overlap_error/…）。
- 新增 [buckets.ts](file:///Users/xike/Documents/Docs/Lumen/frontend/src/lib/perceived/buckets.ts)：维度五元组分桶（capability/tool_profile/outcome/transport/warmth + has_pin，T3 §6）、P50/P95/P99 线性分位（T3 §7）、min_n=30、invalid 单独计数、baseline JSON（schema 1.0，thresholds 全部 `CALIBRATION_PENDING`，T3 §9/§10）。
- 新增 [store.ts](file:///Users/xike/Documents/Docs/Lumen/frontend/src/lib/perceived/store.ts)：样本 JSONL 落 localStorage（上限 2000），`window.__perceivedLatency.dump()/stats()/clear()` 调试钩子（**T7 数据入口**）。

### W-I4 · PIN 显式消费 ✅
- [ws.ts](file:///Users/xike/Documents/Docs/Lumen/frontend/src/api/ws.ts#L3-L34)：类型集加入 `wait_for_input`。
- [App.tsx](file:///Users/xike/Documents/Docs/Lumen/frontend/src/app/App.tsx)：`handleStreamEvent` 消费 `wait_for_input` → 记录 t_wi、显式进入 PIN（无处理指示）；`handleAnswerQuestion` 记录 t_ur、退出 PIN；`failTurnIdle` 对 PIN 豁免保持不变。
- tracker 记录 `[t_wi, t_ur]` 用户思考区间 → M6p / Σ_user（T3 M6p / T4 §7）。

### W-I5 · 传输状态可见化 ✅
- [ws.ts](file:///Users/xike/Documents/Docs/Lumen/frontend/src/api/ws.ts#L261-L277)：`reconnecting`（seek 中）与 `disconnected`（重连耗尽）由**真实传输机制**置位并回调 `onTransportState`；`connected` 在 onopen 上报。仅心跳超时 / WS 断开 / 重连耗尽驱动，**禁止静默推断**（T4 §5.2 B7）。
- [App.tsx](file:///Users/xike/Documents/Docs/Lumen/frontend/src/app/App.tsx)：`reconnecting` 横幅（`data-testid="transport-reconnecting"`，`aria-live`）；`disconnected` 仍走既有 `connectError` 横幅；恢复后清除。
- tracker 消费 transport 事实并记录 `t_disc_detected / t_recovered / t_last_live` → M7a/b/c + Σ_disc（T3 §3.4）。

### W-I6 · 长静默升级（**不需要实施** — 明确结论）
- 依据：T4 C2/T3 §10 明令 `CALIBRATION_PENDING` 未填前不实现；T5 W-I6 明确门控"仅当 T3 采集满足 M5(P95) 有效样本后"。
- 现状：尚无真实采集（本阶段只建立采集能力），无校准 P95 阈值 → **不具备实施前提**。
- 现有 D1/D2（E1+E2 持续维持）与 A3（idle timer→TO 兜底）已满足 T4 §5.1 的允许项，无体验缺口需补。
- **结论：W-I6 不需要实施**（T7 校准 M5(P95) 后由 T7 回填 C2 时另行评估，届时可复用本阶段 W-I1–W-I3 的采集链路）。

### W-I7 · T4 静态审查自动化 ✅
- 新增 [review.ts](file:///Users/xike/Documents/Docs/Lumen/frontend/src/lib/perceived/review.ts)：T4 §11.1 九项检查（同 tick 首反馈、首反馈本地性 E1≠TTFD/M3、状态映射一致性、事件驱动、传输事实驱动、禁止模式 F1–F10 扫描、非破坏性、PIN 豁免、内容-状态分离）全部实现为确定性函数。
- App 通过 tracker 的 `recordFirstFeedback/recordProcessing/recordQuestionCard/recordContentRendered/recordErrorBlock/recordTimeoutBlock/recordTransportBanner/recordPhaseText` 采集真实 UI 观测，每回合样本携带 `review` 结果。
- 单元测试覆盖 PASS 与各 FAIL 触发路径。

### W-I8 · P1 seam 补发 thinking/progress 文案级事件（**不需要实施** — 明确结论）
- 依据：T5 §4-W2 明确"按 T4 §5.1 A2 属**允许项而非必须项**"；T4 A2 只影响文案升级，不改变 P 状态语义。
- 现状：`S` 内 E1+E2 静态"正在处理…"已满足 D1/D2；`thinking/progress` 属文案级、不推进 P（T2 §7）。
- 实施需改后端 P1 adapter（新增事件发射），属"无关重构 + 范围扩张"，且无语义必要性。
- **结论：W-I8 不需要实施**。文案级事件前端分支（`deriveThinkingPhase` 的 thinking/progress/stage 分支）保持可用，未来若 T4 A2 被判定为必须，可零协议变更地在 P1 seam 补发。

### 附 · 文案回退噪声消除（completion #9 / T4 D5）
- [App.tsx](file:///Users/xike/Documents/Docs/Lumen/frontend/src/app/App.tsx#L1637-L1672) `deriveThinkingPhase`：`result`/空 `content`/`wait_for_input` 不再回退为"正在处理…"（T2 §6 映射噪声），改为继续向前扫描保持既有阶段文案。

---

## 2. T3 M1–M8 可采集性（completion #2）

| 指标 | 采集能力（T6 落地） |
|---|---|
| M1 TTA | `session` 到达时刻（tracker.onEvent）− t_submit；缺失→`invalid(missing_ack)` |
| M2 TTFD | 首个决定性到达 − t_submit |
| M3 TTFMR | 首个非空 content 到达 − t_submit；缺失→`invalid(no_value)` |
| M4 / M4s | `τ_terminal − t_submit`；M4s 扣 Σ_user（PIN 显式区间）+ Σ_disc（transport 显式区间） |
| M5 Max Silent | 决定性到达间隔（leading/internal/trailing），仅完全落在 SYS_WAIT 视图（无 PIN/disconnect 遮蔽） |
| M6 S/R/T/G | 由确定性状态机分段时间 × SYS_WAIT |
| M6p PIN | `Σ(t_ur−t_wi)`（t_wi 消费 wait_for_input，t_ur 记录 submit_user_reply） |
| M7 a/b/c | `t_last_live`/`t_disc_detected`/`t_recovered` + 失联终止标记 |
| M8 ok/er/ca/to + t2 | 终态到达/动作时刻 + 触发前静默段 |

全部指标由纯函数计算（可重放），样本写入 JSONL（T3 §9 schema v1.0）。

---

## 3. 未实施项及原因（completion #16）

| 项 | 原因 |
|---|---|
| W-I6 长静默升级 | `CALIBRATION_PENDING`（T4 C2 / T3 §10）：无校准 M5(P95) 阈值，不具备实施前提 |
| W-I8 P1 seam 补发文案级事件 | T4 A2 允许但非必须（T5 §4-W2）；现有 E1+E2 已满足 D1/D2；实施需改后端、无语义必要性 |
| T11 断线下新 submit 先 CA 路径 | 保持 T5 已确认边界（G-TR1 附注）：现 App 用 submitLock 拦截为更严格子集，I5/I10 安全，不属 T6 必须 |

---

## 4. 验证证据（completion #15）

1. **单元测试**（`npm run test:unit`，vitest，42 passed）：
   - [state.test.ts](file:///Users/xike/Documents/Docs/Lumen/frontend/tests/unit/state.test.ts)：T2 §12 T1–T12 状态序列、seq 去重（I6）、终态闩锁（I1）、同刻竞态（T9/T10）、重放一致（I9）、tool profile。
   - [metrics.test.ts](file:///Users/xike/Documents/Docs/Lumen/frontend/tests/unit/metrics.test.ts)：T3 §12 T1–T12 数值、SYS_WAIT 一致性 `M4−M4s=Σ_user+Σ_disc`。
   - [review.test.ts](file:///Users/xike/Documents/Docs/Lumen/frontend/tests/unit/review.test.ts)：T4 §11.1 九项 PASS/FAIL。
   - [tracker.test.ts](file:///Users/xike/Documents/Docs/Lumen/frontend/tests/unit/tracker.test.ts)：端到端 sample、PIN、断线、cancel、无终态丢弃、分位/聚合/baseline。
2. **e2e**（Playwright）：新增 [perceived.spec.ts](file:///Users/xike/Documents/Docs/Lumen/frontend/tests/perceived.spec.ts) 3 项（PIN 卡 + 无处理指示 + 样本落库；正常完成；reconnecting 横幅真实驱动）全过；既有前端 34 项全过（无回归）；后端无关异常用例 X1/X6/X8 全过。
3. **静态**：`tsc -b --noEmit`、`eslint src`（新增模块 0 error/0 warning）、`vite build` 全部通过。
4. **可复现实验**：`window.__perceivedLatency.dump()/stats()` 可在浏览器控制台导出 T7 所需样本。

---

## 5. 遗留风险

| 风险 | 说明 | 处置 |
|---|---|---|
| `performance.now` 不可用环境 | 极罕见（现代浏览器均支持）；回退 `Date.now` 并标记时钟不可用 | `clock.ts` `usable` 标志 + 样本 `invalid(clock)` 路径（T3 §7） |
| M7a 检测滞后以最后决定性/事件到达近似 | 心跳 pong 在 ws 层被过滤，未计入 `t_last_live` | T3 允许"决定性/心跳事件时刻"近似；T7 如需精确可在 ws 层暴露心跳时间戳 |
| 样本仅存 localStorage | 单浏览器本地，多端不聚合 | 作为 T7 数据入口的最小方案；后续可加导出/上报（不改本阶段边界） |
| 并发进程修改了若干后端文件 | 本会话期间检测到 `lumen/cert/tutor.py`、`orchestrator.py`、`plugin.py`、`provider_runtime.py` 等被并发修改 | 与本阶段无关，未触碰、未回退；建议人工确认来源 |

---

## 6. T7 所需数据入口与前置条件（completion #16）

1. **数据入口**：前端 `localStorage['lumen:perceived-samples-v1']`（JSONL，schema v1.0），每行一个 `TurnSample`（含 dimensions、metrics、invalid、review）。导出：浏览器控制台 `window.__perceivedLatency.dump()`（baseline JSON）或 `stats()`（汇总）。
2. **采集前提（已就绪）**：W-I1–W-I5 已落地，真实回合正常产生样本。
3. **T7 待执行（本阶段明确不实施）**：
   - 真实采集足够样本（每桶 ≥ min_n=30，T3 §7）后回填 C1–C4 阈值；
   - 冻结 M3/M4s/M5/M7b 的 P50/P95/P99 baseline（T3 §9）；
   - 依据 M5(P95) 校准结果评估 W-I6 长静默升级；
   - 按 T3 §10 PASS/WARN/FAIL 框架执行最终体验验收。
4. **边界**：T7 任何阈值不得凭空设定；先采集后校准，校准前保持 `CALIBRATION_PENDING`（T3 §10 / T4 §3.3）。

---

## 7. 完成标准核对

| 完成标准 | 落实 |
|---|---|
| ① W-I1–W-I8 全完成或"不需要实施"结论 | §1（6 实施 + 2 结论） |
| ② M1–M8 可靠采集 instrumentation | §2 |
| ③ 客户端 monotonic clock 统一；服务端 timestamp/seq 隔离 | W-I1；`clientArrivalAt` 客户端专属，`seq` 仅定序 |
| ④ 前端确定性表示并重放 P 状态 | W-I2 + 单元测试（I9） |
| ⑤ wait_for_input 正式消费并进出 PIN | W-I4 |
| ⑥ reconnecting/disconnected/recovered 按 T4 契约表现 | W-I5 + e2e |
| ⑦ 真实事件完整贯通、不伪造状态 | 全链路采样；无计时器驱动假推进（T2 I3） |
| ⑧ G1/G2/G5 闭环；G3/G4/G6/G7/G8 保持边界 | §1（G1→M3/M5、G2→M5 观测、G5→W-I5；G3/G4/G6/G7/G8 未改动） |
| ⑨ 文案回退/映射噪声消除 | §1 附 |
| ⑩ 代表性链路验证 | 单元 T1–T12 + e2e |
| ⑪ seq/resume/终态竞态/重复提交无回归 | cleanDecisive I1/I6 + T9/T10 + 既有 e2e 全过 |
| ⑫ 同一轨迹重放一致 | replayTrace + 一致性测试 |
| ⑬ T4 静态审查全过、禁止模式无命中 | W-I7 + review.test |
| ⑭ instrumentation 无显著性能影响 | 纯函数、样本数组小、localStorage 上限 2000；build 体积增量可忽略 |
| ⑮ 测试/证据证明生效 | §4 |
| ⑯ T6 Implementation Report | 本文档 |
| ⑰ T6 标记 COMPLETE / READY FOR T7 | 见下 |

**T6 结论**：**COMPLETE / READY FOR T7**。全部必要工程 Gap 已闭环或给出明确结论，验证通过；未进入 T7 的阈值校准、baseline 冻结或最终体验验收。
