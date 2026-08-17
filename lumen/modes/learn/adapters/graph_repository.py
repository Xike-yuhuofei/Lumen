"""Teaching Graph repository — a swappable persistence layer.

The Teaching Engine and graph queries depend only on the
:class:`TeachingGraphRepository` protocol, so the backing store can be swapped
without touching teaching logic. Three implementations ship in v1:

* :class:`MemoryTeachingGraphRepository` — default; used by the engine when no
  store is configured (and by fast tests).
* :class:`JsonTeachingGraphRepository` — per-path JSON files (mirrors the
  existing ``LearningStore`` convention).
* :class:`SQLiteTeachingGraphRepository` — the recommended persistent store:
  one local SQLite file, no server, no Docker, no Redis.
"""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import threading
from typing import Protocol

from lumen.modes.learn.domain.teaching_graph import TeachingKnowledgeGraph
from lumen.modes.learn.domain.teaching_models import (
    TeachingEdge,
    TeachingKnowledgeModel,
    TeachingNode,
)
from lumen.shared._util.runtime_paths import get_path_service

__all__ = [
    "TeachingGraphRepository",
    "MemoryTeachingGraphRepository",
    "JsonTeachingGraphRepository",
    "SQLiteTeachingGraphRepository",
    "default_graph_db_path",
]


def default_graph_db_path() -> Path:
    """Default location for the SQLite teaching-graph store (workspace-local)."""
    return get_path_service().get_workspace_dir() / "teaching" / "graphs.db"


class TeachingGraphRepository(Protocol):
    """Persistence contract for Teaching Knowledge Graphs."""

    def load_graph(self, path_id: str) -> TeachingKnowledgeGraph | None: ...

    def save_graph(self, path_id: str, graph: TeachingKnowledgeGraph) -> None: ...

    def delete_graph(self, path_id: str) -> None: ...

    def list_paths(self) -> list[str]: ...


class MemoryTeachingGraphRepository:
    """In-memory store (default). Not durable across processes."""

    def __init__(self) -> None:
        self._graphs: dict[str, TeachingKnowledgeGraph] = {}

    def load_graph(self, path_id: str) -> TeachingKnowledgeGraph | None:
        return self._graphs.get(path_id)

    def save_graph(self, path_id: str, graph: TeachingKnowledgeGraph) -> None:
        self._graphs[path_id] = TeachingKnowledgeGraph(graph.to_model())

    def delete_graph(self, path_id: str) -> None:
        self._graphs.pop(path_id, None)

    def list_paths(self) -> list[str]:
        return sorted(self._graphs)


class JsonTeachingGraphRepository:
    """Per-path JSON files under a root directory."""

    def __init__(self, root: Path | None = None) -> None:
        self._root = root or (get_path_service().get_workspace_dir() / "teaching" / "graphs")
        self._root.mkdir(parents=True, exist_ok=True)

    def _path(self, path_id: str) -> Path:
        safe = path_id.replace("/", "_").replace("\\", "_").replace(":", "_")
        return self._root / f"{safe}.json"

    def load_graph(self, path_id: str) -> TeachingKnowledgeGraph | None:
        path = self._path(path_id)
        if not path.exists():
            return None
        model = TeachingKnowledgeModel.model_validate(json.loads(path.read_text(encoding="utf-8")))
        return TeachingKnowledgeGraph(model)

    def save_graph(self, path_id: str, graph: TeachingKnowledgeGraph) -> None:
        data = graph.to_model().model_dump(mode="json")
        self._path(path_id).write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def delete_graph(self, path_id: str) -> None:
        path = self._path(path_id)
        if path.exists():
            path.unlink()

    def list_paths(self) -> list[str]:
        return sorted(p.stem for p in self._root.glob("*.json") if not p.name.startswith("."))


class SQLiteTeachingGraphRepository:
    """SQLite-backed teaching graph store (recommended for v1).

    Normalised ``teaching_nodes`` / ``teaching_edges`` tables keyed by path_id,
    so the graph can be rebuilt and queried without re-hydrating the whole
    model. Safe for concurrent access via a module-level connection lock.
    """

    _lock = threading.RLock()

    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = Path(db_path) if db_path is not None else default_graph_db_path()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._lock:
            with self._connect() as conn:
                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS teaching_nodes (
                        path_id      TEXT NOT NULL,
                        node_id      TEXT NOT NULL,
                        title        TEXT NOT NULL,
                        type         TEXT NOT NULL,
                        content      TEXT NOT NULL DEFAULT '',
                        source_refs  TEXT NOT NULL DEFAULT '[]',
                        difficulty   REAL NOT NULL DEFAULT 0.5,
                        importance   REAL NOT NULL DEFAULT 0.5,
                        teachability REAL NOT NULL DEFAULT 0.5,
                        metadata     TEXT NOT NULL DEFAULT '{}',
                        PRIMARY KEY (path_id, node_id)
                    );
                    CREATE TABLE IF NOT EXISTS teaching_edges (
                        path_id   TEXT NOT NULL,
                        source    TEXT NOT NULL,
                        target    TEXT NOT NULL,
                        relation  TEXT NOT NULL,
                        weight    REAL NOT NULL DEFAULT 1.0,
                        metadata  TEXT NOT NULL DEFAULT '{}',
                        PRIMARY KEY (path_id, source, target, relation)
                    );
                    CREATE INDEX IF NOT EXISTS idx_edges_path_source
                        ON teaching_edges (path_id, source);
                    CREATE INDEX IF NOT EXISTS idx_edges_path_target
                        ON teaching_edges (path_id, target);
                    """
                )

    def load_graph(self, path_id: str) -> TeachingKnowledgeGraph | None:
        with self._lock:
            with self._connect() as conn:
                node_rows = conn.execute(
                    "SELECT * FROM teaching_nodes WHERE path_id = ?", (path_id,)
                ).fetchall()
                if not node_rows:
                    return None
                nodes = [
                    TeachingNode(
                        id=row["node_id"],
                        title=row["title"],
                        type=row["type"],
                        content=row["content"],
                        source_refs=json.loads(row["source_refs"] or "[]"),
                        difficulty=row["difficulty"],
                        importance=row["importance"],
                        teachability=row["teachability"],
                        metadata=json.loads(row["metadata"] or "{}"),
                    )
                    for row in node_rows
                ]
                edge_rows = conn.execute(
                    "SELECT * FROM teaching_edges WHERE path_id = ?", (path_id,)
                ).fetchall()
                edges = [
                    TeachingEdge(
                        source=row["source"],
                        target=row["target"],
                        relation=row["relation"],
                        weight=row["weight"],
                        metadata=json.loads(row["metadata"] or "{}"),
                    )
                    for row in edge_rows
                ]
        return TeachingKnowledgeGraph(TeachingKnowledgeModel(nodes=nodes, edges=edges))

    def save_graph(self, path_id: str, graph: TeachingKnowledgeGraph) -> None:
        model = graph.to_model()
        with self._lock:
            with self._connect() as conn:
                conn.execute("DELETE FROM teaching_nodes WHERE path_id = ?", (path_id,))
                conn.execute("DELETE FROM teaching_edges WHERE path_id = ?", (path_id,))
                for node in model.nodes:
                    conn.execute(
                        """
                        INSERT INTO teaching_nodes
                        (path_id, node_id, title, type, content, source_refs,
                         difficulty, importance, teachability, metadata)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            path_id,
                            node.id,
                            node.title,
                            node.type.value,
                            node.content,
                            json.dumps(node.source_refs),
                            node.difficulty,
                            node.importance,
                            node.teachability,
                            json.dumps(node.metadata),
                        ),
                    )
                for edge in model.edges:
                    conn.execute(
                        """
                        INSERT INTO teaching_edges (path_id, source, target, relation, weight, metadata)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            path_id,
                            edge.source,
                            edge.target,
                            edge.relation.value,
                            edge.weight,
                            json.dumps(edge.metadata),
                        ),
                    )

    def delete_graph(self, path_id: str) -> None:
        with self._lock:
            with self._connect() as conn:
                conn.execute("DELETE FROM teaching_nodes WHERE path_id = ?", (path_id,))
                conn.execute("DELETE FROM teaching_edges WHERE path_id = ?", (path_id,))

    def list_paths(self) -> list[str]:
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT DISTINCT path_id FROM teaching_nodes ORDER BY path_id"
                ).fetchall()
        return [row["path_id"] for row in rows]
