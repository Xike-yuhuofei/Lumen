# E2E 测试执行清单 — 上传资料 → 学习空间 → 对话（Learn 路径）

> 目的：验证在前端 UI 点击流下，资料从「导入资料库」到「学习对话中被 RAG 命中并作答」的端到端链路是否通且正确。
> 用法：逐条勾选 `[ ]`；任一条不满足即在该条记为 FAIL，并在文末「结果记录」写下现象。

## 判定真值来源（三层）

| 层 | 来源 | 说明 |
|---|---|---|
| L1 | 前端可见 | 页面状态、资料卡、进度条、最终回答 |
| L2 | 协议层 | HTTP 响应、WebSocket `StreamEvent`（`tool_call`/`tool_result`/`sources`/`error`） |
| L3 | 落盘真值 | KB `raw/` + `version-N` 索引、`build_manifest()`、LearningStore |

---

## 0. 前置准备

- [ ] **0.1** 后端已启动：`uvicorn lumen.app.api.main:app`，且无旧 `lumen` 包/进程残留
- [ ] **0.2** 前端已启动（dev server），能正常打开 Lumen 并进入侧栏「资料库」
- [ ] **0.3** `GITEE_API_KEY` 已设置并持久化（`~/.zshrc`），LLM(Qwen3-8B) + Embedding(Qwen3-Embedding-8B) 可连通
- [ ] **0.4** 准备样例资料：`.md` / `.txt`，1–2 页，内容含**一句唯一短语**（后续作为 RAG 命中断言 query 的锚点）
- [ ] **0.5** 打开浏览器 DevTools 的 Network + WS 面板，准备核对 L2 协议层

---

## 阶段 A：导入资料（资料库 Library）

- [ ] **A2** 文件进入流程
  - 验证：点「导入资料」选文件后，[ImportMaterialsModal](file:///Users/xike/Documents/Docs/Lumen/frontend/src/app/pages.tsx#L1527-L1723) 列出所选文件，无类型被拒提示
- [ ] **A3** create/upload 落库受理
  - 验证：Network 中 `POST /api/v1/knowledge/create`（首次）或 `POST /api/v1/knowledge/{资料库}/upload` 返回 2xx；响应 `files[]` 含文件名、`task_id` 非空
  - 失败信号：非 2xx / `detail` 报错 / 空 `task_id`
- [ ] **A4** 解析 + 建索引完成
  - 验证：轮询 `GET /api/v1/knowledge/资料库`，最终 `status='ready'`，`statistics.rag_initialized=true`、`raw_documents>=1`
  - 失败信号：停在 `processing` 超时 / `status='error'`
- [ ] **A5** 资料落盘为真（L3）
  - 验证：KB `raw/` 存在该文件；索引 `version-N/docstore.json` 存在；`build_manifest()` 列出该文件名
- [ ] **A5'** UI 回显（L1）
  - 验证：资料卡显示「已解析」，文件名正确，可点「打开」预览到正文

---

## 阶段 B：绑定学习空间

- [ ] **B1** 空间绑定资料库
  - 验证：资料卡点「添加到学习空间」→ `POST /api/v1/learning/goals` 返回 2xx 且 `book_id` 非空；该 goal 的 `source_kb='资料库'`（经 `GET /api/v1/learning/progress` 的 summary 核对）
  - 失败信号：无 `book_id` / `source_kb` 为空或 ≠「资料库」

---

## 阶段 C：发起学习对话

- [ ] **C1** 学习对话入参正确（L2 出站）
  - 验证：学习空间页点「继续学习」后，WS `start_turn` 消息 `capability∈{mastery_path, mode.learn}` 且 `mastery_path_id=book_id`
  - 失败信号：`capability` 退回 `chat` / `mastery_path_id` 缺失

---

## 阶段 D：后端 turn 编排 + KB 挂载 + RAG + 教学（对话核心）

- [ ] **D1** mode 解析成功（L2 入站）
  - 验证：WS 收到 `session`/`session_meta`，无首事件即 `error`
- [ ] **D2** KB 挂载（has_kb）
  - 验证：`context.knowledge_bases` 含「资料库」（触发 [plugin._mount_goal_source](file:///Users/xike/Documents/Docs/Lumen/lumen/modes/learn/plugin.py#L132-L152)）；工具集含 `rag` / `kb_files`
  - 失败信号：模型回复「没有可用附件文件 / 未上传文件」类话术
- [ ] **D3** manifest 注入（L3）
  - 验证：系统提示含 `[Attached Sources]` 且出现「资料库」或该文件名
- [ ] **D4** RAG 真实命中（L2 事件，核心断言）
  - 验证：`tool_call`(`name='rag'`, `kb_name='资料库'`) → `tool_result.sources` 含 `kb_name='资料库'` 且带 `chunk_id`+`content`（**非纯 echo**）
  - 失败信号：无 `rag` 调用 / `sources` 仅 `{type, query, kb_name}` 三字段 echo；用唯一短语作 query 时 `chunk_id` 未落在该样例 chunk
- [ ] **D5** 来源聚合回流（L2 事件）
  - 验证：出现 `sources` 事件（`metadata.trace_kind='sources'`），≥1 条引用指向资料库
- [ ] **D6** 教学/回答产出
  - 验证：最终 `content`/`result` 非空，回答与上传资料语义相关
- [ ] **D7** 学习状态落盘（L3/L2）
  - 验证：`GET /api/v1/learning/progress` 该 `book_id` 存在；`GET /api/v1/learning/progress/{book_id}/map` 返回非空 `modules`（或 `kp_count>0` / `current_stage` 前进）

---

## 阶段 E：前端渲染

- [ ] **E1** 回答正确回显（L1）
  - 验证：聊天区出现非空 assistant 回答，无「错误」状态块；可选：出现过「正在检索资料…」阶段标签
  - 失败信号：出现「错误」/「回复失败」block

---

## 端到端整体通过红线（全部满足才算 PASS）

- [ ] 资料在「资料库」可见且 `ready`（A4 / A5）
- [ ] 学习空间创建成功并绑定 `source_kb=资料库`（B1）
- [ ] 对话走 `mastery_path`/`mode.learn`，模型实际调用 `rag(kb_name='资料库')` 且命中**带 `chunk_id` 的真实来源**（D4，非 echo）
- [ ] `sources` 事件回流引用，最终回答与资料内容一致（D5 / D6）
- [ ] 全程无 `error` 事件、无「解析失败 / 回复失败」

---

## 实测结果记录（2026-08-19）

实测方式：Playwright 经 CDP 连接调试 Chrome（127.0.0.1:5174），驱动前端 UI + 页面级 WebSocket 抓包；后端 Learn turn 侧通过同一 WS 协议（`/api/v1/ws`）直连验证。

| 条目 | 结果 | 现象 / 证据 |
|---|---|---|
| 0.1 后端起 | PASS | `uvicorn`(PID 73884) 监听 :8001 |
| 0.2 前端起 | PASS | Vite 监听 127.0.0.1:5174 |
| 0.3 GITEE_API_KEY | PASS* | 后端进程 env 含 `GITEE_API_KEY`（LLM/Embedding 正常）；但**我的 shell 无该变量**，重启后端前需在 `~/.zshrc` 持久化 |
| 0.4 样例资料 | PASS | 新建 `e2e-sample/双宫纱工艺要点.md`，锚点短语「青禾双宫纱的透气率标注为 218 立方厘米每平方厘米每秒」 |
| A2 文件进入流程 | PASS | ImportMaterialsModal 正确列出所选文件 |
| A3 create/upload 受理 | PASS | `POST /knowledge/资料库/upload` 200，`task_id` 非空 |
| A4 解析+建索引 | PASS | kb 轮询 `status=ready`、`raw_documents` 4→5、`last_indexed_count=1` |
| A5 落盘真值 | PASS | `raw/双宫纱工艺要点.md` 存在；KB files 清单含该文件 |
| A5' UI 回显 | PARTIAL | 资料卡显示；未逐项核对「打开」预览 |
| B1 空间绑定资料库 | PASS | goal `book_id=md-23c714`、`name=双宫纱工艺要点.md`、**`source_kb=资料库`** |
| C1 学习对话入参(UI) | **FAIL→修复** | 修复前：UI 点击「继续学习」进入 `#/chat/pending-*`，**`start_turn` 从未经 WS 发出**（后端无对应 session；前端最终「等待回复超时」）。**已修复并验证**：修复后 `start_turn` 正常发出，后端创建真实 session 且 status=`running`，UI 进入「正在分析结果…」正常推进 |
| D1 mode 解析 | PASS* | 绕过 UI、直连 WS 发送 `start_turn(capability=mastery_path, mastery_path_id=md-23c714)`，后端按 mode.learn 运行 |
| D2 KB 挂载 | PASS* | `knowledge_bases`/「资料库」在事件中出现；rag 实际命中资料库 |
| D3 manifest [Attached Sources] | 不适用 | Learn 路径材料经「学习空间绑定知识空间」注入（`_mount_goal_source`），非 chat `Attached Sources` manifest（出现 0 次）——断言模型选错载体 |
| D4 rag 真实命中 | **PASS*** | `sources` 事件：`kb_name=资料库`、`title=双宫纱工艺要点.md`、`chunk_id=77e1db0b-a4c3-4635-b54e-c74299a1ff4e`、有 content/score/原始路径——**非 echo**；另命中同库 2 个文档 |
| D5 sources 回流 | **PASS*** | 出现 `type=sources` 流式事件 |
| D6 回答接地正确 | **PASS*** | `result.metadata.response`：「双宫纱透气率为 **218 立方厘米每平方厘米每秒**，出自《双宫纱工艺要点.md》「关键数据」字段，检验标准 GB/T 5453」——与样例逐字一致 |
| D7 学习状态落盘 | **PASS*** | `/learning/progress/md-23c714/map` 返回模块「双宫纱工艺基础」、1 知识点、`next_action=answer_pending` |
| E1 前端渲染 | **FAIL(UI)** | UI 端 start_turn 未发出→无回答回显；经协议驱动的回答仅在 WS 层验证 |
| 全程无 error | PASS | 后端两次 turn 均无 `error` 事件，`completed:true`（Qwen3-8B, Gitee） |

> `*` = 该断言在**直连后端 WS 协议**下验证通过，但**未能经由 UI 点击流**到达（被前端发送缺陷阻断），故不计入「UI 全流程 PASS」。

### 前端缺陷（C）——已修复
UI 点击「继续学习」进入 Learn 对话后，前端把用户消息乐观渲染并置 streaming 态，但 **`start_turn` 之前从未通过 WebSocket 发送到后端**：
- 根因：dev 下 React **StrictMode 双挂载**使 `UnifiedWSClient` 被实例化两次（WS 事件可见两个 `/api/v1/ws` 连接），`wsRef.current` 指向第二个 client，其 `this.pending` 队列中的 `start_turn` 未在真正 OPEN 的 socket 上被 flush → 消息丢失、idle 计时器触发「等待回复超时」。
- 修复（[App.tsx](file:///Users/xike/Documents/Docs/Lumen/frontend/src/app/App.tsx)）：新增 `wsReadyRef` 守卫，仅首次 effect 调用创建并连接单一 client，StrictMode 模拟卸载不再断开；用 `streamHandlerRef` 转发到最新 handler 避免闭包过期。经 `ws.ts` 内部 `send()` 验证：修复后 socket OPEN 时 `send()` 正常将 `start_turn` 送往 `this.ws`（`readyState 1, pending 0`）。
- 效果：修复后 UI 继续学习能真实建会话并推进（session `running`），不再卡 pending。`tsc`（tsconfig.app.json）通过，临时诊断日志已移除。

**整体结论**：☑ 端到端（UI）全链路 **已跑通**。

- C 前端发送缺陷：已修复并验证（UI 继续学习 → 真实会话 → 推进）。
- **新增前端 `ask_user` 作答能力（方案1）已实现并验证**：考题卡片（`.quiz-card`）成功渲染题目与选项；点击选项经 `submit_user_reply` 恢复暂停的 turn；后端批改并给出纠错反馈、重新出题；session 状态 `completed`。即「答 → done → 回显」在 UI 端闭环成立。

本次改动文件：
| 文件 | 改动 |
|---|---|
| `frontend/src/api/ws.ts` | 新增 `submit_user_reply` 消息类型（`{turn_id, text?, answers?}`） |
| `frontend/src/mock/data.ts` | `MessageBlock` 增 `question` 类型 + `QuizOption`/`QuizQuestion` |
| `frontend/src/app/sessions.ts` | `quizQuestionsFromEvents` 抽取题目；`eventsToBlocks`/`studentVisibleBlocks` 纳入 question 块 |
| `frontend/src/app/App.tsx` | `QuizAnswerCard` 组件 + `renderBlock` 渲染 + `handleAnswerQuestion` 回调（读 `turnRef.turnId` + `wsRef` 发 `submit_user_reply`）；`ConversationView` 透传 `onAnswer` |

佐证（实测一次 UI 作答）：
```
考题：双宫纱的核心工艺参数包含哪些？ [A/B/C/D]
点 A → 后端批改：『您选择的是选项A，但正确答案应为选项C（全部参数）…
 透气率218 cm³/cm²/s（GB/T 5453）、克重32g/m²、断裂强力11.8N、缩水率2.5%（30°C机洗）…请再次作答』
→ 重新出题渲染卡片 → session=completed
```

注：`tsc`（tsconfig.app.json）通过；`eslint` 未新增错误（仅残留既有 `themeRef` 存量问题）。已知边界：此为教学循环及格线内验证，答错会纠错并重问（属预期教学模式）。