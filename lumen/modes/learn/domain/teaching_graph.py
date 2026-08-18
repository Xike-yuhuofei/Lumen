"""Teaching Knowledge Graph — deterministic in-memory graph.

The graph is the source of truth for *teaching relations* between knowledge
units. It is NOT a general-purpose entity graph, a GraphRAG index, or a
vector store. Queries here return teaching structure answers (prerequisites,
misconception links, teaching context), not document passages.

Repository and query utilities for a persistent (SQLite + JSON) backing store
live in :mod:`lumen.modes.learn.adapters.graph_repository`.
"""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Iterator

from lumen.modes.learn.domain.teaching_models import (
    TeachingEdge,
    TeachingKnowledgeModel,
    TeachingNode,
    TeachingNodeType,
    TeachingRelationType,
)


class TeachingKnowledgeGraph:
    """Deterministic in-memory teaching graph.

    All operations are O(1) or O(V+E) with no I/O — the engine can call
    ``prerequisites()``, ``related()``, etc. without ever hitting a database.
    """

    def __init__(self, model: TeachingKnowledgeModel | None = None) -> None:
        self._nodes: dict[str, TeachingNode] = {}
        self._outgoing: dict[str, list[TeachingEdge]] = defaultdict(list)
        self._incoming: dict[str, list[TeachingEdge]] = defaultdict(list)
        if model is not None:
            for node in model.nodes:
                self.add_node(node)
            for edge in model.edges:
                self.add_edge(edge)

    # ── mutation ─────────────────────────────────────────────────────────

    def add_node(self, node: TeachingNode) -> None:
        if node.id in self._nodes:
            raise ValueError(f"duplicate teaching node id: {node.id}")
        self._nodes[node.id] = node

    def add_edge(self, edge: TeachingEdge) -> None:
        if edge.source not in self._nodes or edge.target not in self._nodes:
            raise ValueError("edge endpoints must exist before the edge is added")
        self._outgoing[edge.source].append(edge)
        self._incoming[edge.target].append(edge)

    def remove_node(self, node_id: str) -> None:
        self.node(node_id)  # raises if unknown
        del self._nodes[node_id]
        self._outgoing.pop(node_id, None)
        self._incoming.pop(node_id, None)
        # Clean edges referencing this node from both directions.
        for src in list(self._outgoing):
            self._outgoing[src] = [e for e in self._outgoing[src] if e.target != node_id]
        for tgt in list(self._incoming):
            self._incoming[tgt] = [e for e in self._incoming[tgt] if e.source != node_id]

    def remove_edge(self, source: str, target: str, relation: TeachingRelationType) -> None:
        def _remove(adj: dict[str, list[TeachingEdge]]) -> None:
            for key in list(adj):
                adj[key] = [
                    e
                    for e in adj[key]
                    if not (e.source == source and e.target == target and e.relation == relation)
                ]

        _remove(self._outgoing)
        _remove(self._incoming)

    # ── read ─────────────────────────────────────────────────────────────

    def node(self, node_id: str) -> TeachingNode:
        try:
            return self._nodes[node_id]
        except KeyError as exc:
            raise KeyError(f"unknown teaching node: {node_id}") from exc

    def has_node(self, node_id: str) -> bool:
        return node_id in self._nodes

    def nodes(self) -> list[TeachingNode]:
        return list(self._nodes.values())

    def node_count(self) -> int:
        return len(self._nodes)

    def edges(
        self,
        *,
        relation: TeachingRelationType | None = None,
    ) -> list[TeachingEdge]:
        result = [edge for edges in self._outgoing.values() for edge in edges]
        if relation is None:
            return result
        return [edge for edge in result if edge.relation == relation]

    def edge_count(self) -> int:
        return sum(len(edges) for edges in self._outgoing.values())

    def incoming(
        self,
        node_id: str,
        relation: TeachingRelationType | None = None,
    ) -> list[TeachingEdge]:
        self.node(node_id)
        result = list(self._incoming.get(node_id, ()))
        if relation is None:
            return result
        return [edge for edge in result if edge.relation == relation]

    def outgoing(
        self,
        node_id: str,
        relation: TeachingRelationType | None = None,
    ) -> list[TeachingEdge]:
        self.node(node_id)
        result = list(self._outgoing.get(node_id, ()))
        if relation is None:
            return result
        return [edge for edge in result if edge.relation == relation]

    # ── teaching queries ─────────────────────────────────────────────────

    def prerequisites(self, node_id: str, *, recursive: bool = True) -> list[str]:
        """Return prerequisites in stable root-to-near order.

        ``A --prerequisite_of--> B`` means A must be learned before B.
        """
        self.node(node_id)
        return self._ordering_closure(node_id, "incoming", recursive)

    def successors(self, node_id: str, *, recursive: bool = True) -> list[str]:
        """Return successors (what this node prepares for), near-to-far."""
        self.node(node_id)
        return self._ordering_closure(node_id, "outgoing", recursive)

    def _ordering_closure(self, node_id: str, direction: str, recursive: bool) -> list[str]:
        rels = TeachingRelationType.ORDERING_RELATIONS
        adj = self._incoming if direction == "incoming" else self._outgoing

        def _parents_of(nid: str) -> list[str]:
            return [
                edge.source if direction == "incoming" else edge.target
                for edge in adj.get(nid, ())
                if edge.relation in rels
            ]

        direct = _parents_of(node_id)
        if not recursive:
            return direct
        ordered: list[str] = []
        visited: set[str] = set()

        def visit(current: str) -> None:
            for parent in _parents_of(current):
                if parent in visited:
                    continue
                visit(parent)
                visited.add(parent)
                ordered.append(parent)

        visit(node_id)
        return ordered

    def resources_for(
        self,
        node_id: str,
        relation: TeachingRelationType,
    ) -> list[str]:
        """Return source nodes that point to ``node_id`` with ``relation``."""
        return [edge.source for edge in self.incoming(node_id, relation)]

    def related(
        self,
        node_id: str,
        *,
        relation: TeachingRelationType | None = None,
        include_incoming: bool = True,
        include_outgoing: bool = True,
    ) -> list[tuple[str, str, TeachingRelationType]]:
        """All nodes directly related to ``node_id``.

        Returns ``(related_id, direction, relation)`` triples where
        ``direction`` is ``"in"`` (source -> node_id) or ``"out"`` (node_id -> target).
        """
        result: list[tuple[str, str, TeachingRelationType]] = []
        if include_incoming:
            for edge in self.incoming(node_id, relation):
                result.append((edge.source, "in", edge.relation))
        if include_outgoing:
            for edge in self.outgoing(node_id, relation):
                result.append((edge.target, "out", edge.relation))
        return result

    def misconceptions_related_to(self, node_id: str) -> list[str]:
        """Misconception node ids teaching-related to ``node_id``.

        A misconception is a node of type :attr:`TeachingNodeType.MISCONCEPTION`
        joined to ``node_id`` by a ``commonly_confused_with`` edge (either
        direction).
        """
        result: set[str] = set()
        for edge in self.edges(relation=TeachingRelationType.COMMONLY_CONFUSED_WITH):
            if edge.source == node_id:
                other = edge.target
            elif edge.target == node_id:
                other = edge.source
            else:
                continue
            node = self._nodes.get(other)
            if node is not None and node.type == TeachingNodeType.MISCONCEPTION:
                result.add(other)
        return sorted(result)

    def learning_path(
        self,
        from_node: str,
        to_node: str,
    ) -> list[str]:
        """BFS shortest path following ``ORDERING_RELATIONS`` from ``from_node`` to ``to_node``.

        Returns an ordered list of node ids (inclusive) or empty list if no
        teaching path exists.
        """
        self.node(from_node)
        self.node(to_node)
        if from_node == to_node:
            return [from_node]

        adj: dict[str, list[str]] = defaultdict(list)
        for edge in self.edges():
            if edge.relation in TeachingRelationType.ORDERING_RELATIONS:
                adj[edge.source].append(edge.target)

        queue: deque[tuple[str, list[str]]] = deque([(from_node, [from_node])])
        visited: set[str] = {from_node}

        while queue:
            current, path = queue.popleft()
            for nxt in adj.get(current, ()):
                if nxt in visited:
                    continue
                new_path = path + [nxt]
                if nxt == to_node:
                    return new_path
                visited.add(nxt)
                queue.append((nxt, new_path))
        return []

    def teaching_context(
        self,
        node_id: str,
        *,
        max_depth: int = 1,
    ) -> TeachingKnowledgeModel:
        """Return the subgraph around ``node_id`` up to ``max_depth`` hops.

        Includes all relations (not just ORDERING_RELATIONS). This is the
        "teaching neighbourhood" the engine uses to make decisions.
        """
        self.node(node_id)
        included: set[str] = {node_id}
        frontier: set[str] = {node_id}

        for _ in range(max_depth):
            next_frontier: set[str] = set()
            for nid in frontier:
                for edge in self._outgoing.get(nid, ()):
                    if edge.target not in included:
                        included.add(edge.target)
                        next_frontier.add(edge.target)
                for edge in self._incoming.get(nid, ()):
                    if edge.source not in included:
                        included.add(edge.source)
                        next_frontier.add(edge.source)
            frontier = next_frontier

        return TeachingKnowledgeModel(
            nodes=[self._nodes[nid] for nid in sorted(included)],
            edges=[
                edge
                for edges in self._outgoing.values()
                for edge in edges
                if edge.source in included and edge.target in included
            ],
        )

    # ── topological / cycle detection ────────────────────────────────────

    def topological_order(self) -> list[str]:
        """Topological order of ORDERING_RELATIONS only."""
        indegree: dict[str, int] = {node_id: 0 for node_id in self._nodes}
        children: dict[str, list[str]] = defaultdict(list)

        for edge in self.edges():
            if edge.relation in TeachingRelationType.ORDERING_RELATIONS:
                indegree[edge.target] = indegree.get(edge.target, 0) + 1
                children[edge.source].append(edge.target)

        queue = deque(node_id for node_id in self._nodes if indegree.get(node_id, 0) == 0)
        order: list[str] = []

        while queue:
            current = queue.popleft()
            order.append(current)
            for child in children.get(current, ()):
                indegree[child] -= 1
                if indegree[child] == 0:
                    queue.append(child)

        if len(order) != len(self._nodes):
            raise ValueError("teaching graph contains a cycle in ordering relations")
        return order

    def has_cycle(self) -> bool:
        """Check for cycles in ORDERING_RELATIONS. Returns True if any exist."""
        try:
            self.topological_order()
            return False
        except ValueError:
            return True

    # ── serialisation ────────────────────────────────────────────────────

    def to_model(self) -> TeachingKnowledgeModel:
        return TeachingKnowledgeModel(nodes=self.nodes(), edges=self.edges())

    def __iter__(self) -> Iterator[TeachingNode]:
        return iter(self._nodes.values())

    def __len__(self) -> int:
        return len(self._nodes)

    def __contains__(self, node_id: object) -> bool:
        return isinstance(node_id, str) and node_id in self._nodes


__all__ = ["TeachingKnowledgeGraph"]
