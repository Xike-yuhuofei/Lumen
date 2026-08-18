"""Runtime session — persistent turn store and turn orchestration."""

from lumen.runtime.session.base_session_manager import BaseSessionManager
from lumen.runtime.session.contract import SessionService
from lumen.runtime.session.plugin import SessionPlugin
from lumen.runtime.session.protocol import SessionStoreProtocol
from lumen.runtime.session.sqlite_store import (
    SQLiteSessionStore,
    get_sqlite_session_store,
    make_imported_session_id,
)
from lumen.runtime.session.turn_runtime import TurnRuntimeManager, get_turn_runtime_manager


def get_session_store() -> SessionStoreProtocol:
    """
    Return the active session store backend.

    The local SQLiteSessionStore is the single supported backend (zero-config,
    per-user database files under the user workspace).
    """
    return get_sqlite_session_store()


__all__ = [
    "BaseSessionManager",
    "SessionService",
    "SessionPlugin",
    "SessionStoreProtocol",
    "SQLiteSessionStore",
    "TurnRuntimeManager",
    "get_session_store",
    "get_sqlite_session_store",
    "get_turn_runtime_manager",
    "make_imported_session_id",
]
