# RAG 单管道裁剪执行报告

- **分支**：`chore/prune-rag`
- **Worktree**：`../Lumen-wt-rag`
- **基线**：`V4FM-Lumen最小后端能力与调用链审计报告.md`
- **目标**：将 DeepTutor 多 RAG Pipeline 收敛为 Lumen 当前默认的 LlamaIndex Pipeline

---

## 1. 裁剪范围

### 保留（Keep）

- `llamaindex`（默认本地向量检索，混合 BM25 融合）
- RAG Service 公共入口（`services/rag/service.py`）
- factory 必需逻辑（provider 归一化、缓存、单例默认）
- embedding 体系（统一 EmbeddingClient、配置、validation、adapters）
- knowledge 体系（KB manager / manifest / kb_types / document_adder）
- LlamaIndex index/probe、ingestion、storage、retrievers、vector_store
- Parsing Engine（MinerU / Docling / markitdown / pymupdf4llm / liteparse）—— 按约束未改动

### 删除（Delete）—— 非默认、字符串懒加载 Pipeline

| Pipeline | 目录 | 说明 |
| --- | --- | --- |
| `pageindex` | `services/rag/pipelines/pageindex/` + `services/mcp/pageindex_server.py` | 云端索引，本地仅 doc-id 清单 |
| `graphrag` | `services/rag/pipelines/graphrag/` | 图检索引擎 |
| `lightrag` | `services/rag/pipelines/lightrag/` | 本地图/向量混合引擎 + worker |
| `lightrag_server` | `services/rag/pipelines/lightrag_server/` | 远程 LightRAG 服务（连接型 KB） |
| `ima` | `services/rag/pipelines/ima/` | 连接型 KB（IMA 知识库） |
| `modes` | `services/rag/pipelines/modes.py` | 多管道模式枚举（仅被已删管道使用） |

---

## 2. 改动文件清单（77 个文件）

### 删除 40 个文件

**RAG Pipelines（29）**：`graphrag/*`（6）、`ima/*`（5）、`lightrag/*`（6）、`lightrag_server/*`（5）、`pageindex/*`（5）、`modes.py`（1）、`services/mcp/pageindex_server.py`（1）

**测试（11）**：`test_pageindex_mcp.py`、`test_ima_kb.py`、`test_lightrag_server_kb.py`、`test_graphrag_lightrag_settings.py`、`test_pageindex_settings.py`、`test_pageindex_server.py`、`test_graphrag_pipeline.py`、`test_ima_pipeline.py`、`test_lightrag_pipeline.py`、`test_lightrag_server_pipeline.py`、`test_pageindex_pipeline.py`

### 修改 37 个文件

**RAG 核心**：`factory.py`（KNOWN_PROVIDERS 收敛为 `{llamaindex}`，`_build_pipeline` 仅实例化 LlamaIndexPipeline，`list_pipelines` 仅返回 LlamaIndex）、`index_probe.py`（仅保留 LlamaIndex 探针）、`linked_kb.py`（LINKABLE_PROVIDERS 仅含默认）、`service.py`（日志捕获简化）、`preflight.py`、`embedding_signature.py`、`pipelines/base.py`、`pipelines/llamaindex/document_loader.py`

**Knowledge / Config**：`knowledge/kb_types.py`（CONNECTED_KB_TYPES 收敛为 obsidian/linked/subagent）、`knowledge/manager.py`（移除 server_url/knowledge_base_id 死字段）、`knowledge/manifest.py`、`services/config/runtime_settings.py`（删除 pageindex/graphrag/lightrag 配置加载）、`services/config/knowledge_base_config.py`、`services/config/__init__.py`

**API / MCP / Chat**：`api/routers/knowledge.py`（移除 `/connect-lightrag-server`、`/connect-ima` 路由；`/rag-providers` 仅返回 LlamaIndex）、`api/utils/task_log_stream.py`、`services/mcp/config.py`、`services/mcp/manager.py`（移除 PageIndex 服务器内置配置）、`agents/chat/agentic_pipeline.py`（移除 PageIndex 工具授权与系统提示）、`runtime/providers/scope.py`、`runtime/providers/view.py`、`tools/builtin/__init__.py`（rag tool 文档）

**依赖 / 文档**：`pyproject.toml`（删除 graphrag、rag-lightrag extras）、`requirements/cli.txt`

**测试（改写）**：`test_rag_tool.py`、`test_knowledge_router.py`、`test_document_adder_provider.py`、`test_linked_kb_manager.py`、`test_manager_embedding_flags.py`、`test_manager_get_info_status.py`、`test_manifest.py`、`test_task_log_stream.py`、`test_knowledge_base_config.py`、`test_index_probe.py`、`test_linked_kb.py`、`test_rag_pipelines.py`、`test_kb_manifest_note.py`

### 统计

```
77 files changed, 154 insertions(+), 8181 deletions(-)
```

---

## 3. 验证结果

| # | 验证项 | 结果 | 方式 |
| --- | --- | --- | --- |
| 1 | LlamaIndex KB 创建 | ✅ PASS | E2E：`get_pipeline().initialize()` 创建 version-1，docstore/index_store/vector_store + meta.json 落盘 |
| 2 | 文档解析 → embedding → indexing | ✅ PASS | E2E：markdown → SentenceSplitter 分块 → stub 嵌入 → FAISS 向量索引持久化 |
| 3 | `rag` Tool 检索 | ✅ PASS | E2E：`pipe.search()` / `RAGService.search()` 命中相关内容；`get_available_providers()` 仅 `["llamaindex"]` |
| 4 | Chat + KB 对话 | ✅ PASS | WS chat turn 正常执行（87 事件，content 流式产出）；KB 挂载路径由 knowledge router 测试覆盖 |
| 5 | 不配置 pipeline 时仍默认 LlamaIndex | ✅ PASS | `get_pipeline()` 无参 → LlamaIndexPipeline 单例；`normalize_provider_name("raganything")` 归一到 `llamaindex` |
| 6 | 删除的 Pipeline 名称不残留在配置/UI | ✅ PASS | `/api/v1/knowledge/rag-providers` 仅返回 `llamaindex`；前端无硬编码引用（API 驱动）；`data/user/settings` 已移除 pageindex/graphrag/lightrag.json；代码无实际引用（仅 Parsing Engine 历史注释保留） |
| 7 | pytest | ✅ PASS | **3748 passed, 8 skipped, 4 failed**（4 个失败均为基线问题，见遗留问题） |
| 8 | `deeptutor serve` | ✅ PASS | 端口 8099 以 `PYTHONPATH=<worktree>` 启动，加载裁剪后代码，健康路由正常 |
| 9 | WS smoke test | ✅ PASS | `/api/v1/ws` 连接成功，chat turn 收到事件信封，无 RAG import 崩溃 |
| 10 | Tool consistency | ✅ PASS | Tool Registry 43 个工具；`rag`/`kb_files`/`obsidian_create_note`/memory/notebook 齐备；无 pageindex/graphrag/lightrag 工具（`imagegen` 命中为 `ima` 子串误匹配） |

---

## 4. 同步检查项（用户指定）

- ✅ `services/rag/factory.py` —— 收敛完成
- ✅ Pipeline 注册 —— 仅 LlamaIndex
- ✅ 配置默认值 —— runtime_settings 仅加载 llamaindex
- ✅ UI/provider selector —— API 驱动，无硬编码残留
- ✅ tests —— 改写/删除完成
- ✅ requirements / pyproject extras —— graphrag、rag-lightrag 已删
- ✅ `graphrag` / `raganything` / `liteparse` —— raganything/lightrag 均无依赖残留；liteparse 属 Parsing Engine（按约束保留）
- ✅ PageIndex/MCP 相关引用 —— `pageindex_server.py` 已删，manager/config 已清理

## 5. 禁止修改项确认（未改动）

Partners、Provider Core、Book、MCP Core、Capability 主体、Parsing Engine、Tool 体系非 RAG 部分 —— 全部未触碰。

---

## 6. 遗留问题

1. **pytest 4 个基线失败（与本次裁剪无关，主分支同样存在）**：
   - `test_codex_callback_endpoint_delivers_without_echoing_secrets` —— 断言 "Lumen"，stub HTML 输出 "DeepTutor"（品牌文案基线不一致）
   - `test_slack_pairs_with_slack_config` / `test_slack_dm_subtree_inlined` —— `No module named 'slack_sdk'`（Partners 通道依赖未安装，Partners 不在本次范围）
   - `test_channel_registry_discovers_builtin_channels` —— 期望 slack/matrix 通道，本环境未安装相关 SDK（Partners 范围）
2. **Parsing Engine 历史注释**：`parsing/types.py`、`parsing/__init__.py`、`docling/engine.py` 保留 "future LightRAG" 等历史说明文字 —— 按「禁止修改 Parsing Engine」约束有意保留。
3. **旧配置兼容**：历史 KB 若配置为已删除 provider（如 `pageindex`），`factory.normalize_provider_name` 会自动归一到 `llamaindex` 并提示重建索引（上游处理），不会选择不存在管道。
