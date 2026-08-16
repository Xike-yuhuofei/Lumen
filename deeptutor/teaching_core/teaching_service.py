"""TeachingService — stateless facade that bridges the Teaching Engine with the
existing Lumen learning system.

The TeachingService is the one public entry point for the Teaching Core. It
combines:

1. Loading / building the Teaching Knowledge Graph (from SQLite or modules).
2. Projecting the current ``LearningProgress`` into a ``LearnerState``.
3. Running the ``TeachingEngine`` to produce a ``TeachingAction``.
4. Translating the action into an instruction the agent can execute.

It is stateless and safe to instantiate per-call (the SQLite repository holds
the only durable state).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from deeptutor.learning.storage import LearningStore

from .adapters import (
    action_instruction,
    goal_from_progress,
    learner_state_from_progress,
)
from .builder import build_graph_from_modules
from .engine import TeachingEngine
from .graph import TeachingKnowledgeGraph
from .graph_repository import (
    SQLiteTeachingGraphRepository,
    TeachingGraphRepository,
)
from .models import TeachingAction, TeachingActionType

if TYPE_CHECKING:
    from deeptutor.learning.models import LearningProgress

logger = logging.getLogger(__name__)


class TeachingService:
    """Facade that produces a TeachingAction for a given learning path.

    Usage::

        service = TeachingService()
        action = service.decide(path_id="my-book")
        instruction = action_instruction(action, node_title="...")
    """

    def __init__(
        self,
        *,
        graph_repository: TeachingGraphRepository | None = None,
        engine: TeachingEngine | None = None,
        learning_store: LearningStore | None = None,
    ) -> None:
        self._graph_repo = graph_repository or SQLiteTeachingGraphRepository()
        self._engine = engine or TeachingEngine()
        self._store = learning_store or LearningStore()

    def decide(self, path_id: str) -> TeachingAction:
        """Produce the next TeachingAction for *path_id*.

        Steps:
        1. Load LearningProgress (returns ``complete`` action if absent).
        2. Load or build the Teaching Knowledge Graph.
        3. Project LearnerState from the progress.
        4. Build the LearningGoal.
        5. Run the Teaching Engine.
        6. Return the action.
        """
        progress = self._store.load(path_id)
        if progress is None or not progress.modules:
            return TeachingAction(
                action=TeachingActionType.COMPLETE,
                reason="No learning path exists for this path_id.",
                success_condition="A learning path must be built first.",
            )

        graph = self._load_or_build_graph(path_id, progress)

        learner = learner_state_from_progress(progress, graph=graph)
        goal = goal_from_progress(progress, graph=graph)
        if not goal.target_node_ids:
            return TeachingAction(
                action=TeachingActionType.COMPLETE,
                reason="No knowledge points are present in the graph for this path.",
                success_condition="Add knowledge points to the path.",
            )

        return self._engine.decide(graph=graph, goal=goal, learner=learner)

    def get_graph(self, path_id: str) -> TeachingKnowledgeGraph | None:
        """Load the Teaching Knowledge Graph for *path_id*, or None."""
        graph = self._graph_repo.load_graph(path_id)
        if graph is not None:
            return graph
        progress = self._store.load(path_id)
        if progress is None:
            return None
        return self._build_and_save_graph(path_id, progress)

    def rebuild_graph(self, path_id: str) -> TeachingKnowledgeGraph | None:
        """Force-rebuild the graph from the current learning modules."""
        progress = self._store.load(path_id)
        if progress is None or not progress.modules:
            return None
        return self._build_and_save_graph(path_id, progress)

    def _load_or_build_graph(
        self,
        path_id: str,
        progress: LearningProgress,
    ) -> TeachingKnowledgeGraph:
        graph = self._graph_repo.load_graph(path_id)
        if graph is not None:
            return graph
        return self._build_and_save_graph(path_id, progress)

    def _build_and_save_graph(
        self,
        path_id: str,
        progress: LearningProgress,
    ) -> TeachingKnowledgeGraph:
        graph = build_graph_from_modules(progress.modules, source_id=path_id)
        try:
            self._graph_repo.save_graph(path_id, graph)
        except Exception:
            logger.warning("Failed to persist teaching graph for %s", path_id, exc_info=True)
        return graph

    def action_instruction(
        self,
        action: TeachingAction,
        *,
        node_title: str = "",
    ) -> dict[str, Any]:
        return action_instruction(action, node_title=node_title)


__all__ = ["TeachingService"]
