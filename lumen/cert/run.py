"""Real certification runner for the Phase 1 Teaching Behavior Optimization Loop.

Canonical home: ``lumen/cert``.

Runs the CertificationController against the **real** Lumen LLM
(:class:`lumen.cert.llm.RealLumenGateway` -> the unified
``lumen.shared._util.llm.complete`` factory the production agent-loop model
uses). All three Evaluators, the Learner Simulator, Failure Reviewer and
Engineering Agent share that gateway.

Usage::

    python -m lumen.cert.run --subject "HTTP Protocol Basics" [--budget 3] [--db PATH]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time

from .engine import Budget, CertificationController, build_contexts
from .llm import ModelRoute, MultiModelGateway, RealLumenGateway
from .models import CandidateManifest, content_digest
from .store import CertificationStore


def _build_candidate(subject: str, goal: str) -> CandidateManifest:
    kps = [
        "HTTP request/response & message structure",
        "methods (GET/POST/PUT/PATCH/DELETE) semantics",
        "status-code classes (2xx/3xx/4xx/5xx)",
        "headers & content types",
    ]
    cfg = {
        "subject": subject,
        "goal": goal or f"Understand the fundamentals of {subject}",
        "knowledge_points": kps,
        "learner_profile": "a curious adult beginner",
        "path_id": "p1-val-path",
    }
    payload = {"tutor_config": cfg, "prompt_override": "", "temperature": 0.2}
    return CandidateManifest(
        effective_candidate_id="cand-real-base",
        parent_candidate_id=None,
        content_digest=content_digest(payload),
        tutor_config=cfg,
        prompt_override="",
        temperature=0.2,
    )


def _real_gateway(
    *,
    binding: str,
    base_url: str,
    model: str,
    api_key_env: str,
    timeout: float = 90.0,
) -> RealLumenGateway:
    """Build a real provider gateway; API key comes from env only (credential rule)."""
    return RealLumenGateway(
        timeout=timeout,
        model=model,
        binding=binding,
        base_url=base_url,
        api_key=os.environ.get(api_key_env, "") or None,
    )


def build_role_gateway(
    timeout: float = 180.0,
    *,
    tutor_timeout: float = 240.0,
    learner_timeout: float = 150.0,
) -> MultiModelGateway:
    """Route each LLM role to a real model.

    Tutor  → Gitee GLM-5.2                  (GITEE_API_KEY)
    Learner→ DeepSeek deepseek-v4-flash     (DEEPSEEK_API_KEY)
    Evaluator / Diagnosis / Engineering → localhost:48760 gpt-5.6-terra
                                          (CODEXMANAGER_API_KEY)
    """
    eval_gw = _real_gateway(
        binding="codexmanager", base_url="http://localhost:48760/v1",
        model="gpt-5.6-terra", api_key_env="CODEXMANAGER_API_KEY", timeout=timeout,
    )
    routes = [
        ModelRoute("tutor", _real_gateway(
            binding="gitee", base_url="https://ai.gitee.com/v1",
            model="GLM-5.2", api_key_env="GITEE_API_KEY", timeout=tutor_timeout,
        )),
        ModelRoute("learner", _real_gateway(
            binding="deepseek", base_url="https://api.deepseek.com",
            model="deepseek-v4-flash", api_key_env="DEEPSEEK_API_KEY", timeout=learner_timeout,
        )),
        ModelRoute("diagnosis", eval_gw),
        ModelRoute("engineering", eval_gw),
        ModelRoute("evaluator", eval_gw),
    ]
    return MultiModelGateway(routes=routes, default=eval_gw)


async def run(
    *,
    subject: str,
    goal: str = "",
    db_path: str,
    language: str = "en",
    patch_budget: int = 3,
    timeout: float = 180.0,
) -> dict:
    store = CertificationStore(db_path)
    scenario = {"subject": subject}
    eval_config = {
        "rubric_version": "phase1-core-1.0",
        "perspectives": ["correctness", "pedagogy", "context"],
    }
    contexts = build_contexts(scenario=scenario, evaluation_config=eval_config)
    gateway = build_role_gateway(timeout=timeout)
    controller = CertificationController(
        gateway=gateway,
        store=store,
        candidate=_build_candidate(subject, goal),
        contexts=contexts,
        scenario=scenario,
        language=language,
        budget=Budget(patch_budget=patch_budget),
    )
    started = time.time()
    outcome = await controller.certify()
    elapsed = round(time.time() - started, 2)

    report = {
        "goal": "Phase 1 Teaching Behavior Optimization Loop",
        "status": outcome.status.value,
        "effective_candidate_id": outcome.candidate_id,
        "trajectory_context_id": outcome.trajectory_context_id,
        "evaluation_context_id": outcome.evaluation_context_id,
        "episode_id": outcome.episode_id,
        "final_turn_statuses": outcome.final_turn_statuses,
        "patches_applied": outcome.patches_applied,
        "blocked_reason": outcome.blocked_reason,
        "message": outcome.message,
        "language": language,
        "elapsed_seconds": elapsed,
        "db_path": db_path,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    outcome_path = db_path.replace(".db", "_outcome.json")
    with open(outcome_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 1 real certification run")
    parser.add_argument("--subject", default="HTTP Protocol Basics")
    parser.add_argument("--goal", default="")
    parser.add_argument("--db", default="data/user/workspace/runtime/cert_phase1.db")
    parser.add_argument("--language", default="en")
    parser.add_argument("--budget", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=180.0)
    args = parser.parse_args()
    asyncio.run(
        run(
            subject=args.subject,
            goal=args.goal,
            db_path=args.db,
            language=args.language,
            patch_budget=args.budget,
            timeout=args.timeout,
        )
    )


if __name__ == "__main__":
    main()