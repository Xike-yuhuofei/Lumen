# Provider 与 CLI 精简执行报告

- 分支：`chore/prune-provider`
- Worktree：`../Lumen-wt-provider`
- 基线：`V4FM-Lumen最小后端能力与调用链审计报告.md`
- 日期：2026-08-16

## 1. 概述

本轮在独立 Worktree 中完成两项精简，未触碰禁止修改区域（RAG、Partners 实现、Book Core、Capability、MCP、Parsing、Chat Runtime、Tool Registry 非 Provider 部分）：

1. **LLM Provider 注册元数据精简**：`provider_registry.py` 的 `ProviderSpec` 从约 40 个收敛至 **14 个**。
2. **CLI 非运行必需命令裁剪**：移除属于 DeepTutor 管理生态的命令，完整保留 `serve` / `start` / `run` / `chat` / `config` / `session` / `init` 启动与运行链。

不主动重构 LLM Factory；核心 Provider backend 仅移除被源码证明不可达/仅元数据层的冷门条目。

## 2. Provider 精简

### 2.1 保留（14 个）

| 类别 | Provider |
| --- | --- |
| Direct（用户自给全部配置，无自动探测） | `custom`（OpenAI-compatible）、`custom_anthropic`、`azure_openai` |
| Gateway（按 api_key / api_base 探测，可路由任意模型） | `openrouter` |
| Standard（按模型名关键字匹配） | `anthropic`、`openai`、`openai_codex`、`github_copilot`、`codebuddy`、`deepseek`、`gemini`、`dashscope` |
| Local | `vllm`、`ollama` |

同时收敛 `PROVIDER_ALIASES`：保留 openai/anthropic-compatible、azure、google→gemini、claude→anthropic、github-copilot、openai-codex、codebuddy/workbuddy 等主流别名；删除指向已裁剪 Provider 的别名。

### 2.2 删除（冷门 / 非 Lumen 所需）

`nvidia_nim`、`atlascloud`、`edenai`、`novita`、`orcarouter`、`aihubmix`、`siliconflow`、`volcengine`、`byteplus`、`zhipu`、`moonshot`、`minimax`、`mistral`、`groq`、`qianfan`、`stepfun`、`xiaomi_mimo`、`lm_studio`、`llama_cpp`、`lemonade`、`ovms` 等。

> 说明：以上条目在 V4FM 审计中确认大部分仅是 `ProviderSpec` 元数据（`backend` 多为 `openai_compat`，无独立 backend 实现），删除不会移除任何真实 backend 代码。

### 2.3 重点检查项结论

- **ProviderSpec → backend 映射**：删除项均为 `openai_compat` 复用型；真实 backend（`provider_core/*`）无依赖被删元数据，未删除任何 backend 文件。
- **user settings**：用户实际 `model_catalog.json` 使用 `custom` binding（本机 OpenAI 兼容接口），不受影响。
- **model selection**：`model_selection/llm.py` 通过 `find_by_name()` 动态取 label，自动反映裁剪后注册表，无硬编码残留。
- **auth**：`openai_codex`/`github_copilot`/`codebuddy` OAuth 保留；删除项不涉及 OAuth 流程。
- **provider factory**：`llm/factory.py` 的 presets 由 `PROVIDERS` 动态生成，删除项自动从 `API_PROVIDER_PRESETS` / `LOCAL_PROVIDER_PRESETS` 消失。
- **UI model selector**：settings router `_provider_choices()` 仅输出 14 个保留 Provider，删除项不残留。
- **默认配置**：默认目录加载正常（`custom` / `gpt-5.6-sol`），绑定全部可 resolve。

### 2.4 连带清理

- `deeptutor_cli/init_wizard.py`：`FEATURED_LLM_PROVIDERS` 与 `LLM_FALLBACK_MODELS` 移除 zhipu/moonshot/siliconflow 等，避免初始化向导出现已删 Provider。
- 测试同步更新：`test_provider_registry.py`、`test_settings_router.py`、`test_agentic_client_provider_kwargs.py`、`test_provider_runtime.py`、`test_openai_compat_reasoning_content.py`（移除依赖 moonshot 元数据的行为用例）。

## 3. CLI 裁剪

### 3.1 保留

- `serve`（`deeptutor serve → api/main.py`）
- `start`（backend + frontend launcher）
- `run`（单轮运行任意 Capability）
- `chat`（交互 REPL）
- `config`（配置检查）
- `session`（会话管理）
- `init`（初始化向导）
- 启动链所需基础设施：`common.py`、`chat.py`、`config_cmd.py`、`init_cmd.py`、`session_cmd.py`、`_tool_result.py`

### 3.2 删除（仅属 DeepTutor 管理生态）

- `partner.py`、`plugin.py`、`skill.py`、`skill_login.py`、`skill_prompts.py`
- `kb.py`、`memory.py`、`notebook.py`
- `book.py`
- `provider_cmd.py`

以及对应测试：`test_kb_cli.py`、`test_notebook_cli.py`、`test_provider_cli.py`、`test_codebuddy_login.py`、`test_skill_login.py`，并更新 `test_chat_cli.py`、`test_docs_contract.py`、`test_skill_publish_flow.py`。

文档同步：`README.md`、`deeptutor_cli/README.md`、`SKILL.md` 移除已删命令说明。

> `run` 的 `--kb` / `--notebook-ref` 属于运行时上下文输入参数（传给 turn 的 knowledge_bases / notebook_references），不是管理子命令，予以保留。

## 4. 验证结果

| 验证项 | 结果 |
| --- | --- |
| pytest | **3900 passed, 9 skipped**；仅剩 4 个基线既有失败（见 §5） |
| 默认模型正常加载 | 通过（`custom` / `gpt-5.6-sol`） |
| custom OpenAI-compatible | 通过（LLMFactory → `OpenAICompatProvider`） |
| 保留 Provider 均可正确 resolve | 通过（14/14） |
| 已删除 Provider 不残留 UI/config | 通过（settings/UI/model_selection/factory presets 均无残留） |
| model_selection | 通过（动态反映注册表） |
| `deeptutor serve` | 通过（启动、settings/ui、openapi 264 路径） |
| `deeptutor start` | 命令注册与 launcher 导入通过；完整前端启动需 `npm run build`（worktree 无 dist），后端与 serve 同源已覆盖 |
| WS 对话 | 通过（`/api/v1/ws`，start_turn → result 事件流） |
| 六个 Capability smoke | **6/6 通过**（chat、deep_solve、deep_question、deep_research、visualize、mastery_path 均产出 result） |

Smoke 采用隔离 `DEEPTUTOR_HOME` + 本地 OpenAI-compatible mock server（`custom` binding），未触碰真实数据与密钥。

## 5. 基线既有失败（与本轮无关）

以下 4 项在基线仓库同样失败，属环境/依赖/品牌文案问题，不在本轮范围：

1. `test_codex_oauth_callback`：测试断言 “Lumen” 而页面输出 “DeepTutor”（品牌文案不一致）。
2. `test_partners_channel_schema` × 2：缺 `slack_sdk`（未安装 `[partners]` 依赖）。
3. `test_channel_manager`：Partners 通道发现依赖未装齐（`slack_sdk` 等）。

## 6. 变更规模

29 个文件变更，**+112 / -3214 行**（净删约 3100 行），其中：
- Provider 元数据层：约 -260 行
- CLI 管理命令与测试：约 -2300 行
- 文档与测试对齐：其余
