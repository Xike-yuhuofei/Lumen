# Lumen 2.0.0 — Production Deployment Runbook

> **Status: PRODUCTION RELEASE** — reproducible deployment for the
> **Production-Validated Release Baseline** (tag `production-validated-v1`,
> commit `c624aea0`), released as **Lumen 2.0.0** (tag `v2.0.0` /
> `production-release-v1`, commit `321a05cc`).

This runbook lets a fresh environment deploy Lumen 2.0.0 from source (or from
the built wheel) in the same form that was production-validated. It covers
install, configuration, start/stop/restart, healthcheck, data/log/telemetry
lifecycle, upgrade, and rollback.

---

## 1. Deployment form

Lumen runs as a single **FastAPI (uvicorn) process** behind a supervisor:

- **Entry point**: `lumen.app.api.main:app`
- **Server**: `uvicorn` (bind `127.0.0.1:8001` by default; expose via your own
  reverse proxy for TLS)
- **Runtime home**: `LUMEN_HOME` — the workspace root that owns
  `<LUMEN_HOME>/data` (settings, SQLite, knowledge bases, memory, logs,
  telemetry). Defaults to the process working directory when unset.
- **Production agent loop**: P1 `agent_loop.langgraph_thin` (elected by
  `PRODUCTION_PROFILE`). Rollback to Legacy P0 with
  `LUMEN_AGENT_LOOP_PROVIDER=legacy`.

Assets in this directory:

| File | Purpose |
|---|---|
| `lumenctl` | start / stop / restart / status / health / logs control script |
| `lumen.service` | systemd unit template (Linux) |
| `com.lumen.server.plist` | launchd plist template (macOS) |
| `.env.production.example` | production environment template (no secrets) |

---

## 2. Install

Requirements: **Python 3.11–3.13** (3.14 is rejected by `pyproject.toml`).
For the full Web app from source you also need **Node.js 22 LTS** only at build
time.

### 2.1 From source (recommended for this repo)

```bash
git clone https://github.com/Xike-yuhuofei/Lumen.git
cd Lumen
git checkout v2.0.0            # exact release
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e ".[server]"
```

### 2.2 From the built wheel (preferred for air-gapped / release archives)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install dist/lumen-2.0.0-py3-none-any.whl
# Optional: enable OTLP protobuf export to Phoenix / OTel Collector
pip install "lumen[otel]"
```

> The wheel is built with the packaged frontend (`lumen_web`), so no Node.js is
> needed at runtime. `langgraph`/`langchain-core` are runtime deps (production
> default P1 agent loop). `opentelemetry-proto` is optional via `lumen[otel]` —
> required only when `LUMEN_OTEL_ENCODING=protobuf`.

---

## 3. Configure

### 3.1 Runtime home and settings

Pick a workspace root, e.g. `/srv/lumen`:

```bash
mkdir -p /srv/lumen
cd /srv/lumen
LUMEN_HOME=/srv/lumen
```

On first start the server auto-creates the settings skeleton
(`data/user/settings/*`) via `ensure_runtime_settings_files()`. Configure the
active LLM profile in **Settings → Models** (web UI) or edit
`data/user/settings/model_catalog.json` directly.

**Credentials are read ONLY from the process environment** — never from config
files. Convention: `<BINDING>_API_KEY` (e.g. `DEEPSEEK_API_KEY`,
`ZHIPU_API_KEY`, `GITEE_API_KEY`, `OPENAI_API_KEY`, `CODEXMANAGER_API_KEY`).
`model_catalog.json` intentionally stores no keys (stripped on load/save).

### 3.2 Environment file

Copy `deploy/.env.production.example` → `/srv/lumen/.env.production`, fill in
real values, `chmod 600`, and source it in the supervisor unit (see §4).

```bash
cp deploy/.env.production.example /srv/lumen/.env.production
chmod 600 /srv/lumen/.env.production
```

Key variables:

| Variable | Default | Meaning |
|---|---|---|
| `LUMEN_HOME` | cwd | runtime workspace root |
| `LUMEN_BIND_HOST` / `LUMEN_BIND_PORT` | `127.0.0.1` / `8001` | server binding |
| `<BINDING>_API_KEY` | — | LLM provider credentials |
| `LUMEN_TELEMETRY_EXPORTERS` | — | `otlp` / `metrics_summary` (optional) |
| `LUMEN_OTEL_ENDPOINT` | `:4318/v1/traces` | Phoenix/Collector OTLP/HTTP endpoint |
| `LUMEN_OTEL_ENCODING` | `json` | `protobuf` required by Phoenix |
| `AUTH_ENABLED` | off | multi-user auth toggle |

---

## 4. Start / stop / restart / healthcheck

### 4.1 `lumenctl` (any supervisor)

```bash
export LUMEN_HOME=/srv/lumen
./deploy/lumenctl start          # daemonized, pid + log under LUMEN_HOME
./deploy/lumenctl status
./deploy/lumenctl health         # HTTP 200 + {"status":"ok"} required
./deploy/lumenctl restart
./deploy/lumenctl stop
./deploy/lumenctl logs
```

`health` probes `GET /api/v1/health` which is **unauthenticated** and reports
`{status, service, version, kernel, storage}` — `status: "ok"` means the Plugin
Kernel booted AND the SQLite store is reachable.

### 4.2 systemd (Linux)

See `lumen.service`. After installing, create the env file
`/etc/lumen/lumen.env` (chmod 600), then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now lumen
systemctl status lumen
systemctl restart lumen
systemctl stop lumen
```

### 4.3 launchd (macOS)

See `com.lumen.server.plist`. `KeepAlive=true` restarts on failure;
`RunAtLoad` starts at login/boot.

---

## 5. External dependencies

| Dependency | Config | Fault isolation |
|---|---|---|
| **LLM Provider** | `<BINDING>_API_KEY` env | Turn fails fast with a persisted `error`; never crashes the server, never silently falls back |
| **Phoenix / OTLP Collector** | `LUMEN_TELEMETRY_EXPORTERS=otlp`, `LUMEN_OTEL_ENDPOINT=…/v1/traces`, `LUMEN_OTEL_ENCODING=protobuf` | Best-effort export, single exit `try/except`; exporter unreachable → `export.otlp.errors` metric, local telemetry continues, main business unaffected |

Local telemetry (span JSONL under `data/user/logs/telemetry/`) is always
written, so diagnosis is preserved even when external exporters are down.

---

## 6. Data, logs, and telemetry lifecycle

Everything lives under `LUMEN_HOME`:

```
<LUMEN_HOME>/data/
├── user/
│   ├── chat_history.db          # SQLite (sessions/messages/turns/events)
│   ├── settings/                # runtime JSON/YAML config
│   ├── workspace/               # memory, notebook, skills, knowledge
│   └── logs/
│       ├── lumen.log            # application log (rotating)
│       ├── telemetry/<date>.jsonl   # span telemetry (daily retention)
│       └── metrics/             # optional metrics summaries
├── knowledge_bases/             # KB config + indexed versions
└── system/                      # auth / grants / audit / user-secrets
```

- **Permissions**: run the service under a dedicated OS user (`lumen`); the
  data tree is owned by that user. Settings files are world-readable where
  they carry no secrets; `data/system/user-secrets/` (OAuth tokens) is private.
- **Lifecycle**: application log rotates (10 MB × 5); span telemetry rotates
  daily (30-day retention); metrics rotate daily (7-day retention);
  `turn_events` follow the session lifecycle.
- **Backup**: stop the service and copy `data/` (files + single SQLite). All
  state is file-backed.

---

## 7. Upgrade

1. Back up `data/` (see §6) and the current `__version__`.
2. Stop the service: `./deploy/lumenctl stop` (or `systemctl stop lumen`).
3. Install the new wheel / checkout the new tag into the same venv:
   `pip install dist/lumen-2.1.0-py3-none-any.whl`.
4. Start: `./deploy/lumenctl start`.
5. Verify: `./deploy/lumenctl health` → `status: "ok"` with the new
   `version`; run one WS turn; confirm telemetry exports.

SQLite migrations run idempotently at startup — the same `data/` tree is
carried forward.

## 8. Rollback

1. Stop the service.
2. Reinstall the previous version:
   `pip install dist/lumen-2.0.0-py3-none-any.whl` (or checkout the prior tag).
3. Start and verify `health` returns the previous `version`.
4. If the forward `data/` tree was modified by the newer version, restore the
   pre-upgrade backup to guarantee an exact prior-state replay.

**Rollback point**: every release tag (e.g. `v2.0.0`) is a safe rollback
point; the frozen `production-validated-v1` tag is the earliest production
rollback target in this line.

---

## 9. Verification checklist after deployment

- [ ] `lumenctl health` → `200`, `status: "ok"`
- [ ] One WS turn completes (`start_turn` → `done`, `status=completed`)
- [ ] Session/turn persisted in `data/user/chat_history.db`
- [ ] Telemetry spans appear in `data/user/logs/telemetry/<date>.jsonl`
- [ ] If OTLP configured: spans appear in Phoenix / Collector
- [ ] `lumen.log` shows no unhandled tracebacks
