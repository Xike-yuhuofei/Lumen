"""Single-user identity and access helpers for Lumen.

Lumen runs as one local deployment account (the local admin). This module is
the consolidated home for the single-user machinery:
identity models, path resolution, the request-local current-user context, the
knowledge-base / model / skill / tool access helpers and the auth user store.

Everything resolves to the single admin workspace under
``<runtime-home>/data``; the per-user workspaces (``data/users/<uid>``),
grants, arbitrary-access RBAC and any notion of a second account are gone.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
import json
import logging
import os
from pathlib import Path
import secrets
import stat
import threading
from typing import Any, Iterator, Literal

from fastapi import HTTPException

from .runtime_home import get_runtime_home

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

Role = Literal["admin", "user"]
ScopeKind = Literal["admin", "user"]


@dataclass(frozen=True, slots=True)
class UserRecord:
    id: str
    username: str
    role: Role = "user"
    created_at: str = ""
    disabled: bool = False
    # Avatar marker: "" (deterministic fallback), "icon:<name>:<color>" for a
    # picked icon, or "img:<version>" when the user uploaded an image (the
    # version is bumped on every upload so clients can cache-bust).
    avatar: str = ""

    def public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "username": self.username,
            "role": self.role,
            "created_at": self.created_at,
            "disabled": self.disabled,
            "avatar": self.avatar,
        }


@dataclass(frozen=True, slots=True)
class UserScope:
    kind: ScopeKind
    user_id: str
    root: Path

    @property
    def cache_key(self) -> str:
        return f"{self.kind}:{self.user_id}:{self.root.resolve()}"


@dataclass(frozen=True, slots=True)
class CurrentUser:
    id: str
    username: str
    role: Role
    scope: UserScope

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    def public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "username": self.username,
            "role": self.role,
            "is_admin": self.is_admin,
        }


@dataclass(frozen=True, slots=True)
class KnowledgeResource:
    id: str
    name: str
    base_dir: Path
    source: Literal["admin", "user"]
    assigned: bool = False
    read_only: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def physical_name(self) -> str:
        return self.name


LOCAL_ADMIN_ID = "local-admin"
LOCAL_ADMIN_USERNAME = "local"

# ---------------------------------------------------------------------------
# Path resolution for the single local deployment user
# ---------------------------------------------------------------------------

PROJECT_ROOT = get_runtime_home()
ADMIN_WORKSPACE_ROOT = PROJECT_ROOT / "data"
SYSTEM_ROOT = ADMIN_WORKSPACE_ROOT / "system"
USER_SECRETS_DIRNAME = "user-secrets"

_path_services: dict[str, Any] = {}


def admin_scope() -> UserScope:
    return UserScope(kind="admin", user_id=LOCAL_ADMIN_ID, root=ADMIN_WORKSPACE_ROOT.resolve())


def local_admin_user() -> CurrentUser:
    return CurrentUser(
        id=LOCAL_ADMIN_ID,
        username=LOCAL_ADMIN_USERNAME,
        role="admin",
        scope=admin_scope(),
    )


def get_path_service_for_scope(scope: UserScope) -> Any:
    from deeptutor.services.path_service import PathService

    key = scope.cache_key
    service = _path_services.get(key)
    if service is None:
        service = PathService(workspace_root=scope.root)
        _path_services[key] = service
    return service


def get_admin_path_service() -> Any:
    return get_path_service_for_scope(admin_scope())


def get_current_path_service() -> Any:
    """The path service for the current scope.

    Single-user mode: the current scope is always the admin workspace.
    When there is no request context (CLI runs, background jobs, tests),
    falls back to the default singleton so callers that patch
    ``PathService.get_instance()`` keep working.
    """
    from deeptutor.services.path_service import PathService

    if get_current_user_or_none() is None:
        return PathService.get_instance()
    return get_admin_path_service()


def get_owner_path_service() -> Any:
    """The path service of the human account that owns the current scope.

    Single-user mode: the owner is always the local admin, so this is the
    admin workspace. Owner-keyed assets (OAuth credentials, above all) resolve
    here.
    """
    return get_admin_path_service()


def owner_secrets_dir(owner_id: str) -> Path:
    """Secrets directory of a *named* owner, independent of the request scope.

    Needed because not every reader runs inside a request: an MCP connection
    task resolves its own server's credentials long after the turn that created
    it, and must address them by the owner it was opened for rather than by
    whoever happens to be current.

    ``data/system`` is the one branch of the tree the sandbox runner does not
    mount, so credentials that authorize a *person* — OAuth refresh tokens
    above all — belong here rather than inside a workspace subtree.
    """
    # SYSTEM_ROOT is read per call so a monkey-patched root (tests) is honored.
    secrets_root = SYSTEM_ROOT / USER_SECRETS_DIRNAME
    owner_dir = secrets_root / (owner_id or LOCAL_ADMIN_ID)
    owner_dir.mkdir(parents=True, exist_ok=True)
    for path in (secrets_root, owner_dir):
        os.chmod(path, stat.S_IRWXU)
    return owner_dir.resolve()


def get_owner_secrets_dir() -> Path:
    """Owner-private directory for secrets the sandbox must never see.

    Single-user mode: the owner is always the local admin.
    """
    return owner_secrets_dir(LOCAL_ADMIN_ID)


def current_owner_id() -> str:
    """Id of the account owning the current scope.

    Single-user mode: always the local admin.
    """
    return LOCAL_ADMIN_ID


@contextmanager
def user_context(user: CurrentUser) -> Iterator[None]:
    token = set_current_user(user)
    try:
        yield
    finally:
        reset_current_user(token)


# ---------------------------------------------------------------------------
# Request-local current identity context
# ---------------------------------------------------------------------------

_current_user: ContextVar[CurrentUser | None] = ContextVar("deeptutor_current_user", default=None)


def set_current_user(user: CurrentUser) -> Token[CurrentUser | None]:
    """Install the current identity. Returns the ContextVar reset token."""
    return _current_user.set(user)


def reset_current_user(token: Token[CurrentUser | None]) -> None:
    """Restore the identity that was current before ``set_current_user``."""
    _current_user.reset(token)


def get_current_user() -> CurrentUser:
    """The current identity, falling back to the local admin."""
    return _current_user.get() or local_admin_user()


def get_current_user_or_none() -> CurrentUser | None:
    """The installed current identity, or ``None`` outside a request context."""
    return _current_user.get()


def user_from_token_payload(payload: Any | None) -> CurrentUser:
    """Any authenticated identity resolves to the single local admin."""
    return local_admin_user()


# ---------------------------------------------------------------------------
# Knowledge-base resolution (single-user mode)
# ---------------------------------------------------------------------------

ADMIN_PREFIX = "admin:kb:"
USER_PREFIX = "user:kb:"
DEFAULT_KB_ALIASES = {"", "default", "current", "selected", "默认", "默认知识库", "当前知识库"}


@lru_cache(maxsize=128)
def _manager_for(base_dir: str) -> Any:
    from deeptutor.knowledge.manager import KnowledgeBaseManager

    return KnowledgeBaseManager(base_dir=base_dir)


def current_kb_base_dir() -> Path:
    return get_admin_path_service().get_knowledge_bases_root()


def admin_kb_base_dir() -> Path:
    return get_admin_path_service().get_knowledge_bases_root()


def current_kb_manager() -> Any:
    return _manager_for(str(current_kb_base_dir().resolve()))


def admin_kb_manager() -> Any:
    return _manager_for(str(admin_kb_base_dir().resolve()))


def _strip_resource_prefix(value: str) -> tuple[str | None, str]:
    raw = str(value or "").strip()
    if raw.startswith(ADMIN_PREFIX):
        return "admin", raw[len(ADMIN_PREFIX) :]
    if raw.startswith(USER_PREFIX):
        return "user", raw[len(USER_PREFIX) :]
    return None, raw


def resolve_kb(kb_ref: str, *, require_write: bool = False) -> KnowledgeResource:
    """Resolve a KB reference to a concrete resource.

    Single-user mode: both ``admin:kb:`` and ``user:kb:`` prefixes address the
    same admin workspace, and the admin workspace is always writable.
    """
    _requested_source, name = _strip_resource_prefix(kb_ref)
    manager = admin_kb_manager()
    resolved = _resolve_default_or_name(manager, name)
    return KnowledgeResource(
        id=f"admin:kb:{resolved}",
        name=resolved,
        base_dir=admin_kb_base_dir(),
        source="admin",
        assigned=False,
        read_only=False,
    )


def _resolve_default_or_name(manager: Any, name: str) -> str:
    requested = str(name or "").strip()
    names = manager.list_knowledge_bases()
    if requested and requested in names:
        return requested
    if requested.lower() in DEFAULT_KB_ALIASES:
        default_kb = manager.get_default()
        if default_kb and default_kb in names:
            return default_kb
        raise HTTPException(status_code=404, detail="No default knowledge base is configured")
    raise HTTPException(status_code=404, detail=f"Knowledge base '{requested}' not found")


def manager_for_resource(resource: KnowledgeResource) -> Any:
    return _manager_for(str(resource.base_dir.resolve()))


def list_visible_knowledge_bases() -> list[dict[str, Any]]:
    """Every KB in the admin workspace (single-user: nothing is hidden)."""
    manager = admin_kb_manager()
    return [
        {
            "id": f"admin:kb:{name}",
            "name": name,
            "source": "admin",
            "assigned": False,
            "read_only": False,
            "provenance_label": "Admin workspace",
        }
        for name in manager.list_knowledge_bases()
    ]


def assert_writable(kb_ref: str) -> KnowledgeResource:
    return resolve_kb(kb_ref, require_write=True)


def resolve_for_rag(kb_ref: str | None) -> KnowledgeResource | None:
    if not kb_ref:
        return None
    return resolve_kb(kb_ref, require_write=False)


def resolve_kb_metadata(kb_ref: str | None) -> dict[str, Any] | None:
    """KB metadata (``type`` / ``vault_path`` / …) for ``kb_ref``."""
    if not kb_ref:
        return None
    try:
        resource = resolve_kb(str(kb_ref), require_write=False)
    except HTTPException:
        return None
    manager = _manager_for(str(resource.base_dir.resolve()))
    return manager.get_metadata(resource.name)


def resolve_kb_manifest(
    kb_ref: str | None,
    *,
    limit: int = 20,
    pattern: str = "",
) -> Any | None:
    """Document inventory for ``kb_ref`` (``None`` if inaccessible)."""
    from deeptutor.knowledge.manifest import build_manifest

    if not kb_ref:
        return None
    try:
        resource = resolve_kb(str(kb_ref), require_write=False)
    except HTTPException:
        return None
    manager = _manager_for(str(resource.base_dir.resolve()))
    entry = manager.get_kb_entry(resource.name)
    if entry is None:
        return None
    return build_manifest(
        name=resource.name,
        kb_dir=resource.base_dir / resource.name,
        entry=entry,
        limit=limit,
        pattern=pattern,
    )


# ---------------------------------------------------------------------------
# Model access (single-user mode — unrestricted)
# ---------------------------------------------------------------------------


def admin_catalog_service() -> Any:
    from lumen.shared.config.model_catalog import ModelCatalogService

    return ModelCatalogService(path=get_admin_path_service().get_settings_file("model_catalog"))


def admin_catalog() -> dict[str, Any]:
    return admin_catalog_service().load()


def redacted_model_access(user_id: str | None = None) -> dict[str, list[dict[str, Any]]]:
    """Model access in redacted row shape. Single-user: the admin has none."""
    return {"llm": []}


def allowed_llm_options() -> dict[str, Any]:
    """LLM option list for the current user (single-user: the full catalog)."""
    from deeptutor.services.model_selection import list_llm_options

    return list_llm_options(admin_catalog())


def has_capability_access(capability: str, user_id: str | None = None) -> bool:
    """Whether the user has at least one usable model (single-user: always)."""
    return True


def apply_allowed_llm_selection(selection: dict[str, Any] | None) -> dict[str, Any] | None:
    """Allow only admin-granted LLM selections (single-user: any model)."""
    return selection


# ---------------------------------------------------------------------------
# Owner-bound LLM profile resolution (single-user mode)
# ---------------------------------------------------------------------------


def owner_catalog_service() -> Any:
    """Model catalog of the account that owns the current scope.

    Single-user mode: the owner is always the local admin, so this is the
    shared deployment catalog.
    """
    from lumen.shared.config.model_catalog import ModelCatalogService

    return ModelCatalogService.get_instance(
        get_owner_path_service().get_settings_file("model_catalog")
    )


def personal_llm_rows() -> list[dict[str, Any]]:
    """Personal models in the row shape ``redacted_model_access`` returns.

    Single-user mode: there are no separate "personal" rows.
    """
    return []


def merge_personal_llm_profiles(catalog: dict[str, Any]) -> dict[str, Any]:
    """``catalog`` plus the current owner's personal LLM profiles.

    Single-user mode: nothing to overlay — the input is returned untouched.
    """
    return catalog


# ---------------------------------------------------------------------------
# Skill visibility guards (single-user mode — always allowed)
# ---------------------------------------------------------------------------


def assigned_skill_ids(user_id: str | None = None) -> set[str]:
    return set()


def assigned_skill_infos(user_id: str | None = None) -> list[dict[str, Any]]:
    return []


def assigned_skill_detail(name: str) -> dict[str, Any] | None:
    return None


def assert_skill_allowed(name: str) -> None:
    """Single-user mode: the local admin is always allowed, so a no-op."""


# ---------------------------------------------------------------------------
# Tool and exec access (single-user mode — unrestricted)
# ---------------------------------------------------------------------------


def allowed_optional_tools() -> set[str] | None:
    """Whitelist of user-toggleable tool names, ``None`` = unrestricted."""
    return None


def allowed_mcp_tools() -> set[str] | None:
    """Whitelist of MCP (deferred) tool names, ``None`` = unrestricted."""
    return None


def exec_override() -> bool | None:
    """Per-user exec override: ``None`` follows the deployment policy."""
    return None


# ---------------------------------------------------------------------------
# Auth user store (single local deployment)
# ---------------------------------------------------------------------------

# Serialises writes to USERS_FILE so a concurrent burst of /register requests
# cannot all see ``not users`` and each promote themselves to admin.
_USERS_WRITE_LOCK = threading.Lock()

AUTH_DIR = SYSTEM_ROOT / "auth"
USERS_FILE = AUTH_DIR / "users.json"
SECRET_FILE = AUTH_DIR / "auth_secret"
LEGACY_USERS_FILE = PROJECT_ROOT / "data" / "user" / "auth_users.json"
LEGACY_SECRET_FILE = PROJECT_ROOT / "data" / "user" / "auth_secret"


def new_user_id() -> str:
    from uuid import uuid4

    return f"u_{uuid4().hex}"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_record(
    username: str,
    value: Any,
    *,
    default_role: Role = "user",
) -> dict[str, Any] | None:
    if isinstance(value, str):
        return {
            "id": _new_uuid(),
            "hash": value,
            "role": default_role,
            "created_at": utc_now(),
            "disabled": False,
            "avatar": "",
        }
    if not isinstance(value, dict):
        return None
    hashed = str(value.get("hash") or value.get("password_hash") or "")
    if not hashed:
        return None
    role = str(value.get("role") or default_role)
    if role not in {"admin", "user"}:
        role = default_role
    return {
        "id": str(value.get("id") or _new_uuid()),
        "hash": hashed,
        "role": role,
        "created_at": str(value.get("created_at") or utc_now()),
        "disabled": bool(value.get("disabled", False)),
        "avatar": str(value.get("avatar") or ""),
    }


def _new_uuid() -> str:
    from uuid import uuid4

    return f"u_{uuid4().hex}"


def _read_json(path: Path) -> dict[str, Any]:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
        return loaded if isinstance(loaded, dict) else {}
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Failed to read %s: %s", path, exc)
        return {}


def _write_users(users: dict[str, dict[str, Any]]) -> None:
    USERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    USERS_FILE.write_text(json.dumps(users, indent=2, ensure_ascii=False), encoding="utf-8")


def _migrate_legacy_users() -> dict[str, dict[str, Any]] | None:
    if USERS_FILE.exists() or not LEGACY_USERS_FILE.exists():
        return None
    legacy = _read_json(LEGACY_USERS_FILE)
    users: dict[str, dict[str, Any]] = {}
    for username, value in legacy.items():
        role: Role = "admin" if not users else "user"
        if isinstance(value, dict) and str(value.get("role") or "") in {"admin", "user"}:
            role = str(value.get("role"))  # type: ignore[assignment]
        record = _canonical_record(username, value, default_role=role)
        if record is not None:
            users[str(username)] = record
    if users:
        _write_users(users)
        logger.info("Migrated auth users from %s to %s", LEGACY_USERS_FILE, USERS_FILE)
        return users
    return None


def _migrate_secret() -> None:
    if SECRET_FILE.exists() or not LEGACY_SECRET_FILE.exists():
        return
    try:
        secret = LEGACY_SECRET_FILE.read_text(encoding="utf-8").strip()
        if secret:
            SECRET_FILE.parent.mkdir(parents=True, exist_ok=True)
            SECRET_FILE.write_text(secret, encoding="utf-8")
            try:
                SECRET_FILE.chmod(0o600)
            except OSError:
                pass
            logger.info("Migrated auth secret from %s to %s", LEGACY_SECRET_FILE, SECRET_FILE)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Failed to migrate legacy auth secret: %s", exc)


def load_users(  # nosec B107 - empty defaults mean "no env fallback supplied".
    env_username: str = "",
    env_password_hash: str = "",
) -> dict[str, dict[str, Any]]:
    """Load canonical users, migrating legacy records and env fallback in memory."""
    users: dict[str, dict[str, Any]] | None = None
    if USERS_FILE.exists():
        users = _read_json(USERS_FILE)
    else:
        users = _migrate_legacy_users()

    if users is None:
        users = {}

    canonical: dict[str, dict[str, Any]] = {}
    changed = False
    for index, (username, value) in enumerate(users.items()):
        role: Role = "admin" if index == 0 else "user"
        if isinstance(value, dict) and str(value.get("role") or "") in {"admin", "user"}:
            role = str(value.get("role"))  # type: ignore[assignment]
        record = _canonical_record(str(username), value, default_role=role)
        if record is None:
            changed = True
            continue
        canonical[str(username)] = record
        changed = changed or record != value

    if USERS_FILE.exists() and changed:
        _write_users(canonical)

    if canonical:
        return canonical

    if env_username and env_password_hash:
        return {
            env_username: {
                "id": "env-admin",
                "hash": env_password_hash,
                "role": "admin",
                "created_at": "",
                "disabled": False,
            }
        }

    return {}


def save_user(username: str, hashed_password: str, role: Role = "user") -> dict[str, Any]:
    USERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with _USERS_WRITE_LOCK:
        users = load_users()
        effective_role: Role = "admin" if not users else role
        existing = users.get(username) or {}
        record = {
            "id": str(existing.get("id") or _new_uuid()),
            "hash": hashed_password,
            "role": effective_role,
            "created_at": str(existing.get("created_at") or utc_now()),
            "disabled": bool(existing.get("disabled", False)),
            "avatar": str(existing.get("avatar") or ""),
        }
        users[username] = record
        _write_users(users)
    return record


def list_user_info(  # nosec B107
    env_username: str = "",
    env_password_hash: str = "",
) -> list[dict[str, Any]]:
    return [
        {
            "id": record.get("id", ""),
            "username": username,
            "role": record.get("role", "user"),
            "created_at": record.get("created_at", ""),
            "disabled": bool(record.get("disabled", False)),
            "avatar": str(record.get("avatar") or ""),
        }
        for username, record in load_users(env_username, env_password_hash).items()
    ]


def get_user(username: str) -> dict[str, Any] | None:
    return load_users().get(username)


def get_user_by_id(user_id: str) -> tuple[str, dict[str, Any]] | None:
    for username, record in load_users().items():
        if str(record.get("id") or "") == user_id:
            return username, record
    return None


def delete_user(username: str) -> bool:
    if not USERS_FILE.exists():
        return False
    users = load_users()
    if username not in users:
        return False
    users.pop(username, None)
    _write_users(users)
    return True


def set_avatar(username: str, avatar: str) -> bool:
    """Update the avatar marker for an existing user. Returns True on success."""
    if not USERS_FILE.exists():
        return False
    with _USERS_WRITE_LOCK:
        users = load_users()
        if username not in users:
            return False
        users[username]["avatar"] = avatar
        _write_users(users)
    return True


# Avatar image files — stored next to the user store, keyed by user id
AVATAR_EXTENSIONS = ("png", "jpg", "webp")


def _avatar_dir() -> Path:
    # Resolved lazily so tests that monkeypatch AUTH_DIR keep avatars isolated.
    return AUTH_DIR / "avatars"


def get_avatar_file(user_id: str) -> Path | None:
    """Return the stored avatar image for ``user_id``, or None."""
    for ext in AVATAR_EXTENSIONS:
        candidate = _avatar_dir() / f"{user_id}.{ext}"
        if candidate.is_file():
            return candidate
    return None


def save_avatar_file(user_id: str, data: bytes, ext: str) -> Path:
    """Atomically persist an avatar image, replacing any previous one."""
    if ext not in AVATAR_EXTENSIONS:
        raise ValueError(f"Unsupported avatar extension: {ext!r}")
    directory = _avatar_dir()
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{user_id}.{ext}"
    tmp = directory / f"{user_id}.{ext}.tmp"
    tmp.write_bytes(data)
    tmp.replace(target)
    for other in AVATAR_EXTENSIONS:
        if other != ext:
            (directory / f"{user_id}.{other}").unlink(missing_ok=True)
    return target


def delete_avatar_file(user_id: str) -> None:
    for ext in AVATAR_EXTENSIONS:
        (_avatar_dir() / f"{user_id}.{ext}").unlink(missing_ok=True)


def set_role(username: str, role: Role) -> bool:
    if role not in {"admin", "user"}:
        raise ValueError("role must be 'admin' or 'user'")
    if not USERS_FILE.exists():
        return False
    users = load_users()
    if username not in users:
        return False
    users[username]["role"] = role
    _write_users(users)
    return True


def load_or_create_auth_secret() -> str:
    _migrate_secret()
    try:
        if SECRET_FILE.exists():
            existing = SECRET_FILE.read_text(encoding="utf-8").strip()
            if existing:
                return existing
        SECRET_FILE.parent.mkdir(parents=True, exist_ok=True)
        generated = secrets.token_hex(32)
        SECRET_FILE.write_text(generated, encoding="utf-8")
        try:
            SECRET_FILE.chmod(0o600)
        except OSError:
            pass
        logger.warning(
            "Auth is enabled and no auth_secret file exists. Generated a stable local secret at %s.",
            SECRET_FILE,
        )
        return generated
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Failed to load/create auth secret at %s: %s", SECRET_FILE, exc)
        return secrets.token_hex(32)


__all__ = [
    "AUTH_DIR",
    "ADMIN_WORKSPACE_ROOT",
    "ADMIN_PREFIX",
    "AVATAR_EXTENSIONS",
    "CurrentUser",
    "KnowledgeResource",
    "LOCAL_ADMIN_ID",
    "LOCAL_ADMIN_USERNAME",
    "PROJECT_ROOT",
    "Role",
    "SECRET_FILE",
    "SYSTEM_ROOT",
    "ScopeKind",
    "USERS_FILE",
    "UserRecord",
    "UserScope",
    "USER_PREFIX",
    "admin_catalog",
    "admin_catalog_service",
    "admin_kb_base_dir",
    "admin_kb_manager",
    "admin_scope",
    "allowed_llm_options",
    "allowed_mcp_tools",
    "allowed_optional_tools",
    "apply_allowed_llm_selection",
    "assert_skill_allowed",
    "assert_writable",
    "assigned_skill_detail",
    "assigned_skill_ids",
    "assigned_skill_infos",
    "current_kb_base_dir",
    "current_kb_manager",
    "current_owner_id",
    "delete_avatar_file",
    "delete_user",
    "exec_override",
    "get_admin_path_service",
    "get_avatar_file",
    "get_current_path_service",
    "get_current_user",
    "get_current_user_or_none",
    "get_owner_path_service",
    "get_owner_secrets_dir",
    "get_path_service_for_scope",
    "get_user",
    "get_user_by_id",
    "has_capability_access",
    "list_user_info",
    "list_visible_knowledge_bases",
    "load_or_create_auth_secret",
    "load_users",
    "local_admin_user",
    "manager_for_resource",
    "merge_personal_llm_profiles",
    "new_user_id",
    "owner_catalog_service",
    "owner_secrets_dir",
    "personal_llm_rows",
    "redacted_model_access",
    "reset_current_user",
    "resolve_for_rag",
    "resolve_kb",
    "resolve_kb_manifest",
    "resolve_kb_metadata",
    "save_avatar_file",
    "save_user",
    "set_avatar",
    "set_current_user",
    "set_role",
    "user_context",
    "user_from_token_payload",
]
