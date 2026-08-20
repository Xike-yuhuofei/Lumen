"""JSON → Learner-Domain SQLite migration.

One-shot, idempotent, verifiable, and non-destructive to the source JSON.

* Every legacy ``quiz_attempt`` becomes a canonical evidence row with a
  deterministic legacy id.
* The aggregate snapshot is imported at its legacy ``version`` (marked via a
  synthetic ``legacy-import`` commit); its next real commit bumps +1.
* A ``legacy_state_imported`` learner event (rather than fabricated high-quality
  evidence) records provenance for non-reducible legacy state.
* Re-running imports nothing new; a failure *never* switches authority or
  mutates the JSON. Rollback deletes the imported rows (JSON stays intact).

Legacy qualitative gates are imported with ``evaluator_kind`` / ``policy_version``
reflecting their true (unknown) provenance — never disguised as new evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import logging
from pathlib import Path
import time

from lumen.modes.learn.commit.constants import EVIDENCE_SCHEMA_VERSION, STATE_SCHEMA_VERSION
from lumen.modes.learn.commit.identity import (
    legacy_action_id,
    legacy_evidence_id,
    stable_hash,
)
from lumen.modes.learn.commit.repository import LearnerDomainRepository, now_ms
from lumen.modes.learn.domain.models import LearningProgress

logger = logging.getLogger(__name__)

_MIGRATION_ACTION_PREFIX = "legacy-import"


@dataclass
class MigrationResult:
    imported: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"imported={len(self.imported)} skipped={len(self.skipped)} "
            f"errors={len(self.errors)}"
        )


def _source_hash(path: Path) -> str:
    return stable_hash(path.read_bytes().decode("utf-8", errors="replace"))


def _schema_variant(progress: LearningProgress) -> str:
    variants = []
    if progress.goal_name:
        variants.append("goal_name")
    if progress.description:
        variants.append("description")
    if progress.source_kb:
        variants.append("source_kb")
    return "+".join(sorted(set(variants)))


def _attempt_evidence(learner_id: str, index: int, attempt: dict) -> dict:
    """Map one legacy ``QuizAttempt`` dict to an evidence row."""
    payload = stable_hash(attempt)
    action_id = legacy_action_id(learner_id, index=index, payload_hash=payload)
    is_feynman = str(attempt.get("question_id") or "").startswith("feynman:")
    outcome = {
        "is_correct": bool(attempt.get("is_correct")),
        "question_id": attempt.get("question_id") or "",
        "module_id": attempt.get("module_id") or "",
        "question_kind": attempt.get("question_kind") or "recall",
        "self_attribution": attempt.get("self_attribution") or "",
        "misconception_node_id": attempt.get("misconception_node_id") or "",
    }
    if attempt.get("error_type"):
        outcome["error_type"] = attempt["error_type"]
    if is_feynman:
        outcome["question_kind"] = "application"
        return {
            "evidence_id": legacy_evidence_id(learner_id, action_id),
            "learner_id": learner_id,
            "action_id": action_id,
            "ordinal": 0,
            "decision_id": None,
            "session_id": "",
            "turn_id": "",
            "target_type": "knowledge_point",
            "target_id": attempt.get("knowledge_point_id") or "",
            "evidence_type": "feynman_explanation",
            "assessment_id": "",
            "outcome_json": json.dumps({"passed": bool(attempt.get("is_correct")), **outcome}),
            "raw_response_json": json.dumps(
                {"user_answer": attempt.get("user_answer") or ""}
            ),
            "evaluator_kind": "legacy-import",
            "evaluator_version": "unavailable",
            "policy_version": "",
            "observed_at_ms": int(float(attempt.get("timestamp") or time.time()) * 1000),
            "recorded_at_ms": now_ms(),
            "supersedes_evidence_id": None,
            "schema_version": EVIDENCE_SCHEMA_VERSION,
            "payload_hash": payload,
        }
    return {
        "evidence_id": legacy_evidence_id(learner_id, action_id),
        "learner_id": learner_id,
        "action_id": action_id,
        "ordinal": 0,
        "decision_id": None,
        "session_id": "",
        "turn_id": "",
        "target_type": "knowledge_point",
        "target_id": attempt.get("knowledge_point_id") or "",
        "evidence_type": "quiz_answer",
        "assessment_id": "",
        "outcome_json": json.dumps({"is_correct": bool(attempt.get("is_correct")), **outcome}),
        "raw_response_json": json.dumps({"user_answer": attempt.get("user_answer") or ""}),
        "evaluator_kind": "deterministic",
        "evaluator_version": "legacy-v1",
        "policy_version": "",
        "observed_at_ms": int(float(attempt.get("timestamp") or time.time()) * 1000),
        "recorded_at_ms": now_ms(),
        "supersedes_evidence_id": None,
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "payload_hash": payload,
    }


def migrate_learning_json(
    root_dir: Path,
    repository: LearnerDomainRepository | None = None,
) -> MigrationResult:
    """Import every ``<book_id>.json`` under ``root_dir`` into ``learner.db``.

    Idempotent: learners already present in ``migration_log`` are skipped. Any
    damaged JSON fails closed (raising) and the authority is not switched.
    """
    repo = repository or LearnerDomainRepository()
    result = MigrationResult()
    already = repo.migrated_learner_ids()

    json_paths = sorted(
        p for p in root_dir.glob("*.json") if not p.name.startswith(".")
    )
    for path in json_paths:
        learner_id = path.stem
        if learner_id in already:
            result.skipped.append(learner_id)
            continue
        try:
            _import_one(repo, path, learner_id)
            result.imported.append(learner_id)
        except Exception as exc:  # fail closed
            logger.exception("Migration failed for %s", learner_id)
            repo._conn.rollback()
            result.errors.append({"book_id": learner_id, "error": str(exc)})
    return result


def _import_one(repo: LearnerDomainRepository, path: Path, learner_id: str) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    progress = LearningProgress.model_validate(data)  # raises → fail closed
    state_hash = stable_hash(progress.model_dump(mode="json"))
    source_hash = _source_hash(path)
    legacy_version = int(progress.version or 0)
    action_id = f"{_MIGRATION_ACTION_PREFIX}:{learner_id}"
    commit_id = f"{_MIGRATION_ACTION_PREFIX}:{learner_id}"
    ts = now_ms()

    with repo.tx():
        # Aggregate first (domain_commits references it via FK).
        repo.insert_aggregate(
            learner_id=learner_id,
            new_version=legacy_version,
            state_json=json.dumps(progress.model_dump(mode="json"), ensure_ascii=False),
            state_hash=state_hash,
            commit_id=commit_id,
            now_ms=ts,
        )
        # Synthetic import commit (auditable; keeps the learner_events FK valid).
        repo.insert_commit(
            {
                "commit_id": commit_id,
                "learner_id": learner_id,
                "action_id": action_id,
                "decision_id": None,
                "expected_learner_version": 0,
                "actual_base_version": 0,
                "resulting_learner_version": legacy_version,
                "status": "APPLIED",
                "request_hash": stable_hash({"migration": source_hash}),
                "receipt_json": json.dumps(
                    {
                        "commit_id": commit_id,
                        "status": "APPLIED",
                        "resulting_version": legacy_version,
                        "migration": True,
                    },
                    ensure_ascii=False,
                ),
                "committed_at_ms": ts,
            }
        )
        for idx, attempt in enumerate(progress.quiz_attempts or []):
            repo.insert_evidence(
                _attempt_evidence(learner_id, idx, attempt.model_dump(mode="json"))
            )
        repo.insert_learner_event(
            {
                "event_id": _MIGRATION_ACTION_PREFIX + ":event:" + learner_id,
                "learner_id": learner_id,
                "learner_version": legacy_version,
                "commit_id": commit_id,
                "ordinal": 0,
                "event_type": "legacy_state_imported",
                "payload_json": json.dumps(
                    {
                        "schema_variant": _schema_variant(progress),
                        "schema_version": STATE_SCHEMA_VERSION,
                    },
                    ensure_ascii=False,
                ),
                "evidence_ids_json": json.dumps([]),
                "reducer_version": "migration",
                "created_at_ms": ts,
            }
        )
        repo.mark_migrated(
            {
                "learner_id": learner_id,
                "source_path": str(path),
                "source_hash": source_hash,
                "state_hash": state_hash,
                "schema_variant": _schema_variant(progress),
                "imported_at": time.time(),
                "result": "ok",
            }
        )


def verify_migration(
    root_dir: Path,
    repository: LearnerDomainRepository | None = None,
) -> dict:
    """Check that every JSON under ``root_dir`` round-trips into ``learner.db``.

    Returns ``{ok, checks, mismatches}``.
    """
    repo = repository or LearnerDomainRepository()
    checks = []
    mismatches = []
    for path in sorted(root_dir.glob("*.json")):
        if path.name.startswith("."):
            continue
        learner_id = path.stem
        data = json.loads(path.read_text(encoding="utf-8"))
        agg = repo.get_aggregate(learner_id)
        if agg is None:
            mismatches.append({"book_id": learner_id, "reason": "missing aggregate"})
            continue
        state = json.loads(agg["state_json"])
        # Normalise the source through the same model so round-trip is
        # canonical (enums, default fields, key order), mirroring _import_one.
        canonical_source = LearningProgress.model_validate(data).model_dump(mode="json")
        if stable_hash(state) != stable_hash(canonical_source):
            mismatches.append({"book_id": learner_id, "reason": "state_hash mismatch"})
            continue
        checks.append(learner_id)
    return {
        "ok": not mismatches and bool(checks),
        "checked": checks,
        "mismatches": mismatches,
    }


def rollback_migration(
    learner_ids: list[str], repository: LearnerDomainRepository | None = None
) -> None:
    """Delete imported rows for ``learner_ids`` (JSON is left untouched)."""
    repo = repository or LearnerDomainRepository()
    for learner_id in learner_ids:
        if repo.exists(learner_id):
            repo.delete_aggregate(learner_id)


__all__ = [
    "migrate_learning_json",
    "verify_migration",
    "rollback_migration",
    "MigrationResult",
]