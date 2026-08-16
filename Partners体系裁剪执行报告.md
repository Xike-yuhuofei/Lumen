# Partners 体系裁剪执行报告

- **分支**：`chore/prune-partners`
- **Worktree**：`../Lumen-wt-partners`
- **基线**：`V4FM-Lumen最小后端能力与调用链审计报告.md`
- **目标**：完整移除 DeepTutor 原有 IM / Bot / Partner 渠道体系，同时保证 Lumen 产品聊天主链路不受影响。
- **当前提交（基线）**：`2e98e57e chore: add project notes and probe results`

---

## 一、调用链追踪（删除前确认）

按强制要求，先完整追踪 `startup → PartnerManager → channel registry → partner tools → multi_user` 才算删除依据，未做“前端不用就暴力删除”：

```
Lifespan startup
  └─ deeptutor/api/main.py  auto_start_partners()  →  deeptutor/services/partners/manager.py
        └─ PartnerManager.start() → channels/manager.py ChannelManager
              └─ partners/channels/registry.py 登记 16 个 IM channel
                    └─ partner tools 自动挂载（agentic_pipeline forced/suppressed）
                          └─ multi_user/partner_access.py + services/partners/scope.py
CLI: deeptutor_cli/partner.py  partner 命令组
API: routers/partners.py + routers/_partners_channel_schema.py
Migration: services/memory/store.py migrate_partner_surface_if_needed
Config: partners/config/schema.py + paths.py；settings/plugins_api 中 partner defaults
Cron: services/cron/executor.py _execute_partner_job
```

追踪结论：Partner 体系是**独立于 Lumen 聊天主链路**的自包含大模块，仅通过
`api/main lifespan`、`tools/builtin`、`agentic_pipeline`、`subagents`、`multi_user`、
`cron`、`memory`、`attachment_store`、`settings`、`plugins_api`、`CLI`、`Config` 等
**接入点**挂载。删除时先移除这些接入点引用，再删除 Partner 目录/模块，保证主链路零影响。

---

## 二、实际减少代码量

| 类别 | 数量 |
| --- | --- |
| 变更文件总数 | 103 |
| 删除行数 | **25,116** |
| 新增行数 | 39 |
| 净减少 | **25,077 行** |

### 删除的 Partner 源码模块（约 17,506 行）

- `deeptutor/partners/`（完整目录）：`__init__`、`bus/`、`channels/`（16 个 IM channel：
  base、dingtalk、discord、email、feishu、manager、matrix、mattermost、mochat、msteams、
  napcat、qq、registry、slack、telegram、wecom、weixin、whatsapp、zulip）、`config/`、
  `helpers.py`、`network.py`、`transcription.py`
- `deeptutor/services/partners/`（完整目录）：`manager.py`、`runtime.py`、`commands.py`、
  `sessions.py`、`workspace.py`、`scope.py`、`model_runtime.py`
- `deeptutor/services/subagent/partner.py`
- `deeptutor/tools/partner_memory.py`
- `deeptutor/multi_user/partner_access.py`
- `deeptutor/api/routers/partners.py`（1,178 行）+ `_partners_channel_schema.py`（176 行）
- `deeptutor_cli/partner.py`

### 删除的 Partner 专属测试（约 6,300 行）

- `tests/partners/`（4 个 markdown 工具测试）
- `tests/services/partners/`（16 个测试 + conftest/__init__）
- `tests/api/test_partners_router.py`、`test_partners_channel_schema.py`、`test_plugins_api_partner.py`
- `tests/multi_user/test_partner_access.py`、`test_owner_path_service.py`
- `tests/test_matrix_requirements.py`

### 保留模块中移除的 Partner 引用（约 1,500 行）

- `deeptutor/api/main.py`：移除 `auto_start_partners` lifespan 调用、停止 Partner 逻辑、
  `migrate_partner_surface_if_needed`、`partners.router` 注册与导入
- `deeptutor/tools/builtin/__init__.py`：移除 `PartnerRead/Memorize/SearchTool` 注册与 `PARTNER_BUILTIN_TOOL_NAMES`
- `deeptutor/agents/chat/agentic_pipeline.py`：移除 Partner 工具 forced/suppressed 挂载逻辑
- `deeptutor/api/routers/subagents.py`：移除 `PARTNER_BACKEND_KIND`、`assert_partner_allowed`
- `deeptutor/services/cron/executor.py`：移除 `_execute_partner_job`
- `deeptutor/services/memory/store.py` + `__init__.py`：移除 `migrate_partner_surface_if_needed`
- `deeptutor/multi_user/paths.py`、`router.py`：移除 partner scope 路径与路由
- `deeptutor/services/storage/attachment_store.py`：移除对 `deeptutor.partners.helpers.safe_filename`
  的依赖，改为本地 `_safe_filename`
- `deeptutor/api/routers/settings.py`、`plugins_api.py`：移除 partner 配置 schema / defaults
- `deeptutor/capabilities/subagent/`、`services/subagent/registry.py`：移除 partner backend
- `deeptutor/services/session/source_inventory.py`：移除 partner 会话分类
- `deeptutor_cli/main.py`：移除 `partner` 命令组注册

---

## 三、删除 SDK 数量

`pyproject.toml` 中删除 3 组 optional-dependencies（`partners`、`matrix`、`matrix-e2e`）
及 `tutorbot` 兼容别名。对应 `requirements/partners.txt`、`requirements/matrix.txt`、
`requirements/matrix-e2e.txt` 同步删除。

**删除的 8 个 IM 平台 SDK / 依赖（共 18 个包，保留 3 个核心包）**：

| # | 依赖包 | 对应渠道 |
| --- | --- | --- |
| 1 | `python-telegram-bot[socks]` | Telegram |
| 2 | `slack-sdk` + `slackify-markdown` | Slack |
| 3 | `lark-oapi` | 飞书 Feishu |
| 4 | `dingtalk-stream` | 钉钉 DingTalk |
| 5 | `wecom-aibot-sdk` | 企业微信 WeCom |
| 6 | `qq-botpy` | QQ |
| 7 | `matrix-nio`（含 `[e2e]`） | Matrix |
| 8 | `zulip` | Zulip |
| +辅助 | `python-socketio`、`msgpack`、`python-socks`、`socksio`、`websocket-client`、`PyJWT[crypto]`、`qrcode`、`mistune`、`nh3` | 各渠道传输/登录/校验辅助 |

**保留的核心依赖**（确有核心使用，未被误删）：
- `mcp`：MCP 服务核心，被 `deeptutor/services/mcp/manager.py` 使用 → 从 partners extra 移入核心 `dependencies`
- `aiohttp`：LLM provider（`local_provider.py`、`cloud_provider.py`、`context_window_detection.py`）核心使用
- `websockets`：`runtime/spa_server.py` 核心使用

---

## 四、清理的启动生命周期逻辑

`deeptutor/api/main.py` lifespan `startup`/`shutdown` 中移除：

- **启动**：`get_partner_manager().auto_start_partners()`（原位于 cron 启动前后的 try/except 块内）
- **启动**：`migrate_partner_surface_if_needed()` 内存迁移调用
- **关闭**：停止 PartnerManager / 关闭 channel 连接的逻辑块

保留的启动逻辑验证：MCP 连接、cron 服务、v1 内存迁移均正常执行，无 Partner import error。

---

## 五、配置变化

- `pyproject.toml`：
  - 删除 `[project.optional-dependencies]` 的 `partners`、`matrix`、`matrix-e2e`、`tutorbot`
  - `all` extra 由 `server + partners + matrix + math-animator + dev` 精简为 `server + math-animator + dev`
  - 核心 `dependencies` 新增 `mcp>=1.26.0,<2.0.0`
- `requirements/`：删除 `partners.txt`、`matrix.txt`、`matrix-e2e.txt`；`server.txt` 中 cron 注释由
  “chat & partner scheduled tasks” 语义保留（cron 主服务仍为核心）
- `deeptutor/api/routers/settings.py`、`plugins_api.py`：移除 partner 配置 schema / defaults
- `.github/workflows/tests.yml`：移除 `requirements/partners.txt` 安装与缓存引用

---

## 六、Tool Registry 变化

- `deeptutor/tools/builtin/__init__.py`：`BUILTIN_TOOL_TYPES` 移除
  `PartnerReadTool`、`PartnerMemorizeTool`、`PartnerSearchTool`
- 移除 `PARTNER_BUILTIN_TOOL_NAMES`
- 验证：`len(BUILTIN_TOOL_TYPES) == 40`，`BUILTIN_TOOL_TYPES` 中无 `Partner` 类
- `agentic_pipeline` 不再强制/抑制挂载 Partner 工具

---

## 七、测试结果

```
pytest tests/
  3169 passed, 9 skipped
  1 failed  ← 预先存在的品牌文案失败（与本次裁剪无关，见下）
```

**唯一失败**：`tests/api/test_codex_oauth_callback.py::test_codex_callback_endpoint_delivers_without_echoing_secrets`
- 断言 `"Authentication received. You can return to Lumen."`，实际渲染为 `"DeepTutor"`
- 已用 `git stash` 在基线提交上复现同一失败 → **确认为基线已有问题，非本次裁剪引入**（`auth.py` 与测试均未改动）

**验证维度**：

| 验证项 | 结果 |
| --- | --- |
| `deeptutor serve` 启动无 Partner import error | ✅ Uvicorn 启动完成，lifespan 正常 |
| lifespan 正常 | ✅ “Application startup complete.” |
| Tool Registry 正常 | ✅ 40 个工具，无 Partner 工具 |
| memory migration 正常 | ✅ `test_store.py`（v1 迁移）通过 |
| multi_user 正常 | ✅ `tests/multi_user/` 通过 |
| WS 对话 | ✅ `/api/v1/ws` 路由存在（`unified_ws.router`），OpenAPI 240 条路径 |
| 六 Capability smoke test | ✅ 7 个 capability（chat/deep_solve/deep_question/deep_research/math_animator/visualize/mastery_path）import OK |
| pytest | ✅ 3169 passed（1 个基线预存失败） |
| requirements 安装无残留依赖 | ✅ 无 `partners/matrix` 引用，CI workflow 已清理 |

API 路由：OpenAPI 共 **240 条路径**，其中 **0 条 partner 路由**；`/api/v1/partners` 返回 404。

---

## 八、禁止修改清单核对

以下模块**未改动**（`git diff` 无记录）：普通 Chat Tool、Memory Core（仅移除 partner migration 函数）、
MCP、RAG、Book、Capability 主体、Provider、Parsing。

---

## 九、结论

Partner 体系已完整移除，聊天主链路、MCP、RAG、Book、Capability、Provider、Parsing 均不受影响。
净减少 **25,077 行**（103 文件，-25,116/+39），删除 **8 个 IM 平台 SDK / 18 个依赖包**，
清理启动生命周期、CLI 命令、API 路由、Cron 任务、配置 schema 与专属测试。