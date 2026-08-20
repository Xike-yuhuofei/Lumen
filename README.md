<div align="center">

# Lumen: Lifelong Personalized Tutoring





[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/downloads/)
[![Vite](https://img.shields.io/badge/Vite-6-646CFF?style=flat-square&logo=vite&logoColor=white)](https://vite.dev/)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue?style=flat-square)](LICENSE)
[![arXiv](https://img.shields.io/badge/arXiv-2604.26962-b31b1b?style=flat-square&logo=arxiv&logoColor=white)](https://arxiv.org/abs/2604.26962)

[![Discord](https://img.shields.io/badge/Discord-Community-5865F2?style=flat-square&logo=discord&logoColor=white)](https://discord.gg/eRsjPgMU4t)
[![Feishu](https://img.shields.io/badge/Feishu-Group-00D4AA?style=flat-square&logo=feishu&logoColor=white)](./Communication.md)

[Features](#-key-features) · [Get Started](#-get-started) · [Explore](#-explore-lumen) · [CLI](#%EF%B8%8F-lumen-cli--agent-native-interface) · [Ecosystem](#-ecosystem--eduhub--the-skills-community) · [Community](#-community)

</div>

---

> 🤝 **We welcome any kinds of contributing!** See our [Contributing Guide](CONTRIBUTING.md) for branching strategy, coding standards, and how to get started.


### 📰 News

- **2026-04-19** 🎉 20k stars in 111 days! Thank you for the support toward truly personalized, intelligent tutoring.
- **2026-04-10** 📄 Our paper is live on arXiv — read the [preprint](https://arxiv.org/abs/2604.26962) for the design and ideas behind Lumen.
- **2026-02-06** 🚀 10k stars in just 39 days! A huge thank you to our incredible community.
- **2025-12-29** 🎓 Lumen is officially released!

## ✨ Key Features

Lumen is an agent-native learning workspace that connects tutoring, problem solving, quiz generation, research, visualization, and mastery practice in one extensible system.

- **One runtime for every mode** — Chat, Quiz, Research, Visualize, Solve, and Mastery Path run on the same agent loop, so you switch the objective, not the engine, and context moves with the learner.
- **Connected learning context** — Knowledge bases, books, Co-Writer drafts, notebooks, question banks, personas, and Memory stay available across every workflow instead of living in isolated tools.
- **Subagents and Partners** — consult a live coding CLI (Claude Code, Codex, Gemini, Kimi, opencode, or MiMo) or a Partner from any turn (or import their past conversations), and run persistent IM companions on the same brain.
- **Multi-engine knowledge** — versioned RAG libraries across LlamaIndex, PageIndex, GraphRAG, LightRAG, or a linked Obsidian vault, with pluggable document parsing.
- **Extensible tools and skills** — built-in tools, MCP servers, CLI apps, image / video / voice generation models, and installable community skills from EduHub.
- **Inspectable memory** — L1 traces, L2 surface summaries, and L3 synthesis make personalization visible and editable, with a Memory Graph that traces every claim back to its evidence.

---

## 🚀 Get Started

Lumen ships four installation paths. They all share one workspace layout: settings live in `data/user/settings/` under the directory you launch from (or under `LUMEN_HOME` / `lumen start --home` if you set one explicitly). For the full app, the recommended flow is **pick a workspace directory → install → `lumen init` → `lumen start`**.

<details>
<summary><b>Option 1 — Install From PyPI</b> · full local Web app + CLI, no clone required</summary>

Full local Web app + CLI, no clone required. Needs **Python 3.11–3.13**. The packaged Vite frontend is served by `lumen start` (no Node.js required for the PyPI install).

```bash
mkdir -p my-lumen && cd my-lumen
pip install -U lumen
lumen init     # prompts for ports + LLM provider + optional embedding
lumen start    # starts backend + frontend; keep the terminal open
```

`lumen init` prompts for backend port (default `8001`), frontend port (default `3782`), LLM provider / base URL / API key / model, and an optional embedding provider for Knowledge Base / RAG.

After `lumen start`, open the frontend URL printed in the terminal — by default [http://127.0.0.1:3782](http://127.0.0.1:3782). Press `Ctrl+C` in that terminal to stop both backend and frontend. Skipping `lumen init` is fine for a quick trial; the app boots with default ports and empty model settings, configure them later in **Settings → Models**.

</details>

<details>
<summary><b>Option 2 — Install From Source</b> · develop against a checkout</summary>

For development against a checkout. Use **Python 3.11–3.13** and **Node.js 22 LTS** to match CI and Docker.

```bash

# Create a venv (macOS/Linux). Windows PowerShell:
#   py -3.11 -m venv .venv ; .\.venv\Scripts\Activate.ps1
python3 -m venv .venv && source .venv/bin/activate
python -m pip install --upgrade pip

# Install backend + frontend deps
python -m pip install -e .
( cd frontend && npm ci )

lumen init
lumen start --dev
```

`lumen start` builds the local `frontend/` app for production once and reuses it; `--dev` runs Vite with HMR. Config layout, ports, and `Ctrl+C` match Option 1.

<details>
<summary><b>Conda environment</b> (instead of <code>venv</code>)</summary>

```bash
conda create -n lumen python=3.11
conda activate lumen
python -m pip install --upgrade pip
```

</details>

<details>
<summary><b>Optional install extras</b> — dev / partners / matrix</summary>

```bash
pip install -e ".[dev]"             # tests/lint tools
pip install -e ".[partners]"        # Partner IM channel SDKs + MCP client
pip install -e ".[matrix]"          # Matrix channel without E2EE/libolm
pip install -e ".[matrix-e2e]"      # Matrix E2EE; requires libolm
```

</details>

<details>
<summary><b>Frontend dependency tweaks & dev-server troubleshooting</b></summary>

**Changing frontend dependencies:** run `npm install` in `frontend/` to refresh `frontend/package-lock.json`, then commit both `frontend/package.json` and `frontend/package-lock.json`.

**Stuck dev server:** if `lumen start --dev` reports the frontend port is already in use, stop the process listening on that port and retry:

```bash
lumen start --dev
```

</details>

</details>


<details>
<summary><b>Option 4 — CLI Only</b> · no Web UI, from a source checkout</summary>

When you don't need the Web UI. The CLI-only package is installed from a source checkout, not from PyPI.

```bash

# Create a venv (macOS/Linux). Windows PowerShell:
#   py -3.11 -m venv .venv-cli ; .\.venv-cli\Scripts\Activate.ps1
python3 -m venv .venv-cli && source .venv-cli/bin/activate
python -m pip install --upgrade pip

python -m pip install -e ./packaging/lumen-cli
lumen init --cli
lumen chat
```

`lumen init --cli` shares the same `data/user/settings/` layout as the full app but skips the backend/frontend port prompts and defaults embeddings to **off** (choose `Yes` if you plan to use `lumen kb …` or RAG tools). It still writes a complete runtime layout (`system.json`, `auth.json`, `integrations.json`, `model_catalog.json`, `main.yaml`, `agents.yaml`) and still prompts for the active LLM provider and model.

<details>
<summary><b>Common commands</b></summary>

```bash
lumen chat                                          # interactive REPL
lumen chat --capability mastery_path --tool rag --kb my-kb
lumen run chat "Explain Fourier transform"
lumen run mastery_path "Master calculus" --kb math-textbook
lumen config show
```

</details>

The local `lumen-cli` install ships no Web assets or server dependencies. Keep the source checkout around — the editable install points to it. To add the Web app later, install the PyPI package (Option 1) and run `lumen init` + `lumen start` from the same workspace.

</details>

<details>
<summary><b>Code Execution Sandbox (office skills)</b> · running model-generated code for docx / pdf / pptx / xlsx</summary>

The built-in office skills — **docx / pdf / pptx / xlsx** — work by having the
model write a short Python script (`python-docx`, `reportlab`, `openpyxl`, …),
run it through the `exec` / `code_execution` tools, and hand back a download URL.
Those tools mount whenever a sandbox backend is active, which it is **by default**
in every deployment shape:

- **Local (Option 1 / 2) and Docker (Option 3, single container):** a restricted
  subprocess sandbox runs the model's code (on the host locally, or inside the
  container under Docker — the container being its own isolation boundary).
- **docker-compose:** routed instead to a hardened, least-privileged **runner
  sidecar** (`Dockerfile.runner`) via `LUMEN_SANDBOX_RUNNER_URL` — the
  strongest posture, and preferred automatically when present.

The subprocess sandbox is controlled by the `sandbox_allow_subprocess` setting in
`data/user/settings/system.json` (default `true`). Running model-generated code
on your host is a real trust decision — set it to `false` (or export
`LUMEN_SANDBOX_ALLOW_SUBPROCESS=0`) to disable host-side execution, at the
cost of the office skills no longer being able to produce files.

</details>

<details>
<summary><b>Configuration reference</b> — config files under <code>data/user/settings/</code> (JSON/YAML)</summary>

Everything under `data/user/settings/` is plain JSON/YAML. The **Settings** page in the browser is the recommended editor.

| File | Purpose |
|:---|:---|
| `model_catalog.json` | LLM, embedding, and search provider profiles; API keys; active models |
| `system.json` | Backend/frontend ports, public API base, CORS, SSL verification, attachment directory and upload/extraction limits |
| `auth.json` | Optional auth toggle, username, password hash, token/cookie settings |
| `integrations.json` | Optional PocketBase and sidecar integration settings |
| `interface.json` | UI and model output language / theme / sidebar preferences |
| `main.yaml` | Runtime behavior defaults and path injection |
| `agents.yaml` | Capability/tool temperature and token settings |

Project-root `.env` is **not** read as an application config file. For a minimal model setup, open **Settings → Models**, add an LLM profile (Base URL / API key / model name), and save. Add an embedding profile only if you plan to use Knowledge Base / RAG features.

**API keys can be injected through environment variables** instead of being stored in plaintext. `model_catalog.json` keeps each provider's key in its `api_key` field as plaintext, but when that field is **left empty**, the runtime falls back to the provider's environment variable: `GITEE_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`, `DASHSCOPE_API_KEY`, and so on (the LLM and embedding resolvers both read them). Precedence is **profile key in `model_catalog.json` > environment variable** — set `export GITEE_API_KEY=…` and leave the profile `api_key` empty to keep keys out of the config file.

</details>

## 📖 Explore Lumen

Start with the main surfaces you will use day to day: Chat, Partners, My Agents, Co-Writer, Book, Knowledge Center, Learning Space, Memory, and Settings. The tour then covers Multi-User deployments for shared, isolated workspaces.



<details>
<summary><b>🏗️ System architecture</b></summary>



</details>

<details>
<summary><b>💬 Chat — The Agent Loop You Actually Use</b></summary>

Chat is the default capability and where most work begins. A single thread can talk normally, call tools, ground itself in selected knowledge bases, read attachments, generate images, consult subagents, write notebook records, and continue with the same context across turns.



The loop is deliberately simple: the model thinks in rounds, calls tools when useful, observes the results, and finishes with a tool-free message. `ask_user` is special — instead of guessing, the agent can pause the turn, ask a structured clarifying question, and resume once you answer.



User-toggleable tools are `brainstorm`, `web_search`, and `reason`. Contextual tools such as `rag`, `kb_files`, `read_source`, `read_memory`, `write_memory`, `read_skill`, `load_tools`, `exec`, `web_fetch`, `ask_user`, `list_notebook`, `write_note`, and `github` mount automatically when the turn has the right context.

Context comes in two kinds: **sticky session context** (knowledge bases, persona, model, voice) lives on the composer toolbar and persists across turns; **one-time references** (files, chat history, books, notebooks, question bank) come from the `+` menu for a single turn.

Chat is also the launch point for deeper capabilities: **Quiz** for question generation, **Visualize** for charts / diagrams / animations, and — under *More Capabilities* — **Mastery Path** for learning-plan flows.

</details>

<details>
<summary><b>🤝 Partner — Persistent Companions on the Same Brain</b></summary>



Partners are persistent companions with their own soul, model policy, library, memory, and channels. They are not a separate bot engine: every inbound web or IM message becomes a normal agent turn inside a partner-scoped workspace. A partner is "a chat that has a personality and a phone number."



Each partner has a `SOUL.md`, model selection, channels, tool policy, and assigned library. Knowledge bases, skills, and notebooks are copied into `data/partners/<id>/workspace/`, so the same RAG, skill, notebook, and memory tools work without special cases. A partner reads its owner's memory but writes only its own.



The channel layer is schema-driven and can connect to IM platforms such as Feishu, Telegram, Slack, Discord, DingTalk, QQ/NapCat, WeCom, WhatsApp, Zulip, Mattermost, Matrix, Mochat, and Microsoft Teams depending on installed extras and configured credentials.

</details>

<details>
<summary><b>✍️ Co-Writer — Selection-Aware Markdown Drafting</b></summary>



Co-Writer is a split-view Markdown workspace for reports, tutorials, notes, and long-form learning artifacts. Documents autosave and render a live preview (KaTeX math, diagram fences), and can be saved back into notebooks when a draft becomes reusable context.



Its defining idea is **surgical editing**: select a span and ask Lumen to rewrite, expand, or shorten it. The edit agent can ground the change in a knowledge base or web evidence, keeps a trace of its tool calls, and shows every change as an accept/reject diff — so nothing lands until you approve it.

</details>

<details>
<summary><b>📖 Book — Living Books from Your Materials</b></summary>



Book turns selected sources into an interactive **living book** — not a static PDF, but a reading environment built from typed blocks. A book can start from knowledge bases, notebooks, question banks, or chat history; the creation flow proposes a chapter outline before content is generated, so you review the shape instead of accepting a blind one-shot output.



Each chapter compiles into typed blocks — text, callouts, quizzes, flash cards, timelines, code, figures, interactive HTML, concept graphs, deep dives, and user notes — and every page has its own Page Chat. Blocks are editable: insert, move, regenerate, or switch a block's type without rewriting the chapter. Maintenance commands such as `lumen book health` and `lumen book refresh-fingerprints` help detect when source knowledge has drifted from compiled pages.

</details>

<details>
<summary><b>📚 Knowledge Center — Multi-Engine RAG Libraries</b></summary>



Knowledge bases are the document collections behind RAG — they ground Chat turns, Co-Writer edits, Book generation, and Partner conversations. What's distinctive is a **choice of retrieval engines**: **LlamaIndex** (the default, local vector + BM25), **PageIndex** (hosted, reasoning retrieval with page-level citations), **GraphRAG** and **LightRAG** (knowledge-graph retrieval), **LightRAG Server** (retrieval offloaded to an external LightRAG instance you connect over HTTP), **Tencent IMA** (a library you curate in IMA, searched over its OpenAPI), or a linked **Obsidian** vault the tutor reads and writes in place. Each KB is bound to one engine.



Creating a KB, you either **create new** (upload documents and build a fresh index) or **link existing** (reuse an index built elsewhere, read in place with no re-index). Re-indexing writes a new flat `version-N` directory and keeps prior ones, so a working index is never destroyed mid-rebuild. A single document can be removed even from an **error**-state base — dropping a file that failed to parse without a full delete-and-rebuild. Document parsing — Text-only, MinerU, Docling, markitdown, PyMuPDF4LLM, or LiteParse — is chosen in **Settings → Knowledge Base**, with local model downloads off by default. The CLI mirrors the lifecycle with `lumen kb list`, `info`, `create`, `add`, `search`, `set-default`, and `delete`.

</details>

<details>
<summary><b>🌐 Learning Space — Skills, Personas, and Reusable Context</b></summary>



Learning Space is the library and personalization layer — where the things that persist live. **Conversations & Materials** holds your chat history, notebooks, and a question bank (each saved question keeps your answer, the reference answer, and an explanation). **Personalization** holds mastery paths, personas (behavior presets such as *peer*, *research-assistant*, *teacher*), skills (`SKILL.md` playbooks the model reads on demand), **MCP Services** — a curated store of hosted MCP servers you install for yourself in one click, plus any remote server you configure by URL — and **CLI Apps**, command-line tools from the [CLI-Anything](https://github.com/HKUDS/CLI-Anything) catalog that the chat agent calls directly, with each app's own usage guide loaded on demand. Everything here can be reused from Chat, Partners, Co-Writer, and Book.



You don't have to write every skill yourself — **Import from EduHub** browses the community catalog and downloads a skill straight into your library through a security gate (see [Ecosystem](#-ecosystem--eduhub--the-skills-community)).

</details>

<details>
<summary><b>🧠 Memory — Inspectable Personalization</b></summary>



Memory is a file-backed, three-layer system you can read, curate, and audit — deliberately *not* a hidden vector store. **L1** is the workspace mirror plus an append-only event trace (`trace/<surface>/<date>.jsonl`); **L2** is per-surface curated facts (`L2/<surface>.md`); **L3** is cross-surface synthesis (`L3/<profile|recent|scope|preferences>.md`). Because L2 cites L1 and L3 cites L2, nothing in your profile is unaccountable.



The Memory Graph shows the whole pyramid — L3 synthesis at the centre, L2 in the middle ring, L1 traces on the outside — so you can trace any synthesized claim back to the exact raw event behind it. Memory is tracked across `chat`, `notebook`, `quiz`, `kb`, `book`, partner, and `cowriter` surfaces; the consolidator's Update / Audit / Dedup budgets are tuned in **Settings → Memory**.

</details>

<details>
<summary><b>⚙️ Settings — One Control Plane</b></summary>



Settings is the operational control plane, with a live status strip (backend health and resident memory across the process tree) and one card per area: **Appearance** (theme, interface and model output language, code-block styling), **Network** (API base, ports, CORS), **Models** (LLM, Embedding, Search, Text-to-Speech, Speech-to-Text, Image Generation, Video Generation), **Knowledge Base** (document parsing engine), **Chat** (tools, per-capability parameters, attachment caps), **Partners & Agents** (the subagents you can consult from a turn), and **Memory** (the consolidator's budgets).



Most sections use a draft-and-apply flow, so you can test a provider before committing it. Four themes ship in the box — Default, Cream, Dark, and Glass. Project-root `.env` files are intentionally ignored; runtime configuration lives under `data/user/settings/*.json` unless `LUMEN_HOME` or `lumen start --home` points the app elsewhere.

**OpenAI Codex OAuth (experimental).** Picking **OpenAI Codex** under Models → LLM replaces the API-key fields with a browser sign-in that runs against your own ChatGPT plan, so no `OPENAI_API_KEY` is needed. Tokens live only in `data/system/user-secrets/<owner>/private/openai-codex/` — in the multi-container Compose deployment, outside every tree the exec sandbox can reach — and Lumen never reads or modifies your `~/.codex` CLI login. The model list comes from that account's live catalog; signing in publishes the profile but only becomes the active model when no LLM is configured yet. Because a token authorizes one person's plan, the profile is not shareable through user grants — each account signs in for itself, ordinary users included: their card sits under Models → LLM, and the resulting models, catalog, and sign-out stay private to that account.

For a remote deployment, the browser's `localhost` and the server's `localhost` are different machines, so an ordinary reverse proxy alone cannot carry the browser's localhost callback to the server. Use an SSH tunnel as the callback bridge. The tunnel reaches the already-published Web port; the SPA server rewrites only the exact callback path to the public callback broker, and the broker validates `state` before routing to the original OAuth operation. The callback listener remains on the backend loopback, ports `1455` and `1457` are not published, and this path supports the default Docker bridge network.

```bash
ssh -N -L 1455:127.0.0.1:3782 <ssh-user>@<server-host>
```

If Lumen reports fallback callback port `1457`, use:

```bash
ssh -N -L 1457:127.0.0.1:3782 <ssh-user>@<server-host>
```

Run only the one command that matches the actual callback port; never run both. `3782` is only the example Web port: it is the configured frontend/container port reported as `callback_forward_port`. That value does not guarantee that the same port is listening on the SSH host's `127.0.0.1`. If Docker or Podman publishes a different host port, or a reverse proxy listens on a different port, replace only the right-hand target port (`3782` above) with the Web port actually listening on the SSH host's `127.0.0.1`; keep the left-hand callback port as `1455` or `1457`. `<server-host>` is the SSH host whose loopback owns that listening port. If the browser URL names a reverse proxy or load balancer, replace it with the correct SSH frontend host.

The CLI prints the tunnel command and then immediately tries to open the browser. On a remote deployment, keep the authorization page open without completing it, establish the printed tunnel in another terminal, and only then continue authorization.

Remote-topology detection has a localhost boundary. If Web itself is reached through an SSH or IDE localhost forward, the browser cannot tell that the server is remote. For the current Web operation, leave its authorization page unfinished, read `redirect_uri` in that operation's authorize URL to identify callback port `1455` or `1457`, and create the second tunnel from that local port to the actual Web port. Alternatively, cancel that Web operation and start a new one with the CLI; the CLI output belongs to the new operation and must not be used for the existing Web operation. Quota errors and catalog failures are reported as-is and never fall back to a paid provider. This compatibility path is experimental: the upstream interface may change.

</details>

<details>
<summary><b>👥 Multi-User — Shared Deployments</b> · optional auth, isolated per-user workspaces</summary>

Authentication is **off by default** — Lumen runs single-user. Turn it on and one `data/` tree hosts an admin workspace, isolated per-user workspaces, and partner workspaces side by side:

```text
data/
├── user/                    # Admin workspace + global settings
├── users/<uid>/             # Per-user scope: chat history, memory, notebooks, KBs
├── partners/<id>/workspace/ # Partner (synthetic-user) scope
├── cli-apps/                # Installed CLI apps, mounted read-only into the sandbox
└── system/                  # auth · grants · audit · user-secrets/<owner> (OAuth tokens)
```

The **first registered user becomes admin** and owns model catalogs, provider credentials, shared knowledge bases, skills, and per-user grants. Everyone else gets an isolated workspace and a redacted Settings page — admin-assigned models, KBs, and skills show up as scoped, read-only options, never as raw API keys.

**Enable it:** turn auth on in `data/user/settings/auth.json`, restart `lumen start`, register the first admin at `/register`, then add users from `/admin/users` and assign models, KBs, skills, partners, tool/MCP/CLI-app policy, and code-execution access through grants.

> PocketBase stays a single-user integration — keep `integrations.pocketbase_url` blank for multi-user deployments unless you've wired up an external user store.

</details>

## ⌨️ Lumen CLI — Agent-Native Interface

One `lumen` binary, two ways in: an interactive **REPL** for people who live in the terminal, and structured **JSON** for other agents that drive Lumen as a tool. Same capabilities, tools, and knowledge bases either way.

<details>
<summary><b>Drive it yourself</b></summary>

`lumen chat` opens an interactive REPL; `lumen run <capability> "<message>"` fires a single turn and exits. Both speak the same `--capability`, `--tool`, `--kb`, and `--config` flags.

```bash
lumen chat                                              # interactive REPL
lumen chat --capability mastery_path --kb my-kb --tool rag   # Learn (mode.learn); CLI compat name mastery_path
lumen run chat "Explain the Fourier transform" --tool rag --kb textbook
lumen run mastery_path "Master a calculus topic" --kb textbook   # Learn (mode.learn)
```

Everything the Web app does is here too — knowledge bases (`kb`), sessions (`session`), partners (`partner`), skills (`skill`), notebooks, memory, and config. Full list below.

</details>

<details>
<summary><b>Let an agent drive it</b></summary>

Lumen is built to be *operated by another agent*. Add `--format json` to any `run` and each turn streams **NDJSON — one event per line** (`content`, `tool_call`, `tool_result`, `done`, …), every line tagged with its `session_id`. Runs are headless-safe: an `ask_user` pause with no TTY auto-resolves with an empty reply instead of hanging.

```bash
# One shot, machine-readable — Learn (mode.learn; CLI compat name mastery_path)
lumen run mastery_path "Master calculus" --kb math-textbook --format json

# Chain turns in one stateful session — capture the id, reuse it
SID=$(lumen run mastery_path "Master vector calculus" --format json \
  | jq -r 'select(.type=="done").session_id')
lumen run chat "Summarize that session" --session "$SID" --format json
```

The repo ships a root [`SKILL.md`](SKILL.md) — a ~150-line handover doc that teaches any tool-using LLM the whole surface in one read. Hand it to Claude Code, Codex, or OpenCode (they pick up `SKILL.md` automatically), or wrap `lumen run` as a tool in a LangChain / AutoGen loop.

</details>

<details>
<summary><b>Command reference</b></summary>

| Command | Description |
|:---|:---|
| `lumen init` | Create or update `data/user/settings` for the current workspace |
| `lumen start [--home PATH] [--dev]` | Launch backend + frontend together; `--dev` enables frontend HMR |
| `lumen serve [--port PORT]` | Start only the FastAPI backend |
| `lumen run <capability> <message>` | Run a single capability turn (`chat`; Learn = `mode.learn`, CLI compat token `mastery_path`); add `--format json` for NDJSON output |
| `lumen chat` | Interactive REPL with capability, tool, KB, notebook, and history controls |
| `lumen session list/show/open/rename/delete` | Manage shared sessions |
| `lumen config show` | Print configuration summary |

</details>

<details>
<summary><b>CLI-only distribution</b></summary>

The CLI-only package lives in `packaging/lumen-cli`. In this checkout, install it from source:

```bash
python -m pip install -e ./packaging/lumen-cli
```

It isn't published to PyPI yet, so the main [Get Started](#-get-started) section keeps the source-install path.

</details>

## 🧩 Ecosystem — EduHub & the Skills Community

Lumen skills use the open **Agent-Skills** format — a folder with a `SKILL.md` playbook (YAML frontmatter + Markdown) and optional reference files. Nothing about it is Lumen-specific, so any registry that speaks the format becomes a source for your library. Lumen ships with **EduHub** — our own education-focused skill registry — wired in as the default hub.

<details>
<summary><b>EduHub — Lumen's skill ecosystem</b></summary>

**EduHub** is the community hub Lumen launched for sharing teaching-oriented agent skills — Socratic tutors, flashcard builders, essay feedback, exam blueprints, concept explainers, and more. It is built into Lumen, so there's nothing to configure: a bare slug or an `eduhub:` prefix resolves to it.

**Find and install** — in the browser, open **Learning Space → Skills → Import from EduHub** to browse the catalog and download a skill straight into your library.

**Publish your own** — package a `SKILL.md` and share it back to the community through the web UI, picking a track and tags, then uploading your skill.

EduHub is also a standalone, ClawHub-compatible registry, so agents that aren't Lumen (Claude Code, Codex, …) can use it directly through the `eduhub` CLI — `npx eduhub install socratic-tutor`.

</details>

<details>
<summary><b>The import safety gate</b></summary>

Whatever the source, every import passes the **same safety gate** before anything touches your workspace:

- the registry's **security verdict** is checked first — flagged packages are refused unless you pass `--allow-unverified`;
- archives are extracted defensively (zip-slip / zip-bomb guards) behind a text/script **suffix whitelist**, so binaries never land in the workspace;
- frontmatter is normalized to Lumen's schema and `always:` is **stripped**, so a downloaded skill can never force itself into every system prompt;
- provenance — hub, version, verdict, and install time — is written to `.hub-lock.json` for audits and updates.

In multi-user deployments, installing is admin-only: a new skill lands in the admin catalog and stays invisible to other users until a grant assigns it, so an admin can vet it before rolling it out.

</details>

<details>
<summary><b>Also compatible with ClawHub</b></summary>

Because Lumen speaks the open Agent-Skills format, **[ClawHub](https://clawhub.ai/)** works as a first-class source too — it's built in alongside EduHub. Pick it with the hub prefix in the web UI.

Add more registries in `settings/skill_hubs.json`: a `type: "clawhub"` entry points at any compatible HTTP API (EduHub and ClawHub both speak it), `type: "command"` wraps whatever fetch CLI a registry ships, and `"default"` chooses the hub used for bare slugs. All of them feed the same import gate.

</details>

## 🌐 Community

### 📮 Contact

Lumen is an open-source project led by [Bingxi Zhao](https://github.com/pancacake) within the [HKUDS](https://github.com/HKUDS) Group, and it iterates in a **fully open-source form**, built together with the community. So far, we **DO NOT** have paid online products of any form. Feel free to reach out at **bingxizhao39@gmail.com** for discussions, ideas, or collaboration.

### 🙏 Appreciation

Heartfelt thanks to [**Chao Huang**](https://sites.google.com/view/chaoh), director of the Data Intelligence Lab @ HKU, and to our HKUDS labmates for their warm support — especially [**Jiahao Zhang**](https://github.com/zzhtx258), [**Zirui Guo**](https://github.com/LarFii), and [**Xubin Ren**](https://github.com/Re-bin). We're also deeply grateful to the **open-source community**: your stars, issues, pull requests, and discussions shape Lumen every single day.

Lumen also stands on the shoulders of outstanding open-source projects that gave us both tools and inspiration:

| Project | Role / Inspiration |
|:---|:---|
| [**LlamaIndex**](https://github.com/run-llama/llama_index) | RAG pipeline and document-indexing backbone |
| [**nanobot**](https://github.com/HKUDS/nanobot) | Ultra-lightweight agent engine that powered the original TutorBot *(HKUDS)* |
| [**LightRAG**](https://github.com/HKUDS/LightRAG) | Simple & fast RAG *(HKUDS)* |
| [**AutoAgent**](https://github.com/HKUDS/AutoAgent) | Zero-code agent framework *(HKUDS)* |
| [**AI-Researcher**](https://github.com/HKUDS/AI-Researcher) | Automated research pipeline *(HKUDS)* |
| [**OpenClaw**](https://github.com/openclaw/openclaw) | Open agent gateway and skill ecosystem behind ClawHub |
| [**Codex**](https://github.com/openai/codex) | Agent-native coding CLI that inspired our CLI workflow |
| [**Claude Code**](https://github.com/anthropics/claude-code) | Agentic coding CLI that inspired the Lumen agent loop |
| [**ManimCat**](https://github.com/Wing900/ManimCat) | AI-driven math animation generation for Math Animator |

### 🗺️ Roadmap & Contribute

We want Lumen to keep iterating and improving — and ultimately to become a gift we give back to the open-source community. Our **roadmap** is updated continuously; vote on items there or propose new ones. If you'd like to contribute, see the [**Contributing Guide**](CONTRIBUTING.md) for branching strategy, coding standards, and how to get started.

<div align="center">

We hope Lumen becomes a gift for the community. 🎁

</div>

<div align="center">

Licensed under the [Apache License 2.0](LICENSE).

</div>
