# Lumen CLI

Agent-first 的命令行界面。两条核心路径：

- **`run`** — 单次执行任意 capability（为 agent 调用设计）
- **`chat`** — 交互式 REPL（为人类设计）

## 安装

```bash
# 仅 CLI（本地源码安装，含 RAG / 文档解析 / 各家 LLM provider SDK）
git clone https://github.com/HKUDS/DeepTutor.git
cd DeepTutor
python3 -m venv .venv-cli
source .venv-cli/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ./packaging/deeptutor-cli
deeptutor init --cli

# CLI + Web/API 服务
pip install deeptutor
deeptutor init

# 源码开发
pip install -e .
deeptutor init

# 可选附加组件
pip install -e ".[partners]"       # Partners 渠道 SDK + MCP 客户端
pip install -e ".[all]"            # 全部依赖（含开发工具）
```

`deeptutor init --cli` 和普通 `deeptutor init` 使用同一套 `data/user/settings/` 配置目录；区别是 `--cli` 不询问 Web 后端/前端端口，仍会创建 `system.json`、`auth.json`、`integrations.json`、`model_catalog.json`、`main.yaml` 和 `agents.yaml`，并继续询问 LLM 配置。Embedding 配置默认跳过；如果要使用 RAG 或知识库，请在向导里选择配置 embedding，或稍后编辑 `data/user/settings/model_catalog.json`。

Windows PowerShell 可使用：

```powershell
py -3.11 -m venv .venv-cli
.\.venv-cli\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ./packaging/deeptutor-cli
deeptutor init --cli
```

---

## `run` — 执行 Capability

统一入口，单次执行任意 capability。Agent 只需掌握这一个命令。

```bash
deeptutor run <capability> <message> [options]
```

### 内置 Capability

| Capability | 说明 |
|------------|------|
| `chat` | 对话（默认，可挂载工具） |
| `visualize` | 生成图表、图解、Mermaid 或 HTML 可视化 |
| `mastery_path` | 掌握式学习路径与测评循环 |

### 选项

| 选项 | 缩写 | 说明 |
|------|------|------|
| `--tool` | `-t` | 启用工具（可多次指定）：`rag`, `web_search`, `code_execution`, `reason`, `brainstorm` |
| `--kb` | | 挂载知识库 |
| `--language` | `-l` | 回复语言（默认 `en`） |
| `--session` | | 继续已有会话 |
| `--config` | | capability 配置 `key=value`（可多次指定） |
| `--config-json` | | capability 配置（JSON 字符串） |
| `--notebook-ref` | | 笔记本引用 |
| `--history-ref` | | 引用历史会话 |
| `--format` | `-f` | 输出格式：`rich`（默认）\| `json` |

### 示例

```bash
# 对话
deeptutor run chat "什么是傅里叶变换？" -l zh

# 掌握式学习（含测评循环）
deeptutor run mastery_path "线性代数" --kb math-textbook -l zh

# 可视化
deeptutor run visualize "画出注意力机制的数据流图" --config render_mode=mermaid

# 掌握式学习
deeptutor run mastery_path "带我系统掌握特征值和特征向量"

# JSON 输出（适合 agent 解析）
deeptutor run mastery_path "线性代数基础" --kb math-textbook -f json
```

---

## `chat` — 交互式 REPL

进入多轮对话界面，在 REPL 内通过 `/` 命令切换 capability、工具、知识库等。

```bash
deeptutor chat [options]
```

| 选项 | 说明 |
|------|------|
| `--session` | 恢复已有会话 |
| `--tool`, `-t` | 预启用工具 |
| `--capability`, `-c` | 初始 capability（默认 `chat`） |
| `--kb` | 预挂载知识库 |
| `--language`, `-l` | 回复语言 |

### REPL 内置命令

| 命令 | 说明 |
|------|------|
| `/quit` | 退出 |
| `/session` | 显示当前 session ID |
| `/new` | 新建会话 |
| `/tool on\|off <name>` | 启用/关闭工具 |
| `/cap <name>` | 切换 capability |
| `/kb <name>\|none` | 切换知识库 |
| `/history add <id>\|clear` | 管理历史引用 |
| `/notebook add <ref>\|clear` | 管理笔记本引用 |
| `/regenerate`（别名 `/retry`） | 重跑上一条用户消息 |
| `/show last\|<n>` | 展开被截断的工具结果或折叠的思考过程 |
| `/refs` | 查看当前设置 |
| `/config show\|set\|clear` | 管理 capability 配置 |

回答生成期间按 `Ctrl-C` 会取消当前 turn 并回到输入提示符;模型通过
`ask_user` 提问时,会在终端内渲染选项卡片并等待输入(非交互式 stdin
下自动提交空回复,turn 不会挂起)。

---

## `serve` — 启动 API 服务

```bash
deeptutor serve [--host 0.0.0.0] [--port 8001] [--reload]
```

`deeptutor serve` 需要完整 Web/API 依赖；如果你是通过本地 `./packaging/deeptutor-cli` 安装的 CLI-only 包，请先卸载本地 CLI 包并切换到 `pip install -U deeptutor`。

---

## 资源管理命令

### `session` — 会话

```bash
deeptutor session list [--limit 20]
deeptutor session show <id>
deeptutor session open <id>                      # 进入 REPL 继续对话
deeptutor session rename <id> --title "新标题"
deeptutor session delete <id>
```

### `config` — 配置

```bash
deeptutor config show
```

## 典型工作流

```bash
# 1. 在 Web 界面创建知识库 calculus（或使用已有知识库）

# 2. 掌握式学习（含测评）
deeptutor run mastery_path "微积分" --kb calculus -l zh

# 3. 查看会话记录
deeptutor session list
```
