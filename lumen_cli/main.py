"""CLI entry point for the standalone ``lumen-cli`` package."""

from __future__ import annotations

from pathlib import Path

import typer

from lumen.app.mode import RunMode, set_mode
from lumen.shared._util.brand import PRODUCT_NAME
from lumen.shared._util.logging import configure_logging

from .chat import register as register_chat
from .common import build_turn_request, console, maybe_run
from .config_cmd import register as register_config
from .init_cmd import register as register_init
from .session_cmd import register as register_session

set_mode(RunMode.CLI)
configure_logging()

app = typer.Typer(
    name="lumen",
    help=f"{PRODUCT_NAME} CLI – agent-first interface for capabilities, tools, and knowledge.",
    no_args_is_help=True,
    add_completion=False,
)

chat_app = typer.Typer(help="Interactive chat REPL.")
config_app = typer.Typer(help="Inspect configuration.")
session_app = typer.Typer(help="Manage shared sessions.")

app.add_typer(chat_app, name="chat")
app.add_typer(config_app, name="config")
app.add_typer(session_app, name="session")

register_chat(chat_app)
register_config(config_app)
register_session(session_app)
register_init(app)


@app.command("run")
def run_capability(
    capability: str = typer.Argument(
        ...,
        help=(
            "Capability name (e.g. chat, mode.learn; mastery_path is the CLI compatibility name)."
        ),
    ),
    message: str = typer.Argument(..., help="Message to send."),
    session: str | None = typer.Option(None, "--session", help="Existing session id."),
    tool: list[str] = typer.Option([], "--tool", "-t", help="Enabled tool(s)."),
    kb: list[str] = typer.Option([], "--kb", help="Knowledge base name."),
    notebook_ref: list[str] = typer.Option([], "--notebook-ref", help="Notebook references."),
    history_ref: list[str] = typer.Option([], "--history-ref", help="Referenced session ids."),
    language: str = typer.Option("en", "--language", "-l", help="Response language."),
    config: list[str] = typer.Option([], "--config", help="Capability config key=value."),
    config_json: str | None = typer.Option(
        None, "--config-json", help="Capability config as JSON."
    ),
    fmt: str = typer.Option("rich", "--format", "-f", help="Output format: rich | json."),
) -> None:
    """Run any capability in a single turn (agent-first entry point)."""
    from lumen.app.facade import LumenApp

    from .common import run_turn_and_render

    request = build_turn_request(
        content=message,
        capability=capability,
        session_id=session,
        tools=tool,
        knowledge_bases=kb,
        language=language,
        config_items=config,
        config_json=config_json,
        notebook_refs=notebook_ref,
        history_refs=history_ref,
    )
    maybe_run(run_turn_and_render(app=LumenApp(), request=request, fmt=fmt))


@app.command()
def start(
    home: Path | None = typer.Option(None, "--home", help="Runtime workspace root."),
    dev: bool = typer.Option(
        False,
        "--dev",
        help="Use the Next.js development server for frontend work.",
    ),
) -> None:
    """Launch backend + frontend together. Source installs default to production."""
    from lumen.app.launcher import start as start_web

    start_web(home=home, dev=dev)


@app.command()
def serve(
    host: str = typer.Option("0.0.0.0", help="Bind address."),
    port: int | None = typer.Option(None, help="Port number."),
    reload: bool = typer.Option(False, help="Enable auto-reload for development."),
) -> None:
    """Start the Lumen API server."""
    import asyncio
    import sys

    set_mode(RunMode.SERVER)
    if port is None:
        from lumen.app.setup import get_backend_port

        port = get_backend_port()

    # Windows: uvicorn defaults to SelectorEventLoop which does not support
    # asyncio.create_subprocess_exec.  Switch to ProactorEventLoop so that
    # child-process APIs (used by Math Animator renderer, etc.) work correctly.
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

    try:
        import uvicorn
    except ImportError:
        console.print(
            "[bold red]Error:[/] API server dependencies not installed.\nRun: pip install -U lumen"
        )
        raise typer.Exit(code=1)

    from lumen.shared.config import HTTP_KEEP_ALIVE_TIMEOUT, get_ws_max_size

    # ws_max_size tracks the configured chat-attachment total so base64
    # uploads fit in one WS frame (uvicorn defaults to 16MB).
    uvicorn.run(
        "lumen.app.api.main:app",
        host=host,
        port=port,
        reload=reload,
        reload_excludes=["frontend/*", "data/*"] if reload else None,
        ws_max_size=get_ws_max_size(),
        timeout_keep_alive=HTTP_KEEP_ALIVE_TIMEOUT,
    )


def main() -> None:
    app()


if __name__ == "__main__":
    main()
