"""Graph Tests — teaching relations, traversal, closure, paths, misconceptions.

These verify the Teaching Knowledge Graph answers the questions the Teaching
Engine and the content generator need, deterministically.
"""

from __future__ import annotations

import pytest

from deeptutor.teaching_core.builder import build_graph_from_modules
from deeptutor.teaching_core.graph import TeachingKnowledgeGraph
from deeptutor.teaching_core.models import (
    TeachingEdge,
    TeachingKnowledgeModel,
    TeachingNode,
    TeachingNodeType,
    TeachingRelationType,
)


def _sample_graph() -> TeachingKnowledgeGraph:
    """A small book-like graph:

    A (concept) --prerequisite_of--> B (concept) --prerequisite_of--> C (concept)
    A --part_of--> Module1
    E (example) --example_of--> C
    M (misconception) --commonly_confused_with--> C
    F (explanation) --corrects--> M
    Q (question) --assesses--> C
    """
    model = TeachingKnowledgeModel(
        nodes=[
            TeachingNode(id="A", title="A", type=TeachingNodeType.CONCEPT),
            TeachingNode(id="B", title="B", type=TeachingNodeType.CONCEPT),
            TeachingNode(id="C", title="C", type=TeachingNodeType.CONCEPT),
            TeachingNode(id="M1", title="Module1", type=TeachingNodeType.LEARNING_OBJECTIVE),
            TeachingNode(id="E", title="Example", type=TeachingNodeType.EXAMPLE),
            TeachingNode(id="M", title="Misconception", type=TeachingNodeType.MISCONCEPTION),
            TeachingNode(id="F", title="Fix", type=TeachingNodeType.EXPLANATION),
            TeachingNode(id="Q", title="Question", type=TeachingNodeType.QUESTION),
        ],
        edges=[
            TeachingEdge(source="A", target="B", relation=TeachingRelationType.PREREQUISITE_OF),
            TeachingEdge(source="B", target="C", relation=TeachingRelationType.PREREQUISITE_OF),
            TeachingEdge(source="A", target="M1", relation=TeachingRelationType.PART_OF),
            TeachingEdge(source="B", target="M1", relation=TeachingRelationType.PART_OF),
            TeachingEdge(source="E", target="C", relation=TeachingRelationType.EXAMPLE_OF),
            TeachingEdge(
                source="M", target="C", relation=TeachingRelationType.COMMONLY_CONFUSED_WITH
            ),
            TeachingEdge(source="F", target="M", relation=TeachingRelationType.CORRECTS),
            TeachingEdge(source="Q", target="C", relation=TeachingRelationType.ASSESSES),
        ],
    )
    return TeachingKnowledgeGraph(model)


# ── basic structure ─────────────────────────────────────────────────────


def test_node_and_edge_counts() -> None:
    g = _sample_graph()
    assert g.node_count() == 8
    assert g.edge_count() == 8
    assert "C" in g
    assert g.has_node("A")
    assert not g.has_node("missing")


def test_duplicate_node_rejected() -> None:
    g = _sample_graph()
    with pytest.raises(ValueError):
        g.add_node(TeachingNode(id="A", title="A2", type=TeachingNodeType.CONCEPT))


def test_edge_requires_existing_endpoints() -> None:
    g = _sample_graph()
    with pytest.raises(ValueError):
        g.add_edge(TeachingEdge(source="A", target="ghost", relation=TeachingRelationType.PART_OF))


# ── prerequisite / closure ──────────────────────────────────────────────


def test_prerequisites_recursive_and_direct() -> None:
    g = _sample_graph()
    # A is a prerequisite of C (A -> B -> C), root-to-near order: [A, B]
    assert g.prerequisites("C", recursive=True) == ["A", "B"]
    # direct prereq of C is B only
    assert g.prerequisites("C", recursive=False) == ["B"]


def test_successors_recursive_and_direct() -> None:
    g = _sample_graph()
    # successors follow ORDERING_RELATIONS (prerequisite_of + part_of):
    # A --prerequisite_of--> B, A --part_of--> M1, B --prerequisite_of--> C.
    assert set(g.successors("A", recursive=False)) == {"B", "M1"}
    assert set(g.successors("A", recursive=True)) == {"B", "M1", "C"}


# ── cycle detection / topological order ─────────────────────────────────


def test_topological_order() -> None:
    g = _sample_graph()
    order = g.topological_order()
    assert set(order) == {n.id for n in g.nodes()}
    # prerequisites must come before dependents
    assert order.index("A") < order.index("B") < order.index("C")


def test_cycle_detected_in_ordering_relations() -> None:
    g = _sample_graph()
    g.add_edge(TeachingEdge(source="C", target="A", relation=TeachingRelationType.PREREQUISITE_OF))
    assert g.has_cycle() is True
    with pytest.raises(ValueError):
        g.topological_order()


def test_non_ordering_cycle_is_allowed() -> None:
    # example/misconception cycles must not break the learning-order skeleton.
    g = _sample_graph()
    # Add a new node and an example cycle that is NOT an ordering relation.
    g.add_node(TeachingNode(id="E2", title="E2", type=TeachingNodeType.EXAMPLE))
    g.add_edge(TeachingEdge(source="E", target="E2", relation=TeachingRelationType.EXAMPLE_OF))
    g.add_edge(TeachingEdge(source="E2", target="E", relation=TeachingRelationType.EXAMPLE_OF))
    # topological order ignores example_of, so no cycle is raised.
    assert g.topological_order()


# ── misconception relations ─────────────────────────────────────────────


def test_misconceptions_related_to() -> None:
    g = _sample_graph()
    assert g.misconceptions_related_to("C") == ["M"]
    # other direction: misconceptions have no misconception links back
    assert g.misconceptions_related_to("A") == []


def test_resources_for_by_relation() -> None:
    g = _sample_graph()
    assert sorted(g.resources_for("C", TeachingRelationType.EXAMPLE_OF)) == ["E"]
    assert sorted(g.resources_for("C", TeachingRelationType.ASSESSES)) == ["Q"]
    assert sorted(g.resources_for("M", TeachingRelationType.CORRECTS)) == ["F"]


# ── related / teaching context ──────────────────────────────────────────


def test_related_includes_direction() -> None:
    g = _sample_graph()
    related = g.related("C")
    pairs = {(nid, direction) for nid, direction, _ in related}
    assert ("B", "in") in pairs  # B --prereq--> C
    assert ("E", "in") in pairs  # E --example_of--> C
    assert ("M", "in") in pairs  # M --confused_with--> C
    assert ("Q", "in") in pairs  # Q --assesses--> C
    # C has no outgoing ordering edges in this graph
    assert ("B", "out") not in pairs


def test_teaching_context_subgraph() -> None:
    g = _sample_graph()
    ctx = g.teaching_context("C", max_depth=1)
    assert ctx.nodes  # C plus everything directly connected
    node_ids = {n.id for n in ctx.nodes}
    assert "C" in node_ids
    assert {"B", "E", "M", "Q"} <= node_ids


# ── learning path ───────────────────────────────────────────────────────


def test_learning_path() -> None:
    g = _sample_graph()
    assert g.learning_path("A", "C") == ["A", "B", "C"]
    assert g.learning_path("A", "A") == ["A"]
    assert g.learning_path("C", "A") == []  # no path backwards


# ── builder: structural graph from mastery modules ──────────────────────


def test_build_graph_from_modules() -> None:
    from deeptutor.learning.models import KnowledgePoint, KnowledgeType, LearningModule

    modules = [
        LearningModule(
            id="p_m0",
            name="Basics",
            order=0,
            knowledge_points=[
                KnowledgePoint(id="k1", name="KP1", type=KnowledgeType.CONCEPT, module_id="p_m0"),
                KnowledgePoint(id="k2", name="KP2", type=KnowledgeType.PROCEDURE, module_id="p_m0"),
            ],
        ),
        LearningModule(
            id="p_m1",
            name="Advanced",
            order=1,
            knowledge_points=[
                KnowledgePoint(id="k3", name="KP3", type=KnowledgeType.CONCEPT, module_id="p_m1"),
            ],
        ),
    ]
    g = build_graph_from_modules(modules, source_id="p")
    # every kp becomes a node with the same id (learner mastery maps 1:1)
    assert g.has_node("k1") and g.has_node("k2") and g.has_node("k3")
    # modules become part_of containers; each kp points INTO its module node
    assert g.has_node("p_m0__module") and g.has_node("p_m1__module")
    part_of_targets = {edge.target for edge in g.outgoing("k1", TeachingRelationType.PART_OF)}
    assert part_of_targets == {"p_m0__module"}
    # resources_for returns the sources pointing INTO the module (its members)
    assert set(g.resources_for("p_m0__module", TeachingRelationType.PART_OF)) == {"k1", "k2"}
    # ordering within a module and across modules becomes prerequisite_of
    assert g.prerequisites("k2", recursive=False) == ["k1"]
    assert g.prerequisites("k3", recursive=False) == ["k2"]
    # the whole ordering skeleton is acyclic
    assert g.topological_order()
