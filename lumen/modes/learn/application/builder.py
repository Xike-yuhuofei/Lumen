"""Graph builder — turn canonical models / learning modules into a validated graph."""

from __future__ import annotations

from lumen.modes.learn.domain.models import KnowledgePoint, LearningModule
from lumen.modes.learn.domain.teaching_graph import TeachingKnowledgeGraph
from lumen.modes.learn.domain.teaching_models import (
    TeachingEdge,
    TeachingKnowledgeModel,
    TeachingNode,
    TeachingNodeType,
    TeachingRelationType,
)

__all__ = [
    "build_graph",
    "validate_graph",
    "build_graph_from_modules",
    "NODE_TYPE_BY_KNOWLEDGE_TYPE",
]

# Mapping from the learner model's KnowledgeType to the graph's canonical
# KnowledgeUnit role. Concept -> concept, procedure -> procedure, the rest map
# to the closest teaching unit type.
NODE_TYPE_BY_KNOWLEDGE_TYPE: dict[str, TeachingNodeType] = {
    "concept": TeachingNodeType.CONCEPT,
    "procedure": TeachingNodeType.PROCEDURE,
    "memory": TeachingNodeType.PRINCIPLE,
    "design": TeachingNodeType.LEARNING_OBJECTIVE,
}


def build_graph(model: TeachingKnowledgeModel) -> TeachingKnowledgeGraph:
    """Validate and materialise a TeachingKnowledgeModel into a graph."""
    graph = TeachingKnowledgeGraph(model)
    validate_graph(graph)
    return graph


def validate_graph(graph: TeachingKnowledgeGraph) -> None:
    """Raise ``ValueError`` when ordering relations contain a cycle.

    Non-ordering relations (examples, corrections, misconceptions, …) are
    intentionally allowed to cycle — only the learning-order skeleton must be
    acyclic.
    """
    graph.topological_order()  # raises ValueError on cycle


def build_graph_from_modules(
    modules: list[LearningModule],
    *,
    source_id: str = "path",
) -> TeachingKnowledgeGraph:
    """Build a structural Teaching Knowledge Graph from a mastery path.

    Used when no extracted teaching model exists yet: each knowledge point
    becomes a KnowledgeUnit, each module becomes a ``part_of`` container, and
    module order becomes ``prerequisite_of`` links so the Teaching Engine can
    still gate progress deterministically.

    Node ids equal the knowledge point ids, so the learner model's mastery /
    attempts map onto the graph with no renaming. Each KP also contributes:

    * its ``description`` / ``source_ref`` as node content / source grounding;
    * one MISCONCEPTION node per registered misconception, joined by a
      ``corrects`` edge (KP corrects the misconception) so the engine's
      remediation policy has real material to remediate with.
    """
    graph = TeachingKnowledgeGraph()
    kp_by_id: dict[str, KnowledgePoint] = {}

    for module in sorted(modules, key=lambda m: m.order):
        module_node_id = f"{module.id}__module"
        module_node = TeachingNode(
            id=module_node_id,
            title=module.name,
            type=TeachingNodeType.LEARNING_OBJECTIVE,
            metadata={"module": True, "source": source_id},
        )
        if not graph.has_node(module_node_id):
            graph.add_node(module_node)

        previous_kp_id: str | None = None
        for kp in module.knowledge_points:
            kp_by_id[kp.id] = kp
            node_type = NODE_TYPE_BY_KNOWLEDGE_TYPE.get(kp.type.value, TeachingNodeType.CONCEPT)
            node = TeachingNode(
                id=kp.id,
                title=kp.name,
                type=node_type,
                content=kp.description or "",
                source_refs=[kp.source_ref] if kp.source_ref else [],
                metadata={"module_id": module.id, "knowledge_type": kp.type.value},
            )
            if not graph.has_node(kp.id):
                graph.add_node(node)
            # knowledge point is part of its module
            graph.add_edge(
                TeachingEdge(
                    source=kp.id,
                    target=module_node_id,
                    relation=TeachingRelationType.PART_OF,
                    weight=1.0,
                )
            )
            # registered misconceptions become remediable MISCONCEPTION nodes;
            # the KP node is the correction resource for each of them.
            for i, mis in enumerate(kp.misconceptions):
                statement = mis.statement.strip()
                if not statement:
                    continue
                mis_node_id = f"{kp.id}__mis{i}"
                if not graph.has_node(mis_node_id):
                    graph.add_node(
                        TeachingNode(
                            id=mis_node_id,
                            title=statement[:120],
                            type=TeachingNodeType.MISCONCEPTION,
                            content=statement,
                            metadata={
                                "knowledge_point_id": kp.id,
                                "correction": mis.correction,
                                "source": source_id,
                            },
                        )
                    )
                graph.add_edge(
                    TeachingEdge(
                        source=kp.id,
                        target=mis_node_id,
                        relation=TeachingRelationType.CORRECTS,
                        weight=1.0,
                    )
                )
            # knowledge points within a module build on each other in order
            if previous_kp_id is not None and previous_kp_id != kp.id:
                graph.add_edge(
                    TeachingEdge(
                        source=previous_kp_id,
                        target=kp.id,
                        relation=TeachingRelationType.PREREQUISITE_OF,
                        weight=1.0,
                    )
                )
            previous_kp_id = kp.id

    # module order -> prerequisite chain across modules
    ordered_modules = sorted(modules, key=lambda m: m.order)
    for earlier, later in zip(ordered_modules, ordered_modules[1:]):
        earlier_kps = [kp.id for kp in earlier.knowledge_points]
        later_kps = [kp.id for kp in later.knowledge_points]
        if earlier_kps and later_kps:
            graph.add_edge(
                TeachingEdge(
                    source=earlier_kps[-1],
                    target=later_kps[0],
                    relation=TeachingRelationType.PREREQUISITE_OF,
                    weight=1.0,
                )
            )
    return graph
