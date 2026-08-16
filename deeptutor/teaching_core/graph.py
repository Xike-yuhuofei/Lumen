from __future__ import annotations

from collections import defaultdict, deque

from .models import (
    TeachingEdge,
    TeachingKnowledgeModel,
    TeachingNode,
    TeachingRelationType,
)


class TeachingKnowledgeGraph:
    """Small deterministic teaching graph with no database or LLM dependency."""

    def __init__(self, model: TeachingKnowledgeModel | None = None) -> None:
        self._nodes: dict[str, TeachingNode] = {}
        self._outgoing: dict[str, list[TeachingEdge]] = defaultdict(list)
        self._incoming: dict[str, list[TeachingEdge]] = defaultdict(list)
        if model is not None:
            for node in model.nodes:
                self.add_node(node)
            for edge in model.edges:
                self.add_edge(edge)

    def add_node(self, node: TeachingNode) -> None:
        if node.id in self._nodes:
            raise ValueError(f"duplicate teaching node id: {node.id}")
        self._nodes[node.id] = node

    def add_edge(self, edge: TeachingEdge) -> None:
        if edge.source not in self._nodes or edge.target not in self._nodes:
            raise ValueError("edge endpoints must exist before the edge is added")
        self._outgoing[edge.source].append(edge)
        self._incoming[edge.target].append(edge)

    def node(self, node_id: str) -> TeachingNode:
        try:
            return self._nodes[node_id]
        except KeyError as exc:
            raise KeyError(f"unknown teaching node: {node_id}") from exc

    def nodes(self) -> list[TeachingNode]:
        return list(self._nodes.values())

    def edges(
        self,
        *,
        relation: TeachingRelationType | None = None,
    ) -> list[TeachingEdge]:
        result = [edge for edges in self._outgoing.values() for edge in edges]
        if relation is None:
            return result
        return [edge for edge in result if edge.relation == relation]

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

    def prerequisites(self, node_id: str, *, recursive: bool = True) -> list[str]:
        """Return prerequisites in stable root-to-near order.

        ``A --prerequisite_of--> B`` means A must be learned before B.
        """
        self.node(node_id)
        direct = [
            edge.source for edge in self.incoming(node_id, TeachingRelationType.PREREQUISITE_OF)
        ]
        if not recursive:
            return direct

        ordered: list[str] = []
        visited: set[str] = set()

        def visit(current: str) -> None:
            for parent in [
                edge.source for edge in self.incoming(current, TeachingRelationType.PREREQUISITE_OF)
            ]:
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

    def topological_order(self) -> list[str]:
        """Topological order of prerequisite relations only."""
        indegree = {node_id: 0 for node_id in self._nodes}
        children: dict[str, list[str]] = defaultdict(list)

        for edge in self.edges(relation=TeachingRelationType.PREREQUISITE_OF):
            indegree[edge.target] += 1
            children[edge.source].append(edge.target)

        queue = deque(node_id for node_id in self._nodes if indegree[node_id] == 0)
        order: list[str] = []

        while queue:
            current = queue.popleft()
            order.append(current)
            for child in children.get(current, ()):
                indegree[child] -= 1
                if indegree[child] == 0:
                    queue.append(child)

        if len(order) != len(self._nodes):
            raise ValueError("prerequisite graph contains a cycle")
        return order

    def to_model(self) -> TeachingKnowledgeModel:
        return TeachingKnowledgeModel(nodes=self.nodes(), edges=self.edges())


__all__ = ["TeachingKnowledgeGraph"]
