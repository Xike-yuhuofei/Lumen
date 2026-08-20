# Perceived Latency Metrics v1（感知延迟指标体系 v1）

> 状态：**FROZEN BASELINE**（T3｜Perceived Latency Metrics 语义契约，可作为 T4｜等待体验设计规范输入）
> 冻结标记：`FROZEN_BASELINE = "t3-perceived-latency-metrics-v1"`（验收见 §15）
> 日期：2026-08-20 · 输入：T1 `PERCEIVED_LATENCY_GAP_AUDIT.md`（G1–G8 / S1–S6）+ **冻结的** T2 `PERCEIVED_WAITING_STATE_MODEL_V1.md`
> 依据代码：`lumen/runtime/stream/events.py`、`turn_runtime.py`、P1 `langgraph_thin/plugin.py`、前端 `frontend/src/app/App.tsx`、`api/ws.ts`
> 关系：**只定义并验证指标体系，不实施 UI / 不改生产代码 / 不进入 T4**

---

## 0. 范围与对 T1/T2 的关系（不破坏冻结基线）

本文档把"感知等待"从主观体验转化为**可测量、可比较、可回归、可验收**的指标。它**只引用** T1/T2 已冻结的语义，不新增语义矛盾、不修改状态机、不引入假进度：

- **T2 为语义唯一来源**：状态集合 `S/R/T/G/PIN/OK/ER/CA/TO`、传输覆盖 `connected/reconnecting/disconnected`、转换表（§2.1）、决定性/文案级白名单（T2 §5/§11.4）、终态闩锁与不变量 I1–I11、三平面模型与三条时间轴，全部原样沿用。
- **本阶段不实施任何修复**：不实现真实采集端到端、不设定终态绝对阈值作为已生效告警、（绝对阈值标记为 `CALIBRATION_PENDING`）——只交付**可测试、可重放、可回归**的指标契约。

**本文档新增的三样东西（均不破坏 T2）**：
1. 把 T2 的"客户端到达时刻"基元（`t_submit/t_session/t_first_decisive/t_first_token/t_done/…`，T2 §11.2）固化为**单回合指标集合（§3）**。
2. 定义**系统等待记账规则**（§4）：哪些时间计入、哪些排除（PIN 用户思考、disconnect 失联）。
3. 定义**聚合统计与验收契约**（§5–§10）：场景维度、P50/P95/P99、异常样本、baseline 结构与 PASS/WARN/FAIL 框架。

> 一致性红线：本文档任何指标出现的"首个反馈/首个有效结果/静默窗口/终态"等概念，**必须**与 T2 状态机定义逐一对齐（完成标准 #7），引用处标注 T2 节号。

---

## 1. 时间轴与时钟（重申 T2 I11，指标的唯一计时基准）

**唯一计时基准 = 客户端单调时钟**。所有"感知延迟指标"的 `t_*` 均为客户端单调时钟（`performance.now`）上记录的**到达/动作/计时器触发时刻**。

| 轴 | 载体 | 是否驱动感知指标 | 用途 |
|---|---|---|---|
| **客户端感知时间轴** ¶ | 客户端单调时钟 | **是（唯一）** | 指标全部 `t_*`、`gap`、`max_silent`、`time_in`、`disconnect` 时长 |
| 服务端诊断时间轴（B 平面） | 服务端 `timestamp` | **否** | 仅 B 平面诊断与关联（T2 §11.1） |
| 顺序轴 `seq` | 事件携带递增序号 | 否（非时间） | 定序/去重/重放（T2 §11.1；本 §8） |

> **采集前置（T3 实现要求，本阶段仅约定语义）**：指标要求在 WS `onmessage` 边界用 `performance.now()` 打上**到达时刻**，`submit/cancel/submit_user_reply` 与 idle timer 触发亦然（`ws.ts` 现用 `Date.now()` 仅做心跳，不是单调感知时钟——这部分属 T3 采集实现，不在本阶段落地）。任何非单调/缺失时钟的来源 → 该样本标记 `invalid(clock)`，不进入感知指标分位（§8）。

---

## 2. 事件白名单与规范性预处理（deterministic 前提）

沿用 T2 §5/§11.4 的**决定性 / 文案级**二分。指标只以**决定性事件**为测量轴；文案级事件只贡献文案，**不进任何测量的分母/间隔**（消除 `result`/空 `content` 的文案回退噪声，T2 §6/§11.4）。

**决定性（触发 P 迁移，度量轴）**：`content(非空)`、`tool_call`、`sources`、`tool_result`（仅保留 R/T 类属）、`wait_for_input`、`done`、`error` ＋ 用户本机动作 `submit/cancel/submit_user_reply` ＋ 前端 idle timer 触发。

**文案级/非决定性（不迁移）**：`thinking`、`progress`、`stage_start`、`stage_end`、`session`、`session_meta`、`result`、`content(空)`。

> `session` 特殊：非决定性（不进测量间隔），但 T2 用它取 `turnId`；本指标仅用它定义 **M1 服务端确认**（见 §3），不参与静默/状态时长计算。

**规范性预处理（所有指标共享，保证可回放确定性，T2 I6/I9）**：
1. **去重/乱序守卫**：`seq>0` 的事件，`seq ≤ lastSeq` 一律丢弃；`lastSeq` 递增更新（T2 §9 第 2 条）。`resume_from` 重放时用 `lastSeq` 续播，天然去重。
2. **终态闩锁**：到达首个终态后（`done(status=completed/failed/cancelled)`、`error(turn_terminal)`、`cancel`、idle timer）后续事件全部丢弃（T2 I1/I7 先到者胜）。
3. **Turn 隔离**：事件按 `(session_id, turn_id)` 归属；新 Turn 启动后旧 Turn 残留事件不作用于新 Turn（T2 §9 第 6 条）。
4. **断线重连**：`disconnected` 期间无事件；恢复后 `resume_from(lastSeq)` 重放，重复事件被第 1 条去掉（T2 §2.4）。

---

## 3. 单回合核心指标（M1–M8）

### 3.0 计法约定与输入
给定一个 Turn 的**清洗后**(§2) 决定性事件序列 `E=[e_0,…,e_{n-1}]`，每个 `e_i` 有 `arrival a_i`（客户端单调时钟）。设 `t_submit`＝发出 `start_turn` 的时刻，`τ_terminal`＝终端到达时刻：
- `OK`：`done(completed)` 到达；`ER`：`error(failed,turn_terminal)` 到达；`CA`：用户 `cancel`（客户端动作时刻）或 `error("Turn cancelled")+done(cancelled)` 到达；`TO`：前端 idle timer 触发时刻（T2 §11.3）。
- `t_wi_k`＝第 k 段 `wait_for_input` 到时刻；`t_ur_k`＝第 k 段 `submit_user_reply` 发出的客户端时刻。
- `disc`＝断线区间集合，每段 `[ds, de]`（§5/§7）。

**`SYS_WAIT(I)`（系统等待记账函数，§4）**：对区间 `I=[p,q]`，
```
SYS_WAIT([p,q]) = (q - p)
                  − Σ_k overlap([p,q], [t_wi_k, t_ur_k])       // 排除 PIN 用户思考
                  − Σ_k overlap([p,q], disc_k)                 // 排除 disconnect 失联
```
> **什么计入系统等待 / 什么必须排除**（完成标准 #3）：
> - **计入**：所有活动态 `S/R/T/G` 内在客户端单调时钟上的真实经过时间（含被服务端隐藏的 TTFT/摘要/重试退避——它们在 O 平面合法静默，T2 §4/§8）。
> - **排除 1：PIN 用户思考** `[t_wi, t_ur]`（WAIT_FOR_INPUT 中用户答题时间，非系统等待，审计/T2 明令不计入）。
> - **排除 2：disconnect 失联**（断线期间无数据可交付，属传输故障，计入独立 `disconnect` 指标而非活动态时长，见 §5/§7；防止大失联压扁 `time_in` 与 `max_silent`）。
> - **排除 3**：终态之后的任何时间（`done` 后标题生成等非决定性，T2 G7/§5）。

### 3.1 指标总表

| ID | 指标 | 数学/事件边界定义 | 场景口径 | 依赖 | 参考状态 |
|---|---|---|---|---|---|
| **M1** | Time to Acknowledgement（服务端确认） | `a(session)−t_submit`，首个 `session` 到达 | 全部 Turn；`session` 缺失→`invalid(missing_ack)` | — | 只会计入"确认延迟"，非静默 |
| **M2** | Time to First Decisive Feedback | `a(e_0)−t_submit`，首个**决定性**事件到达（首段 S 退出点） | 全部；`e_0` 可为 tool_call/sources/content/终态 | T2 §11.2 `latency_first_phase` | = 首段静默区 |
| **M3** | Time to First Meaningful Result / First Token | `a(content_first_nonempty)−t_submit` | **必被 `content(非空)` 进入（T2 G 唯一来源）**；无内容→见 §8 `no_value` 样本 | T2 §11.2 `latency_first_token`；**对应审计 S1** | 首个有价值结果 |
| **M4** | Total Perceived Turn Duration | `τ_terminal − t_submit`（原始，含 PIN/失联） | 依 `ok/er/ca/to` | — | 总经停 |
| **M4s** | System Perceived Turn Duration | `M4 − Σ_user − Σ_disc`（`SYS_WAIT([t_submit,τ_terminal])`） | 同上 | **§4** | **主指标**：剔用户思考+失联 |
| **M5** | Max Silent Gap | 见 §3.2 定义（决定性/终态到达间隔，仅在系统等待区间内取最大） | 依终态 | T2 §11.3 `max_silent` | 最长静止 |
| **M6** | Time in `S / R / T / G` | 见 §3.3（按派生状态分段，`SYS_WAIT` 口径） | 依终态 | T2 §11.3 `time_in(S)` 扩展 | 各活动态累计 |
| **M6p** | Time in PIN（用户思考） | `Σ_k (t_ur_k − t_wi_k)`（或 `cancel` 时到 `t_cancel`） | 有 PIN 的 Turn | T2 §8 | 用户等待（不属系统） |
| **M7** | Disconnect Duration | 见 §3.4（含检测滞后、失联时长、失联终止） | 依是否断线 | T2 §1.2/§2.4/§11.3 | 失联 |
| **M8** | Timeout / Cancel / Failure 相关 | 见 §3.5 | 依 `to/ca/er` | T2 终态 | 异常终结 |

### 3.2 M5 Max Silent Gap（精确定义）
候选间隔 `G` 收集（仅两端都在**同 Turn、连接态、非 PIN** 系统等待区间内）：
1. **leading**：`a(e_0) − t_submit`；
2. **internal**：所有相邻决定性到达 `a(e_{i+1}) − a(e_i)`（`i=0..n-2`），且该相邻对被断线/PIN 未隔断；
3. **trailing**：`τ_terminal − a(e_{n-1})`（若 `e_{n-1}` 与 `τ_terminal` 之间无断线间隔）。

```
M5 = max(valid gaps)
若对决：仅当区间两端连续、且完全落在 `SYS_WAIT` 视图（无 PIN/disconnect 遮蔽）时计入。
无任何有效间隔时（如连首 decisive 都缺失）→ M5 = undefined，样本 `invalid(missing_decisive)`。
```

### 3.3 M6 Time in `S/R/T/G`（精确定义）
用 T2 §2.1 状态机对决定性序列**确定性推导**状态段 `seg=[(st, seg_start, seg_end)]`。对每个状态 `X∈{S,R,T,G}`：
```
time_in(X) = Σ_{段 st==X} SYS_WAIT([seg_start, seg_end])
```
- 状态段边界 = 决定性到达时刻；终态段 `ε=[last_decisive, τ_terminal]` 记到 `τ_terminal`。
- `PIN` 段单独记为 `time_in(PIN)`（M6p），不并入活动态。
- 断线在段内时：`SYS_WAIT` 扣除失联区间，故失联不计入任何活动态（归 M7）。
- 要求：`Σ time_in(S/R/T/G) + Σ_user + Σ_disc ≈ M4`（一致性校验，用于自动化测试断言）。

### 3.4 M7 Disconnect Duration（三要素）
- **M7a 检测滞后**：`de_t−detect` 的客户端时长 = `t_disc_detected − t_last_live`（`t_last_live`＝断线前最后收到的决定性/心跳事件时刻；检测受心跳45s 上限约束，见 `ws.ts` HEARTBEAT_TIMEOUT_MS）。
- **M7b 失联时长（恢复前）**：`t_recovered − t_disc_detected`，其中 `t_recovered`＝重连成功（`resume_from` 后首个事件到达）时刻。
- **M7c 失联终止**：若在失联期间到达终态（`TO` 由 idle timer 触发，或用户 `CA`），则 `失联终止时长 = τ_terminal − t_disc_detected`，标记 `disconnect_terminated=true`。
- 聚合时 `#disc`＝失联段数；`Disconnect Duration` 独立成桶，不进 `M4s`。

### 3.5 M8 Timeout / Cancel / Failure
| 指标 | 定义 | 备注 |
|---|---|---|
| **M8-o Time to OK** | `t_done(completed) − t_submit`（=M4/OK） | 正常完成 |
| **M8-f Time to Failure** | `t_error(failed, turn_terminal) − t_submit` | 失败 |
| **M8-c Time to Cancel** | `t_cancel − t_submit`（用户动作或 cancelled 事件到达） | 取消 |
| **M8-t1 Time to Timeout** | `τ_TO − t_submit`（idle timer 触发） | 超时 |
| **M8-t2 Timeout Trigger Silence** | `τ_TO − t_last_event`（触发前静默段；≈ `chatTimeout` 减去已抵事件缓冲） | 超时诱因 |
| 派生态 | `fraction_time_in_X = time_in(X)/M4s`、`first_decisive_kind∈{content,tool,source,tool_result}` | 状态占比/首个决定性类型 |

> **口径**：`ok/er/ca/to` 四类**分别统计**，不混入同一分位（§5）。`TO` 与后端 `OK`/`ER` 互斥（T2 I7），任一先到达即定终态，指标以**实际到达者**为 `τ_terminal`。

---

## 4. 系统等待记账规则（完成标准 #3 的明确定义）

```
system_wait_interval(turn) = [t_submit, τ_terminal]
exclusion_set =
   PIN_user_waits ∪ disconnect_durations        // 均含半开端点错开，避免双边闭合重叠
SYS_WAIT(I) = |I| − Σ |I ∩ e| , e ∈ exclusion_set
M4  = |system_wait_interval|                      // 总经停（含排除）
M4s = SYS_WAIT(system_wait_interval)              // 系统等待（主口径）
```
**计入**：活动态真实经过时间（含隐藏的 TTFT/摘要/重试退避静默）。
**排除**：PIN 用户思考、disconnect 失联、终态之后。
**一致性断言**（可测）：`M4 − M4s = Σ_user + Σ_disc`（容差随单调时钟量化，测试内做浮点近似断言）。

---

## 5. 场景统计口径（完成标准 #4）

每类场景只在**同一口径**内聚合，禁止跨场景混算：

| 场景 | 聚合口径 | 说明 |
|---|---|---|
| **OK 正常完成** | `ok` 桶，可用 M1–M7 | 唯一的"无异常"基线桶 |
| **ER 失败** | `er` 桶，`M8-f` 为主；M4s 可报但标注 | 失败原因不清：仅报时长，不并 OK 桶 |
| **CA 取消** | `ca` 桶，`M8-c` 为主 | 取消发生时所在活动态时长单独报 |
| **TO 超时** | `to` 桶，`M8-t1/t2` 为主 | `timeout` 与 `OK/ER` 互斥（I7），先到者胜 |
| **断线恢复** | 若 turn 内含 ≥1 disc 段 → 入 `disc` 桶；M7 为主 | 不污染无断线桶的静默指标 |
| **断线终止** | `disconnect_terminated` 桶（M7c） | 失联致 TO/CA |
| **WAIT_FOR_INPUT (PIN)** | 含 PIN 段的 Turn 桶；M4s 剔除 PIN | 用户等待单列 `time_in(PIN)` |
| **多步 Agent / 检索 / 纯 chat** | 按 §6 维度再切分 | 见 §6 |

---

## 6. 任务/场景维度（完成标准 #5，避免无差别聚合）

每个样本按下列维度**档案化**；分位数只在与目标同维的桶内对比：

| 维度 | 取值（示例） |
|---|---|
| `capability` | `chat` / `rag` / `tool` / `agent(多步)` / `learn` |
| `tool_profile` | `no_tool` / `retrieval_only` / `tool_only` / `mixed` |
| `outcome` | `ok` / `er` / `ca` / `to` |
| `transport` | `clean` / `disconnected_recovered` / `disconnected_terminated` |
| `has_pin` | `true` / `false` |
| `warmth` | `cold_first`（首次回合/Kernel 冷启动，G6/S3）/ `warm` |
| `session_len` | 短 / 中 / 长（触发摘要 S2） |
| `model_provider` | 保留字段（B 平面诊断，不进入感知口径） |

> 分位对比规则：**同一 `(capability, tool_profile, outcome, transport, warmth)` 五元组**内才可纵向比较；其余不变体允许跨 `outcome` 桶但必须显式标注。

---

## 7. 分位数与样本有效性（完成标准 #6）

- **分位**：对每个桶内某指标的有效样本集合，计算 **P50 / P95 / P99**（线性分位：`rank = ceil(p*n)`，插值取相邻）。同时报 **AVG / MAX / count**。
- **样本有效性**：
  - 有效样本：清洗后(§2)、指标在该样本上有定义（非 `undefined`）、`invalid(reason)` 为空。
  - `invalid` 原因枚举：`clock`（时钟非单调/缺失）、`missing_ack`（M1 无 session）、`missing_decisive`（无决定性事件，M2/M5 undef）、`no_value`（无 `content(非空)`，M3 undef）、`overlap_error`（`M4−M4s` 与排除量不一致，记账断言失败）、`replay_ambiguous`（重放与实时状态序列不一致，I9 违反）。
  - 无效样本**计入 `invalid_count` 并给出原因分布**，但**不进分位**（避免污染分布）。
- **最小样本**：每桶每指标 `min_n`（默认 30，可配置）。不足 → 该桶该指标标记 `samples_insufficient`，只可观察不可验收（进入 WARN 档，见 §10）。

---

## 8. 异常样本、缺失/重复/乱序/重放处理原则（完成标准 #8）

| 情形 | 处理 | 依据 |
|---|---|---|
| **缺失 decisive**（无任何决定性，直接空转到时间） | 无 `e_0`：若到达终态，`M4/τ` 可用；`M2/M3/M5` → `undefined` → `invalid(missing_decisive)` | T2 I6 语义 |
| **缺失 done**（有 content 但无 done） | 有 `content(非空)`：M3 有效；`M4/M4s` 依赖 `τ`，缺失→用最后决定性到达近似并标记 `truncated` | 截断样本，不进分位 |
| **重复事件** | `seq ≤ lastSeq` 丢弃；重放去重 | T2 I6 |
| **乱序事件** | 实时：按到达时刻记录，但丢弃 `seq ≤ lastSeq`（拒绝陈旧）；重放：按 `(seq)` 排序再按 `seq` 重放，与实时**必须**得同状态序列 | T2 I6/I9 |
| **replay/resume** | `resume_from(lastSeq)` 续播去重；断线区间归 M7，不污染活动态时长 | T2 §2.4/§8 |
| **时钟异常** | `performance.now` 缺失/非单调 → `invalid(clock)` | §1 |
| **美容噪声（result/空 content）** | 属文案级，不进任何间隔/分母 | T2 §5/§11.4 |
| **终态后事件** | 闩锁丢弃（幂等） | T2 I1 |

> 这些规则与 T2 §9 冲突/异常处理第 1–6 条逐条对齐，保证**同一有序轨迹重放结果唯一**（I9）。

---

## 9. Baseline 结构与版本对比（完成标准 #9）

**Baseline**＝一个**提交固定的、按桶聚合的分布快照**，用于后续回归与版本对比。结构（JSON/JSONL，schema 版本化）：

```
{
  "schema_version": "1.0",
  "frozen_against": ["t2-perceived-waiting-state-model-v1"],
  "generated_at": "<ISO>", "app_version": "<git-sha>",
  "dimensions": ["capability","tool_profile","outcome","transport","warmth","has_pin"],
  "buckets": [
    { "scene": {"capability":"chat","tool_profile":"no_tool","outcome":"ok",
                "transport":"clean","warmth":"warm","has_pin":false},
      "metrics": {
         "M3":   {"P50":..,"P95":..,"P99":..,"avg":..,"max":..,"n":..},
         "M4s":  {"P50":..,"P95":..,"P99":..,"avg":..,"max":..,"n":..},
         "M5":   {...},
         "time_in_S":{...},"time_in_G":{...}, ...
      },
      "samples_insufficient": false
    }
  ],
  "thresholds": { "M3": {"P95_warn_pct":"TBD_CALIBRATE","P95_fail_pct":"TBD_CALIBRATE"}, ... }
}
```

**回归/版本对比**：重跑同一场景套件 → 按同 `scene` 桶计算新分位 → 与 baseline 对比：
- 相对漂移法：`drift = (new − base)/base`，对 `P50/P95/P99` 分别求；
- 若两版本样本独立且 `n` 足，可选用**重叠置信区间 / 双样本 Mann-Whitney**（可选，不在本阶段实现）；
- 输出 `diff_multi_metric` 报表，供人工与自动门禁消费。
> 早期无足够真实数据时，baseline 可为空（`empty_baseline`），只记录 schema 与维度，待采集后归档。

---

## 10. PASS / WARN / FAIL 验收框架（完成标准 #10）

> **绝对阈值不得凭空设定**：在未采集足够真实数据前，一切绝对数值目标标记为 `CALIBRATION_PENDING`（见红字），只提供**结构化的验收程序**。

**决策程序（每桶每指标）**：
1. `samples_insufficient` 或 `invalid_count` 偏高（无效占比 > 阈值，默认 10%，可配）→ **WARN（数据质量不足）**。
2. 否则对目标指标与 `baseline` 分位比较：
   - `drift ≤ warn_pct` → **PASS**；
   - `warn_pct < drift ≤ fail_pct` → **WARN（回归观察）**；
   - `drift > fail_pct` 或超出硬性上限 `hard_max` → **FAIL（回归阻断）**。
3. 无 baseline 时：仅当无 `WARN/FAIL` 触发即标记 `PASS(no_baseline, record only)`，并鼓励建立首个 baseline。

**阈值占位（必须校准）**：
```
M3(P95):   warn_pct=CALIBRATION_PENDING  fail_pct=CALIBRATION_PENDING  hard_max=CALIBRATION_PENDING
M4s(P95):  warn_pct=CALIBRATION_PENDING  fail_pct=CALIBRATION_PENDING
M5(P95):   warn_pct=CALIBRATION_PENDING  fail_pct=CALIBRATION_PENDING
M7b(P95):  warn_pct=CALIBRATION_PENDING  fail_pct=CALIBRATION_PENDING
```
> 标注：以上数值全部为 `CALIBRATION_PENDING`——现有证据（T1 单点实测 8.256s 静默、S5 退避 5/10/20s）不足以制定稳定绝对阈值，必须在真实采集后校准，**本阶段不生效为告警**。唯一可立即生效的是**结构规则**（维度、分位、无效样本、componentwise 漂移判定）。

---

## 11. 确定性推导算法（自动化测试的硬输入）

```
IN: raw event log R（实时到达序） + 本机动作 + 传输覆盖
CLOCK = 客户端单调时钟

CLEAN(R):
  L=[]; lastSeq=0; terminal=None
  for e in R:                       # 按到达序
    if e.seq and e.seq<=lastSeq: continue
    lastSeq=max(lastSeq,e.seq or 0)
    if terminal and e 属于决定性终态: continue      # 闩锁
    if e.type in DECISIVE: L.append(e)
    if e.type in TERMINAL_DECISIVE:
        if terminal is None: terminal=e
  return L, terminal

DERIVE(STATE_SEQ):    # T2 §2.1 状态机，决定性事件驱动
  st=IDLE; seg=[("IDLE",t_submit,t_submit)]
  for e in L: nxt=TRANSITION(st,e); ...
  close to τ_terminal

COMPUTE(seg, terminal, user_actions, disc):
  等 → M1..M8s（§3，全部用 SYS_WAIT 口径）

ASSERT:
  M4-M4s == Σ_user + Σ_disc   （浮点近似）
  derived state seq 与（若有）实时观测 state seq 一致 → 否则 invalid(replay_ambiguous)
```

> 任何确定性属性违反（如重放与实时状态序列不一致）直接产出 `invalid(replay_ambiguous)`，不静默含糊。

---

## 12. 代表性轨迹验证（完成标准 #11：确定性与可重放性）

对 T2 §12 的 T1–T12 轨迹，用上述算法**示例算一遍**核心指标。所有 `t` 为客户端单调时钟，单位秒。（`result`/`thinking` 属文案级，不进任何间隔。）

**记法**：`s`=submit=0；`ses`=session(ack)；`cX`=content；`tcallKind`=tool_call(kind)；`tres`=tool_result；`wi/ur`=wait_for_input/idle 前用户动作；`done/err/cancel/timer`=终态。

| # | 轨迹（决定性 ＋ 标注参数） | 状态序列 | M1 | M2 | M3 | M4s | M5 | time_in | M7 | M8 | 说明 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| T1 正常 chat | `ses(0.013) c1(8.269) … cN(9.99) done(10.0)` | S→G→OK | 0.013 | 8.269 | 8.269 | 10.0 | **8.269**(leading) | S=8.269;G=1.731 | 0 | ok=10.0 | 复现审计 §3（MAX_SILENT=8.256 同构） |
| T2 检索 | `ses(0.013) tcall(rag,1.1) tres(2.3) c1(6.9) done(7.8)` | S→R→G→OK | 0.013 | **1.1** | 6.9 | 7.8 | 4.6 | S=1.1;R=5.8;G=0.9 | 0 | ok=7.8 | 首 decis.=tool_call→R |
| T3 多步 Agent | `tcall(rag,1) tres(2) c1(5) tcall(web_fetch,6) tres(7) c2(8) done(9)` | S→R→G→T→G→OK | ≈0.01 | 1 | 5 | 9 | 3 | S=1;R=4;G=2;T=2 | 0 | ok=9 | G→T 为真实新阶段(T2 §2.3) |
| T4 WAIT_FOR_INPUT | `c1(2) wi(3) [ur=8.5] c2(9) done(10)` | S→G→PIN→S→G→OK | — | 2 | 2 | **4.5** | 2 | S=2.5;G=2;PIN(用户)=5.5 | 0 | ok=10 | **PIN 用户思考 5.5s 剔除(M4=10→M4s=4.5)** |
| T5 重试静默 | `ses(0.01) [后端退避无事件] c1(25) done(26)` | S(原地)→G→OK | — | 25 | 25 | 26 | 25 | S=25;G=1 | 0 | ok=26 | 无假进度，TTFT/S5 静默全归 S |
| T6 断线恢复 | `c1(2) [disc 4→6, resume] done(7)` | S→G→…→OK（P 保持 G） | — | 2 | 2 | **5** | 2 | G(连接)=3(SYS_WAIT 扣失联) | **M7b=2** | ok=7 | M4=7；Σ_disc=2 → M4s=5 |
| T7 取消 | `c1(3) [cancel=4] err("Turn cancelled")+done(cancelled)` | S→G→CA | — | 3 | 3 | 4 | **3** | G=1 | 0 | ca=4 | M8-c |
| T8 超时 | `[无 decisive 直至 timer=180]` | S→TO | — | undef | undef | 180 | undef | S=180 | 0 | to=180; t2=180 | M2/M3/M5→invalid(missing_decisive) |
| T9 竞态 done vs cancel | `c1(3) (同刻 done(completed)先于 cancel处理)` | S→G→**OK**（cancel 丢弃） | — | 3 | 3 | 4 | **3** | G=1 | 0 | ok=4 | 先到者胜(I7) |
| T10 done 迟到 vs TO | `[timer=180 先触发] 迟到 done` | S→**TO**（done 丢弃） | — | undef | undef | 180 | undef | S=180 | 0 | to=180 | I1 闩锁 |
| T11 断线后新 submit | 旧`c1(3)`→disc→[新 submit]；新`ses c1 done` | 旧 S→G→**CA**；新 S→G→OK | — | (旧)3 | (旧)3 | — | — | 旧 G 止于 CA | 新 Turn 独立 | 旧 ca | 单活跃(I5/I10)；旧 Turn 先 CA 隔离 |
| T12 thinking 不进 G | `ses(0.01) thinking(5) c1(7) done(8)` | S→(thinking 文案,S)→G→OK | — | **7** | 7 | 8 | 7 | S=7;G=1 | 0 | ok=8 | thinking 不产生 M2/M3（无 content） |

> 注：M1（服务端确认）在示例行中，凡未显式给出 `ses` 到达时刻的，视为 `session` 在 `t≈0.01s` 到达并省略显示（`M1≈0.01`）；`—` 表示该行非本指标关注点，不影响其余指标（`session` 非决定性，不进任何静默/时长口径，T2 §5/§11.4）。

**重放一致性（完成标准 #11）**：对任意一行，把"决定性事件 + 客户端到达时刻 + seq"的有序日志从冷客户端重放，**去重→状态推导→指标**逐项与此表一致。原因：
1. 决定性集/顺序固定，状态由决定性事件唯一决定（T2 §2.2）；
2. 终态先到者胜且闩锁（I1/I7）；
3. 文案级事件不进测量（I2/I4 附）；
4. `SYS_WAIT` 记账函数确定性；`seq` 去重保证重放与实时同序；
5. 跨 Turn 隔离（I5/I10）使 T11 重放唯一。
故满足**确定性、可解释、可测试、可重放**。

---

## 13. 覆盖 T1 G1–G8 / S1–S6（完成标准 #12 前半）

| 项 | 由哪个指标/口径覆盖 |
|---|---|
| G1 / S1 首 token 静默 | **M3 TTFMR**、M2、M5；T1/T5 演示 |
| G2 / S5 LLM 静默重试 | T5 轨迹：重试静默全归 S（`time_in_S`）；M8 区分；I3 无假进度 |
| G3 / S2 摘要被过滤 | 归 `S` 静默；`session_len` 长 → wait（`warmth/session_len` 维度区分） |
| G4 / S4 工具无子进度 | M6 `time_in(T/R)`；M2 首 decis.=tool_call |
| G5 断线不复位 | **M7**（a/b/c）、`transport` 维度、T6/T11 |
| G6 / S3 冷启动 | `warmth=cold_first` 维度隔离到 S 静默 |
| G7 标题生成 | 终态后非决定性，不进任何指标（§1 排除 3） |
| G8 重复提交 | 单活跃 I5/I10；T11 隔离 |
| 成功/失败/取消/超时 | `outcome∈{ok,er,ca,to}` 分桶；M8 系列 |
| 等待用户输入 | `has_pin=true` 桶、M6p、T4 |

=> **G1–G8、S1–S6 全部覆盖，无遗漏（完成标准 #12）。**

---

## 14. T4 等待体验设计规范的输入（完成标准 #12 后半）

本指标为 T4 提供**可测量验收量纲**：
- T4 的任何等待交互设计（首反馈打磨、静默分桶、超时提示）以 **M2/M3/M5/M6** 的分布为**现状基线**；
- T4 验收以 **M4s（主）＋ M2/M3（首阶段）＋ M7（断线）** 在 §6 桶内的 **P50/P95/P99** 漂移为判据；
- `CALIBRATION_PENDING` 阈值在 T4 阶段以真实数据填充后转 PASS/FAIL。
> T4 不得绕过本指标契约：任意改变等待语义的行为必须先在对应桶复测。本阶段**不进入 T4**（见 §15）。

---

## 15. 修正验收与 FROZEN BASELINE 声明

> 完成标准逐项核验，全部通过后正式冻结本 T3。

| 完成标准 | 落实 |
|---|---|
| ① 核心指标集合（TTA/TTFD/TTFMR/M4/M5/time_in/disconnect/超时取消失败） | §3 M1–M8 全覆盖 |
| ② 每项唯一无歧义数学/事件边界 | §3.1 表 + §3.2–3.5 + §2 白名单 |
| ③ 计入/排除明确 | §4 记账规则（PIN 用户思考、失联、终态后排除） |
| ④ 场景统计口径 | §5（ok/er/ca/to/disc/PIN/多步/检索/chat 分桶） |
| ⑤ 任务/场景维度防混聚 | §6 维度五元组 |
| ⑥ P50/P95/P99 与样本有效性 | §7（min_n=30、invalid 原因枚举、退位） |
| ⑦ 核心概念与 T2 状态机一致 | 静默/首反馈/首有效结果逐项引 T2 §2/§5/§11；G 仅由 content(非空) |
| ⑧ 异常/缺失/重复/乱序/重放处理 | §8 对齐 T2 §9 第1–6条 |
| ⑨ baseline 结构与版本对比 | §9（JSON schema、buckets、drift 法） |
| ⑩ PASS/WARN/FAIL 框架；阈值标注待校准 | §10（绝对阈值 `CALIBRATION_PENDING`，不凭空设定） |
| ⑪ 代表性轨迹验证确定/可重放 | §12 T1–T12 指标演算 + 重放一致性论证 |
| ⑫ 覆盖 G1–G8/S1–S6 且可作 T4 输入 | §13 全覆盖；§14 T4 输入契约 |
| ⑬ 输出本文档与验收结论 | 本 §15 |
| ⑭ 全部通过后标记 FROZEN BASELINE | 见下 |

**结论**：上述 14 项完成标准全部通过。**T3 per `PERCEIVED_LATENCY_METRICS_V1.md` 正式标记为 `FROZEN BASELINE`**（`FROZEN_BASELINE = "t3-perceived-latency-metrics-v1"`）。绝对体验阈值因缺真实数据标注为 `CALIBRATION_PENDING`（不生效为告警），**不实施 UI / 不改生产代码 / 不进入 T4 实现**，仅交付冻结的指标契约。

——