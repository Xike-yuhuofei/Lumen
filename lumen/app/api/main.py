from contextlib import asynccontextmanager
import logging
import sys

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from lumen.shared._util.brand import PRODUCT_NAME
from lumen.shared._util.logging import configure_logging
from lumen.shared._util.observability import (
    begin_request,
    end_request,
)
from lumen.shared._util.observability import (
    configure as configure_observability,
)
from lumen.shared._util.observability import (
    configure_export as configure_observability_export,
)
from lumen.shared._util.path_service import get_path_service
from lumen.shared.config import (
    ensure_runtime_settings_files,
    export_runtime_settings_to_env,
    load_auth_settings,
    load_system_settings,
)
from lumen.shared.config.origins import normalize_origins

ensure_runtime_settings_files()
export_runtime_settings_to_env(overwrite=True)
configure_logging()
# Local telemetry backend (span JSONL + retention). No-op when disabled —
# telemetry must never become a hard dependency of the server.
configure_observability()
# Optional external exporters (OTLP / metrics summary), read from env.
# No-op when unconfigured — local-first default.
configure_observability_export()
logger = logging.getLogger(__name__)


class _SuppressWsNoise(logging.Filter):
    """Suppress noisy uvicorn logs for WebSocket connection churn."""

    _SUPPRESSED = ("connection open", "connection closed")

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        return not any(f in msg for f in self._SUPPRESSED)


logging.getLogger("uvicorn.error").addFilter(_SuppressWsNoise())

CONFIG_DRIFT_ERROR_TEMPLATE = (
    "Configuration Drift Detected: Capability tool references {drift} are not "
    "registered in the runtime tool registry. Register the missing tools or "
    "remove the stale tool names from the capability manifests."
)


def validate_tool_consistency():
    """
    Validate that the generic chat capability only references tools that are
    actually registered in the runtime ``ToolRegistry``.

    ``chat`` is the only capability; its tool surface is the canonical
    ``CHAT_OPTIONAL_TOOLS`` set.
    """
    try:
        from lumen.runtime.agent_loop.providers.legacy.agentic_pipeline import CHAT_OPTIONAL_TOOLS
        from lumen.runtime.tools.registry import get_tool_registry

        tool_registry = get_tool_registry()
        available_tools = set(tool_registry.list_tools())

        referenced_tools = set(CHAT_OPTIONAL_TOOLS)

        drift = referenced_tools - available_tools
        if drift:
            raise RuntimeError(CONFIG_DRIFT_ERROR_TEMPLATE.format(drift=drift))
    except RuntimeError:
        logger.exception("Configuration validation failed")
        raise
    except Exception:
        logger.exception("Failed to load configuration for validation")
        raise


def _build_cors_settings() -> dict[str, object]:
    """Build CORS settings for both localhost and remote Docker deployments."""
    system_settings = load_system_settings()
    auth_settings = load_auth_settings()
    frontend_port = str(system_settings["frontend_port"])
    extra_origins = normalize_origins(
        [system_settings["cors_origin"], system_settings["cors_origins"]]
    )
    origins = [
        f"http://localhost:{frontend_port}",
        f"http://127.0.0.1:{frontend_port}",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]
    for origin in extra_origins:
        if origin not in origins:
            origins.append(origin)

    # Auth is disabled by default. In that local/single-user mode, mirror the
    # pre-v1.3.8 behavior and allow remote Docker/LAN origins out of the box.
    # When auth is enabled, require explicit CORS_ORIGIN(S) for credentialed
    # cross-origin requests.
    allow_origin_regex = None if auth_settings["enabled"] else r"https?://.*"
    mode = "explicit" if auth_settings["enabled"] else "permissive"
    return {
        "allow_origins": origins,
        "allow_origin_regex": allow_origin_regex,
        "mode": mode,
    }


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifecycle management
    Gracefully handle startup and shutdown events, avoid CancelledError
    """
    # Execute on startup
    logger.info("Application startup")

    # Validate configuration consistency
    validate_tool_consistency()

    # Initialize LLM client early so OPENAI_* env vars are available before
    # any downstream provider integrations start.
    try:
        from lumen.shared._util.llm import get_llm_client

        llm_client = get_llm_client()
        logger.info(f"LLM client initialized: model={llm_client.config.model}")
    except Exception as e:
        logger.warning(f"Failed to initialize LLM client at startup: {e}")

    try:
        from lumen.runtime.stream.event_bus import get_event_bus

        event_bus = get_event_bus()
        await event_bus.start()
        logger.info("EventBus started")
    except Exception as e:
        logger.warning(f"Failed to start EventBus: {e}")

    # Migrate any v1 memory files (PROFILE.md / SUMMARY.md) into a
    # backup folder so the v2 three-layer subsystem starts clean.
    try:
        from lumen.shared.memory.store import migrate_v1_if_needed

        backup = migrate_v1_if_needed()
        if backup is not None:
            logger.info("v1 memory archived to %s", backup)
    except Exception as e:
        logger.warning(f"v1 memory migration failed: {e}")

    # The Plugin Kernel is the single formal dependency-assembly entry.
    # The production Profile (Runtime + Shared + mode.learn) is booted here
    # and disposed on shutdown.  A boot failure is fatal: without the kernel
    # there is no runtime to serve turns.
    lumen_root = None
    try:
        from lumen.bootstrap import LumenBootstrap, attach_bootstrap
        from lumen.profile import PRODUCTION_PLUGINS

        # Keep the booted assembly as the active one so the WS turn runtime
        # routes Learn requests into mode.learn and generic turns into
        # runtime.agent_loop.
        lumen_bootstrap = LumenBootstrap()
        lumen_root = await lumen_bootstrap.boot()
        attach_bootstrap(lumen_bootstrap)
        app.state.lumen_root = lumen_root
        app.state.lumen_bootstrap = lumen_bootstrap
        logger.info("Lumen Plugin Kernel booted: %s", [p.manifest.id for p in PRODUCTION_PLUGINS])
    except Exception:
        logger.exception("Lumen Plugin Kernel bootstrap failed — refusing to start")
        raise

    yield

    # Execute on shutdown
    logger.info("Application shutdown")

    # Phase 5 — dispose the Plugin Kernel assembly (releases service
    # registrations, background tasks, and registered cleanups).
    if lumen_root is not None:
        try:
            from lumen.bootstrap import detach_bootstrap

            detach_bootstrap()
            await lumen_root.dispose()
            logger.info("Lumen Plugin Kernel disposed")
        except Exception as e:
            logger.warning(f"Failed to dispose Lumen Plugin Kernel: {e}")
        finally:
            app.state.lumen_root = None
            app.state.lumen_bootstrap = None

    # Close pooled LLM SDK clients so their keep-alive sockets and transports
    # are released deterministically instead of waiting for interpreter GC.
    try:
        from lumen.shared._util.llm.provider_factory import close_runtime_provider_pool

        await close_runtime_provider_pool()
        logger.info("LLM provider pool closed")
    except Exception as e:
        logger.warning(f"Failed to close LLM provider pool: {e}")

    try:
        from lumen.runtime.agent_loop.engine.client import close_agentic_client_pool

        await close_agentic_client_pool()
        logger.info("Agentic LLM client pool closed")
    except Exception as e:
        logger.warning(f"Failed to close agentic LLM client pool: {e}")

    # Stop EventBus
    try:
        from lumen.runtime.stream.event_bus import get_event_bus

        event_bus = get_event_bus()
        await event_bus.stop()
        logger.info("EventBus stopped")
    except Exception as e:
        logger.warning(f"Failed to stop EventBus: {e}")


app = FastAPI(
    title=f"{PRODUCT_NAME} API",
    version="1.0.0",
    lifespan=lifespan,
    # Disable automatic trailing slash redirects to prevent protocol downgrade issues
    # when deployed behind HTTPS reverse proxies (e.g., nginx).
    # Without this, FastAPI's 307 redirects may change HTTPS to HTTP.
    # See: https://github.com/HKUDS/Lumen/issues/112
    redirect_slashes=False,
)

# Access logging is funneled through this one middleware. uvicorn's own
# per-request access log is disabled on every launch path (run_server.py via
# access_log=False; the launcher and Docker via `--no-access-log`), so routine
# 200s — the chatty frontend polling of /settings, /tools, /knowledge/list,
# etc. — never reach the logs. Only non-200s are surfaced, since those are the
# ones worth seeing.
#
# The `lumen.access` logger gets its own INFO stdout handler rather than
# leaning on the root handlers: the root console handler runs at the global log
# level (WARNING by default), which would swallow these INFO access lines.
# propagate=False keeps them from also printing through root if the global
# level is ever lowered to INFO/DEBUG.
_access_logger = logging.getLogger("lumen.access")
if not any(getattr(h, "_lumen_access_handler", False) for h in _access_logger.handlers):
    _access_handler = logging.StreamHandler(sys.stdout)
    _access_handler.setLevel(logging.INFO)
    _access_handler.setFormatter(logging.Formatter("%(message)s"))
    _access_handler._lumen_access_handler = True  # type: ignore[attr-defined]
    _access_logger.addHandler(_access_handler)
    _access_logger.setLevel(logging.INFO)
    _access_logger.propagate = False


@app.middleware("http")
async def selective_access_log(request, call_next):
    response = await call_next(request)
    if response.status_code != 200:
        _access_logger.info(
            '%s - "%s %s HTTP/%s" %d',
            request.client.host if request.client else "-",
            request.method,
            request.url.path,
            request.scope.get("http_version", "1.1"),
            response.status_code,
        )
    return response


@app.middleware("http")
async def request_id_context(request, call_next):
    """Bind one request_id per HTTP request and echo it on the response.

    The id is pinned into the telemetry + logging context for the whole
    request, so REST logs (including the selective access log above) can be
    correlated back to a single request. Turns started inside this scope
    (WS/CLI/SDK) inherit the request_id via contextvars copy.
    """
    request_id = request.headers.get("X-Request-ID") or None
    token = begin_request(request_id)
    try:
        response = await call_next(request)
    finally:
        end_request(token)
    response.headers.setdefault("X-Request-ID", request_id or "")
    return response


_cors_settings = _build_cors_settings()
logger.info(
    "CORS configured: mode=%s allow_origins=%s allow_origin_regex=%s",
    _cors_settings["mode"],
    _cors_settings["allow_origins"],
    _cors_settings["allow_origin_regex"],
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_settings["allow_origins"],
    allow_origin_regex=_cors_settings["allow_origin_regex"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize user directories on startup
try:
    from lumen.app.setup import init_user_directories

    init_user_directories()
except Exception:
    # Fallback: just create the main directory if it doesn't exist
    user_dir = get_path_service().get_public_outputs_root()
    if not user_dir.exists():
        user_dir.mkdir(parents=True)

# Import routers only after runtime settings are initialized.
# Some router modules load YAML settings at import time.
from lumen.app.api.routers import (
    attachments,
    auth,
    knowledge,
    mastery_path,
    memory,
    notebook,
    outputs,
    personas,
    sessions,
    settings,
    unified_ws,
)
from lumen.app.api.routers import tools as tools_router

# Auth router is public — login/logout/register/status require no token
app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
app.include_router(outputs.router, prefix="/api/outputs", tags=["outputs"])

# All other routers require a valid session when AUTH_ENABLED=true.
# require_auth is a no-op when AUTH_ENABLED=false, so this is safe for local use.
from lumen.app.api.routers.auth import require_auth  # noqa: E402

_auth = [Depends(require_auth)]

app.include_router(
    knowledge.router, prefix="/api/v1/knowledge", tags=["knowledge"], dependencies=_auth
)

app.include_router(
    mastery_path.router,
    prefix="/api/v1/learning",
    tags=["mastery-path"],
    dependencies=_auth,
)

app.include_router(
    notebook.router, prefix="/api/v1/notebook", tags=["notebook"], dependencies=_auth
)
app.include_router(memory.router, prefix="/api/v1/memory", tags=["memory"], dependencies=_auth)

app.include_router(
    sessions.router, prefix="/api/v1/sessions", tags=["sessions"], dependencies=_auth
)

# Public UI-settings read (auth pages bootstrap the interface language
# before a session exists, so GET /api/v1/settings/ui must not be gated
# by _auth). Mounted first so the path resolves here, not on the gated
# settings router below.
app.include_router(
    settings.public_router,
    prefix="/api/v1/settings",
    tags=["settings"],
)
app.include_router(
    settings.router, prefix="/api/v1/settings", tags=["settings"], dependencies=_auth
)

app.include_router(
    personas.router, prefix="/api/v1/personas", tags=["personas"], dependencies=_auth
)
app.include_router(tools_router.router, prefix="/api/v1/tools", tags=["tools"], dependencies=_auth)
app.include_router(
    attachments.router,
    prefix="/api/attachments",
    tags=["attachments"],
    dependencies=_auth,
)

# Unified WebSocket endpoint — auth is checked inside the handler (WebSockets
# cannot use FastAPI dependencies in the standard way)
app.include_router(unified_ws.router, prefix="/api/v1", tags=["unified-ws"])


@app.get("/")
async def root():
    return {"message": f"Welcome to {PRODUCT_NAME} API"}


@app.get("/api/v1/health")
async def health():
    """Unauthenticated liveness/readiness probe for production deployments.

    Returns the Lumen version, whether the Plugin Kernel assembly was booted
    (the server refuses to start if it was not), and a minimal storage probe so
    an orchestrator (systemd / launchd / Kubernetes / Docker HEALTHCHECK) can
    distinguish "process up" from "service ready".  Never returns credentials,
    configuration values, or provider secrets.
    """
    from lumen.__version__ import __version__

    kernel_booted = bool(getattr(app.state, "lumen_root", None))
    db_ok = False
    try:
        from lumen.runtime.session.sqlite_store import get_sqlite_session_store

        store = get_sqlite_session_store()
        if store is not None:
            db_ok = bool(await store.ping())
    except Exception:
        db_ok = False

    ready = kernel_booted and db_ok
    return {
        "status": "ok" if ready else "degraded",
        "service": PRODUCT_NAME,
        "version": __version__,
        "kernel": "booted" if kernel_booted else "not_booted",
        "storage": "ok" if db_ok else "error",
    }


if __name__ == "__main__":
    from lumen.app.api.run_server import main as run_server_main

    run_server_main()
