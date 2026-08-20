# Teaching Architecture Bake-off — Report

## Verdict
**CONTINUE EXPERIMENT** — After the parity-gap closure Candidate B's as-shipped graph now completes the SAME share of the matrix as Candidate A (teaching effect at parity: identical completion rate, mastery and misconception diagnosis/remediation). The remaining question is not whether B can teach, but whether it teaches *better* — the current deterministic simulated-learner evidence shows parity, not superiority, so continue the experiment rather than promote or discard.

## Evidence basis
Deterministic simulated-learner A/B within the existing Learn eval harness: both candidates share the same materials, learners, deterministic Teaching Engine, scheduler and learning store; the only variable is who walks the teaching loop.

## Matrix summary (completion / efficiency / diagnosis / cost)

| candidate | runs | completed | rate | avg steps* | cap gain/step* | diagnosed | remed. | retention* | transfer* | model LLM calls/run |
|---|---|---|---|---|---|---|---|---|---|---|
| a | 10 | 8 | 80% | 19.875 | 0.558 | 0.50 | 0.50 | 0.750 | 1.000 | 45.9 |
| b_virgin | 10 | 8 | 80% | 21.875 | 0.540 | 0.50 | 0.50 | 0.750 | 1.000 | 13.4 |
| b_seeded | 10 | 8 | 80% | 21.000 | 0.595 | 0.50 | 0.50 | 0.750 | 1.000 | 11 |

*avg steps / cap gain per step / retention / transfer computed only over completed episodes.
**model LLM calls/run is architecture-modeled (A = whole-loop LLM turns; B = content fills only).**

## Architecture comparison

- **PolicyDecision / teaching-path interpretability**  
  - A: advisory DecisionTrace via teaching_plan; the ACTUAL executed path is LLM-authored and not persisted deterministically
  - B: explicit immutable PolicyDecision (decision_id/policy_version/trace) committed and replayable
- **Lineage / auditability**  
  - A: evidence trail in the domain ledger, but no stable teaching_session->decision engine decision id for the executed flow
  - B: teaching_session_id -> decision_id -> action_id -> evidence_id -> commit_id persisted chain
- **Crash / resume / replay correctness**  
  - A: depends on the LLM re-observing state each turn (no deterministic replay knob)
  - B: passed the Fault / Concurrency / Replay Hard Gate; durable checkpoint + idempotent domain commits
- **Latency**  
  - A: one full LLM agent-loop (a large, multi-tool, multi-token turn) per teaching round — the highest-latency path
  - B: every decision is deterministic (0 LLM); only the decided content action calls the Agent Runtime — low latency when it runs
- **Token / model-call overhead**  
  - A: ~46 whole-loop LLM turns/episode (expensive, per round)
  - B: 0 decision LLM calls + ~13 content-fill calls/episode on average (cheap generations; decisions are deterministic and free)
- **Checkpoint / storage overhead**  
  - A: domain ledger only; no execution-path checkpoint
  - B: adds teaching_graph checkpoint + teaching_session governor + policy_decisions ledger (separate DBs, small)
- **Runtime / Mode / Domain ownership clarity**  
  - A: pedagogy split across tools + LLM; Agent Runtime owns the loop
  - B: explicit 3-way separation: graph (flow) | Agent Runtime (content primitive) | DomainCommit (authority)
- **Future deterministic policy / experiment / bandit**  
  - A: harder: the flow is not a replayable deterministic artifact
  - B: designed for it: deterministic engine + immutable decisions are a direct experiment/bandit seam

### Code-size (real source LOC, non-empty lines)

- Candidate A tool+capability surface: 1086 LOC
- Candidate B graph+governor+domain-commit: 3073 LOC
- Shared deterministic engine/policy (used by both): 3126 LOC

## Interpretation / residual risk
- The three Candidate-B parity gaps are closed: a fresh learner now leaves `first_exposure` through a posed follow-up (no more content-only spin), CONCEPT/DESIGN objectives enter the qualitative gate via feynman evidence, and wrong answers matched to registered misconceptions drive a `remediate_misconception` path that re-assesses and graduates. These were coverage gaps in the *candidate*, fixed inside the Teaching Session Graph + Domain Commit without touching the engine or Candidate A.
- B's teaching effect is now at parity with A (identical completion rate and identical misconception detection/remediation counts per learner), at a fraction of the LLM-call cost. B remains slightly step-inefficient for struggling (Weak) learners, and the current deterministic simulated-learner evidence cannot discriminate retention/transfer between the two architectures — a real-LLM trial would be the decisive axis. That is why the verdict is CONTINUE EXPERIMENT, not PROMOTE.
- B costs far fewer LLM calls (decisions are deterministic) and offers strictly better lineage/replay/interpretability/crash-resume, and those advantages are now accompanied by a *comparable* teaching effect rather than a coverage gap.
- Retention/transfer are post-episode probes of the SAME learner model, so they measure learner+content outcomes, not the architecture: both candidates funnel through the identical engine + scheduler + learner, and their measured retention/transfer match by construction where they both reach the same mastered state. A real-LLM learner trial would be needed to discriminate these two axes between architectures (residual evidence gap).

_Generated by `run_bakeoff.py`; raw evidence in `teaching_bakeoff_evidence.json`._