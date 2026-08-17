# Lumen CLI Skill

> Teach your AI agent to configure, manage, and use Lumen — an intelligent learning platform — entirely through the command line.

## When to Use

Use this skill when the user wants to:
- Set up or configure Lumen
- Chat with Lumen or run a capability (quiz generation, deep research, visualize, mastery path)
- Create, manage, or search knowledge bases
- Create, manage, or run Partners (IM-connected companions)
- Search, install, or manage skills from a hub (ClawHub)
- Inspect or maintain interactive Books
- View or manage learning memory, sessions, or notebooks
- Start the Lumen API server or the full Web app

## Prerequisites

- Python 3.11+
- Lumen installed: `pip install deeptutor` for the full Web app, `pip install deeptutor-cli` for CLI-only, or `pip install -e .` from a source checkout
- Run `deeptutor init` for first-time interactive setup. It walks a guided wizard (ports → LLM → embedding → search → review) and writes the same settings as the Web Settings page under `data/user/settings`. Add `--cli` to skip the ports step for CLI-only use, or `--home <path>` to target a specific workspace.

## Commands

### Chat & Capabilities

```bash
# Interactive REPL
deeptutor chat
deeptutor chat --capability visualize --kb my-kb --tool rag --tool web_search

# One-shot capability execution
deeptutor run chat "Explain Fourier transform"
deeptutor run visualize "Plot the unit circle"

# Capabilities accepted by `run` / `chat -c`:
#   chat, visualize, mastery_path

# Options for `run`:
#   --session <id>         Resume existing session
#   --tool/-t <name>       Enable tool (repeatable)
#   --kb <name>            Knowledge base (repeatable)
#   --notebook-ref <ref>   Notebook reference, "<notebook_id>:<rec1>,<rec2>" (repeatable)
#   --history-ref <id>     Referenced session id (repeatable)
#   --language/-l <code>   Response language (default: en)
#   --config <key=value>   Capability config (repeatable)
#   --config-json <json>   Capability config as JSON
#   --format/-f <fmt>      Output format: rich | json (default: rich)
```

`deeptutor chat` accepts the same `--session / --tool / --kb / --notebook-ref / --history-ref / --language / --config / --config-json` options, plus `--capability/-c <name>` to set the initial capability.

**Tools** for `--tool` / `-t`: user-toggleable tools are `brainstorm`, `web_search`, `reason`. Context-gated tools (`rag`, `code_execution`, `read_source`, `web_fetch`, `github`, `ask_user`, …) auto-mount when their context is present, but can also be force-enabled with `--tool`. The full registered set is shown in the Web UI under **Settings → Tools**.

### Sessions

```bash
deeptutor session list [--limit 20]                 # List sessions
deeptutor session show <id> [--format rich|json]    # View session messages
deeptutor session open <id>                         # Resume session in the REPL
deeptutor session rename <id> --title "..."         # Rename a session
deeptutor session delete <id>                       # Delete a session
```

### System

```bash
deeptutor config show                               # Print resolved configuration
deeptutor serve [--host 0.0.0.0] [--port 8001] [--reload]   # Start the API server
deeptutor start [--home <path>]                     # Launch backend + frontend together
deeptutor init [--cli] [--home <path>]              # Create/update workspace settings
```

## REPL Slash Commands

Inside `deeptutor chat`, use these:

| Command | Effect |
|:---|:---|
| `/quit` | Exit REPL |
| `/session` | Show current session id |
| `/status` | Print the current REPL state |
| `/new` or `/clear` | Start a new session context |
| `/regenerate` or `/retry` | Re-run the last user message |
| `/tool on\|off <name>` | Toggle a tool |
| `/cap <name>` | Switch capability |
| `/kb <name>\|none` | Set or clear knowledge base |
| `/history add <id>` / `/history clear` | Manage history references |
| `/notebook add <ref>` / `/notebook clear` | Manage notebook references |
| `/show last\|<n>` | Expand a captured tool result or thinking block |
| `/refs` | Show all active references |
| `/config show\|set\|clear` | Manage capability config |

## Typical Workflows

**First-time setup:**
```bash
cd DeepTutor
pip install -e .
deeptutor init        # Interactive guided setup (add --cli for CLI-only)
```

**Daily learning:**
```bash
deeptutor chat --kb textbook --tool rag --tool web_search
```

**Build a knowledge base from documents:** create the knowledge base in the Web UI (Settings → Knowledge Bases), then query it from the CLI:
```bash
deeptutor run chat "Explain Newton's third law" --kb physics --tool rag
```

**Generate quiz questions via Mastery Path:**
```bash
deeptutor run mastery_path "Thermodynamics" --kb physics
```

**Run the full Web app locally:**
```bash
deeptutor start       # backend + frontend; Ctrl+C to stop
```
