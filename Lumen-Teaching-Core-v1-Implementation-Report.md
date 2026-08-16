# Lumen Teaching Core v1 — Implementation Report

## 1. Final Architecture

```
deeptutor/teaching_core/
├── __init__.py              # Public API re-exports
├── models.py                # Canonical Teaching Knowledge Model + contracts
├── graph.py                 # TeachingKnowledgeGraph (in-memory)
├── graph_repository.py      # Swappable persistence (SQLite / JSON / memory)
├── builder.py               # Graph builder from LearningModules
├── engine.py                # Teaching Engine (constrained deterministic policy stack)
├── adapters.py              # Adapters: LearningProgress ↔ LearnerState, action → instruction
├── teaching_service.py      # Stateless facade (the one public entry point)
└── tests/
    ├── test_model_contract.py      # 11 tests — domain model serialisation, validation
    ├── test_graph_queries.py       # 12 tests — prerequisites, successors, cycles, context, builder
    ├── test_policy_replay.py       # 4 tests — deterministic replay, policy priority
    ├── test_vertical_slice.py      # 2 tests — full-loop integration, graph-differentiation
    └── test_teaching_core.py       # 28 tests — legacy test suite (pre-restructure)
```

### Integration with existing Lumen

```
mastery_path (Capability)
    │
    ▼
ChatOrchestrator → agentic_pipeline (LLM loop)
    │
    ├── teaching_plan (Tool) ──────► TeachingService.decide()
    │                                       │
    │                          ┌────────────┼────────────┐
    │                          ▼            ▼            ▼
    │                   GraphRepo    LearningStore   TeachingEngine
    │                          │            │            │
    │                          ▼            ▼            ▼
    │                   SQLite / JSON  LearningProgress  Policy Stack
    │
    ├── mastery_status (Tool)   — raw map snapshot
    ├── mastery_quiz (Tool)     — register question
    ├── mastery_grade (Tool)    — grade answer
    ├── mastery_assess (Tool)   — qualitative gate
    ├── mastery_build (Tool)    — build path
    └── ask_user / rag / read_source — content tools
```

## 2. Domain Model

### TeachingNode (KnowledgeUnit)

| Field         | Type              | Description                                |
|---------------|-------------------|--------------------------------------------|
| `id`          | `str`             | Canonical node identifier                  |
| `title`       | `str`             | Human-readable name                        |
| `type`        | `TeachingNodeType`| Role: concept, procedure, example, …       |
| `content`     | `str`             | Optional body content                      |
| `source_refs` | `list[str]`       | Provenance locators (source_id#locator)    |
| `difficulty`  | `float [0,1]`     | Teaching metadata                          |
| `importance`  | `float [0,1]`     | Teaching metadata                          |
| `teachability`| `float [0,1]`     | Teaching metadata                          |
| `metadata`    | `dict[str, Any]`  | Extensible                                 |

### TeachingNodeType

```
LEARNING_OBJECTIVE, CONCEPT, PRINCIPLE, PROCEDURE,
CLAIM, ARGUMENT, EXAMPLE, ANALOGY, MISCONCEPTION,
QUESTION, EXPLANATION
```

### TeachingEdge

| Field      | Type                  | Description                     |
|------------|-----------------------|---------------------------------|
| `source`   | `str`                 | Source node id                  |
| `target`   | `str`                 | Target node id                  |
| `relation` | `TeachingRelationType` | Typed edge                     |
| `weight`   | `float`               | Edge strength (≥ 0)             |
| `metadata` | `dict[str, Any]`      | Extensible                      |

### TeachingRelationType

**Structural (learning-order skeleton):**
- `prerequisite_of` — A must be learned before B
- `part_of` — A is a component of B
- `depends_on` — A functionally depends on B
- `prepares_for` — A prepares the learner for B (softer than prerequisite)
- `requires` — A requires B to be meaningful

**Teaching relations:**
- `explains` — A is an explanation of B
- `supports` — A supports understanding B
- `example_of` — A is a concrete example of B
- `analogous_to` — A is analogous to B
- `contrasts_with` — A contrasts with B
- `commonly_confused_with` — Misconception link
- `corrects` — A corrects misconception B
- `remediates` — Remediation path for B
- `assesses` — A (question/assessment) assesses B

`ORDERING_RELATIONS` = `{prerequisite_of, part_of, depends_on, prepares_for}` — only these participate in topological sort and learning-path queries.

### TeachingKnowledgeModel

The canonical container: `TeachingKnowledgeModel(nodes, edges)`. Validates uniqueness and no dangling edge references. Used as serialisation/deserialisation boundary.

## 3. Graph Schema

### SQLite (recommended persistent store)

```sql
CREATE TABLE teaching_nodes (
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

CREATE TABLE teaching_edges (
    path_id   TEXT NOT NULL,
    source    TEXT NOT NULL,
    target    TEXT NOT NULL,
    relation  TEXT NOT NULL,
    weight    REAL NOT NULL DEFAULT 1.0,
    metadata  TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (path_id, source, target, relation)
);
```

### Repository protocol (`TeachingGraphRepository`)

```python
class TeachingGraphRepository(Protocol):
    def load_graph(self, path_id: str) -> TeachingKnowledgeGraph | None: ...
    def save_graph(self, path_id: str, graph: TeachingKnowledgeGraph) -> None: ...
    def delete_graph(self, path_id: str) -> None: ...
    def list_paths(self) -> list[str]: ...
```

Three implementations: `MemoryTeachingGraphRepository`, `JsonTeachingGraphRepository`, `SQLiteTeachingGraphRepository`.

## 4. TeachingAction Schema

| Field                 | Type                | Description                          |
|-----------------------|---------------------|--------------------------------------|
| `action`              | `TeachingActionType`| What to do next                      |
| `focus_node_id`       | `str`               | The target knowledge unit            |
| `strategy`            | `TeachingStrategy`  | Teaching approach                    |
| `scaffold_level`      | `ScaffoldLevel`     | Support level (none/light/medium/full)|
| `expected_evidence`   | `EvidenceType`      | What evidence to collect             |
| `success_condition`   | `str`               | When this action is complete         |
| `reason`              | `str`               | Why the engine chose this action     |
| `resource_node_ids`   | `list[str]`         | Linked resources (explanations, examples, corrections) |
| `constraints`         | `list[str]`         | Active constraints (e.g. "prerequisite_gate") |
| `trace`               | `DecisionTrace`     | Full decision log                    |

### TeachingActionType

```
REMEDIATE_MISCONCEPTION  — correct a known misconception
RESOLVE_PENDING          — grade a pending question first
REVIEW                   — spaced-repetition review
REVIEW_PREREQUISITE      — teach a prerequisite before the target
EXPLAIN                  — first exposure / re-explain
SHOW_EXAMPLE             — worked example after difficulty
PRACTICE                 — scaffolded practice after repeated difficulty
ASSESS                   — assess toward mastery gate
COMPLETE                 — all targets mastered
```

### TeachingStrategy

```
EXPLAIN_DIRECT, WORKED_EXAMPLE, ANALOGY, SOCRATIC,
SCAFFOLDED_PRACTICE, FEYNMAN_CHECK, SPACED_REVIEW,
MISCONCEPTION_CORRECTION, NONE
```

## 5. Policy Stack

Priority order (top-down, first match wins):

| Rank | Policy                 | Decision logic                                                     |
|------|------------------------|--------------------------------------------------------------------|
| 1    | `resolve_pending`      | A pending question exists → must be graded first                   |
| 2    | `remediate_misconception` | Active misconception nodes → full correction before progression |
| 3    | `review_due`            | Spaced-repetition items are due → refresh before new material      |
| 4    | `prerequisite_gate`    | First unmastered target's prerequisites below threshold → teach them first |
| 5    | `first_exposure`       | Target has 0 attempts → EXPLAIN with full scaffold                 |
| 6    | `scaffold_escalation`  | Target has low mastery + attempts → show example / practice        |
| 7    | `assess_gate`          | Target is partially learned → assess toward mastery gate           |
| 8    | `complete`             | All targets meet threshold → COMPLETE                              |

### Design guarantees

- **Deterministic**: same (graph, goal, learner) → same action. No `time.time()`, no random state.
- **Hard constraints**: goal validity, pending question, active misconception block progression.
- **Prerequisite gating**: only the **first unmastered target** is gated, so later targets' prerequisites don't block progress.
- **Mastery gating**: a target advances only when its mastery clears the goal threshold.
- **Scaffold escalation**: 0 attempts → EXPLAIN; 1-2 attempts with low mastery → SHOW_EXAMPLE (or re-EXPLAIN if no example exists); 3+ attempts with low mastery → SCAFFOLDED_PRACTICE.
- **Decision trace**: every action carries a `DecisionTrace` with `policy_applied`, `policies_evaluated`, `gates`, and `steps`.

## 6. Data Flow

```
Learning Material
    │
    ▼
Extraction (deeptutor/teaching_extraction/)
    │
    ▼
TeachingKnowledgeModel (nodes + edges)
    │
    ▼
TeachingKnowledgeGraph (validated, in-memory)
    │
    ├── SQLiteRepository.save_graph(path_id, graph)
    │
    ▼
────────  Teaching Time  ────────
    │
    ▼
mastery_path capability
    │
    ▼
TeachingPlanTool.execute()
    │
    ▼
TeachingService.decide(path_id)
    │
    ├── 1. LearningStore.load(path_id) → LearningProgress
    ├── 2. GraphRepository.load_graph(path_id) → TeachingKnowledgeGraph
    │       (or build_graph_from_modules as fallback)
    ├── 3. learner_state_from_progress(progress, graph) → LearnerState
    ├── 4. goal_from_progress(progress, graph) → LearningGoal
    └── 5. TeachingEngine.decide(graph, goal, learner) → TeachingAction
    │
    ▼
action_instruction(action, node_title) → {mastery_tool, instruction}
    │
    ▼
LLM agent executes instruction with existing mastery tools
    │
    ▼
Learner responds → quiz attempt / explanation
    │
    ▼
LearningStore.save(progress) → mastery/attempts updated
    │
    ▼
Next turn → TeachingPlanTool → TeachingService → TeachingEngine → next action
```

## 7. New / Modified Files

### New files (7 files, ~1,175 lines)

| File | Lines | Purpose |
|------|-------|---------|
| `deeptutor/teaching_core/builder.py` | 126 | Graph builder from LearningModules |
| `deeptutor/teaching_core/graph_repository.py` | 255 | SQLite/JSON/Memory persistence |
| `deeptutor/teaching_core/teaching_service.py` | 143 | Stateless facade |
| `deeptutor/teaching_core/tests/test_model_contract.py` | 253 | 11 model contract tests |
| `deeptutor/teaching_core/tests/test_graph_queries.py` | 232 | 12 graph query tests |
| `deeptutor/teaching_core/tests/test_policy_replay.py` | 275 | 4 policy replay tests |
| `deeptutor/teaching_core/tests/test_vertical_slice.py` | 472 | 2 integration tests |

### Modified files (9 files, +1,368 / -163 net)

| File | Purpose |
|------|---------|
| `deeptutor/teaching_core/__init__.py` | Added TeachingService export |
| `deeptutor/teaching_core/models.py` | +374 lines: full Teaching Knowledge Model, contracts, traces |
| `deeptutor/teaching_core/graph.py` | +241 lines: extended queries, resources_for, teaching_context, learning_path, topological_order |
| `deeptutor/teaching_core/engine.py` | +514 lines: full 8-policy Teaching Engine |
| `deeptutor/teaching_core/adapters.py` | +307 lines: learner_state, goal, evidence, estimate, action_instruction adapters |
| `deeptutor/capabilities/mastery/tools.py` | +83 lines: TeachingPlanTool |
| `deeptutor/capabilities/mastery/prompts/en/system.md` | +4 lines: teaching_plan instruction |
| `deeptutor/capabilities/mastery/prompts/zh/system.md` | +4 lines: teaching_plan instruction |
| `deeptutor/tools/mastery_tool.py` | +2 lines: TeachingPlanTool re-export |

## 8. Mapping to existing `deeptutor/learning/`

| Old (deeptutor.learning) | New (deeptutor.teaching_core) | Relationship |
|--------------------------|-------------------------------|-------------|
| `KnowledgePoint` | `TeachingNode` | Adapter maps kp → TeachingNode |
| `KnowledgeType` | `TeachingNodeType` | Reused via `NODE_TYPE_BY_KNOWLEDGE_TYPE` |
| `LearningModule` | `TeachingNode` (module) | Builder creates module nodes with `part_of` edges |
| `LearningProgress` | `LearnerState` | `learner_state_from_progress()` projects it |
| `LearningProgress` | `LearningGoal` | `goal_from_progress()` derives targets |
| `QuizAttempt` | `EvidenceItem` / `AssessmentResult` | Adapters translate |
| `mastery_levels` | `LearnerState.mastery` | Direct projection |
| `qualitative_mastery` | `LearnerState.mastery` (1.0) | Passed gates mapped to 1.0 |
| `error_records` | `LearnerState.misconceptions` | Filtered by MISCONCEPTION node type |
| `pending_question` | `LearnerState.pending_answer` | Direct projection |
| `due_reviews()` | `LearnerState.due_reviews` | Projected at a fixed `now` |
| `is_mastered()` | `TeachingEngine._first_unmastered_target()` | Engine logic |
| `next_objective()` | `prerequisite_gate` + `first_exposure` | Engine policies |
| `gate_threshold()` | `LearningGoal.mastery_threshold` | Goal parameter |
| `policy.py` | `engine.py` | Deterministic policy stack supersedes |
| `LearningStore` | `TeachingService` | Facade wraps LearningStore + GraphRepository + Engine |

## 9. Vertical Slice Verification

Two integration tests in `test_vertical_slice.py` prove the complete closed loop.

### Test 1 — `test_vertical_slice_full_loop()`

Drives the Teaching Engine through a 3-module learning path (What is a Function, Domain & Range, Function Composition) with 6 knowledge points plus an enriched teaching graph (misconception node, correction explanation, example, assessment question):

1. **First decision** (fresh learner: no mastery, no attempts, no misconceptions):
   - First unmastered target is `path_m0_kp0`; no attempts exist → `first_exposure` policy → **EXPLAIN** with `EXPLAIN_DIRECT` strategy, `FULL` scaffold.
   - Assertions: `action == EXPLAIN`, `focus == "path_m0_kp0"`, `trace.policy_applied == "first_exposure"`, `action_instruction` maps to `mastery_tool == "explain"`.
2. **After first kp mastered**: target moves to `path_m0_kp1` (Function Notation) → **EXPLAIN**.
3. **After a quiz failure on Function Notation** (1 failed attempt, mastery below 0.5): `scaffold_escalation` with attempts ≤ 2 and no linked example → **EXPLAIN** with `MEDIUM` scaffold.
4. **After an active misconception arises on Domain** (`mc_domain` node with `COMMONLY_CONFUSED_WITH` edge): `remediate_misconception` outranks normal progression → **REMEDIATE_MISCONCEPTION**, `focus == "mc_domain"`, strategy `MISCONCEPTION_CORRECTION`, `resource_node_ids == ["fix_domain"]`.
5. **After misconception graduated**: progression resumes → `path_m1_kp0` **EXPLAIN**.
6. **After all targets mastered**: **COMPLETE** with `trace.policy_applied == "complete"`.
7. **Replay verification**: re-running `engine.decide()` on the same inputs yields an identical `TeachingAction` (`replayed == expected_action`, `to_dict()` equal).

### Test 2 — `test_teaching_service_vertical_slice()`

Drives the full loop through the **TeachingService facade with SQLite persistence**:

1. A `LearningProgress` is saved via `LearningStore`; `TeachingService.decide()` builds the structural graph from modules, persists it to SQLite, and returns **EXPLAIN** on `path_m0_kp0`.
2. The persisted graph is reloaded and contains the module knowledge points.
3. Learner masters the first kp → engine moves on to `path_m0_kp1`.
4. An **extracted** teaching graph (with a misconception node) is persisted over the structural one; an active misconception drives the next decision to **REMEDIATE_MISCONCEPTION** with `resource_node_ids == ["fix_domain"]`.
5. After the misconception is graduated, normal progression resumes.

This proves: the graph persists across calls (SQLite), the engine responds deterministically to learner state, and a richer extracted graph changes the decision.

### Test 3 — `test_engine_differentiates_based_on_graph_structure()`

Same learner, same mastery, different graph wiring → different TeachingActions:
- Graph A (no example linked) → **EXPLAIN**
- Graph B (with a linked `EXAMPLE_OF` edge) → **SHOW_EXAMPLE**

This is the core proof that TeachingAction varies deterministically with the Knowledge Graph, not just with mastery.

## 10. Test Results

```
2754 passed, 7 skipped in 21.19s
```

All 7 skipped are baseline (pre-existing, unrelated to Teaching Core changes).

### Per-category breakdown

| Test suite | Tests | Status |
|-----------|-------|--------|
| Model contract (`test_model_contract.py`) | 11 | All passed |
| Graph queries (`test_graph_queries.py`) | 12 | All passed |
| Policy replay (`test_policy_replay.py`) | 4 | All passed |
| Vertical slice (`test_vertical_slice.py`) | 2 | All passed |
| Legacy teaching core (`test_teaching_core.py`) | 28 | All passed |
| Full regression (entire `deeptutor/`) | ~2,697 | All passed |

### Key test categories

- **Model contract tests**: serialisation round-trip, validation, version compatibility
- **Graph tests**: prerequisites (recursive/direct), successors, cycle detection (ordering vs non-ordering), misconceptions, teaching context, learning path, builder from modules
- **Policy replay tests**: deterministic replay (same input → same action), policy priority ordering, edge cases (empty goal, all mastered)
- **Vertical slice tests**: full closed-loop, graph-driven differentiation
- **Deterministic replay**: 3 replay tests pass — identical inputs produce identical `DecisionTrace`

## 11. Definition of Done — Checklist

| # | Requirement | Status |
|---|-------------|--------|
| 1 | Teaching Knowledge Model has unique canonical schema | Done — `models.py` is the single source of truth |
| 2 | Teaching Knowledge Graph can be persisted and queried | Done — SQLite/JSON/Memory repositories |
| 3 | Teaching Engine independently and deterministically produces TeachingAction | Done — 8-policy deterministic stack |
| 4 | LLM does not own teaching decisions | Done — `teaching_plan` tool is authoritative |
| 5 | `mastery_path` is connected to Teaching Engine | Done — `TeachingPlanTool` in `MASTERY_TOOL_TYPES` |
| 6 | LlamaIndex RAG and Teaching Knowledge Graph have clear separation | Done — RAG = evidence retrieval; Graph = teaching structure |
| 7 | Existing `LearningProgress` usable via Adapter, no second copy of state | Done — adapters project, never duplicate |
| 8 | At least one real learning material completes full vertical slice | Done — `test_vertical_slice_full_loop()` |
| 9 | All core decisions have DecisionTrace | Done — every action carries full trace |
| 10 | Deterministic replay tests pass | Done — 3 tests in `test_policy_replay.py` |
| 11 | Original core capabilities have no regression | Done — full regression passes |
| 12 | Full pytest passes | Done — 2754 passed, 7 skipped, 0 failed |

## 12. Items not yet implemented (v1+)

- **LLM-based content generation from TeachingAction**: the engine produces the action; the existing LLM loop (guided by the instruction) generates the content. Future work: explicit content templates per strategy.
- **Mastery estimation from accumulated evidence**: currently uses `LearningProgress.mastery_levels` directly. A Bayesian or evidence-count estimator could be added.
- **Review scheduler**: `due_reviews()` from `deeptutor.learning.policy` is used; no separate scheduler.
- **Learning Plan**: `LearningPlan` model exists but no dedicated planner capability.
- **Teaching Extraction integration**: `deeptutor/teaching_extraction/` produces `TeachingKnowledgeModel`; the TeachingService should be extended to import extracted graphs via `graph_repository.save_graph()`.
- **GraphRAG replacement**: the Teaching Knowledge Graph does not replace LlamaIndex RAG for document retrieval — they are complementary.
- **Multi-learner / multi-session support**: the repository protocol supports it but no higher-level orchestration.
- **Teaching Engine metrics**: no telemetry on policy hit rates, scaffold effectiveness, etc.
- **WebSocket events for TeachingAction**: currently the action is returned via the tool result; future work: emit `teaching_action` events on StreamBus.