"""Subprocess entry for the Persistent Checkpointer spike (crash/restart).

Usage:
    python _checkpointer_spike_worker.py thin <db> <thread> [--resume] [--crash]
    python _checkpointer_spike_worker.py intr_start <db> <thread> [--crash]
    python _checkpointer_spike_worker.py intr_resume <db> <thread> --reply <text>
    python _checkpointer_spike_worker.py get_state <db> <thread>

``--crash`` calls ``os._exit`` immediately after the phase write, so the SQLite
writer is killed without graceful teardown — a faithful mid-write crash that
must still leave a durable, resumable checkpoint.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # harness sibling
_repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _repo_root)  # repo root (lumen)
import _checkpointer_spike as hp  # noqa: E402


def _main() -> None:
    args = sys.argv[1:]
    if not args:
        print(json.dumps({"error": "no phase"}), file=sys.stderr)
        raise SystemExit(2)
    phase = args[0]
    crash = "--crash" in args
    args = [a for a in args if a not in ("--crash", "--resume")]

    if phase in ("start_op", "retry_op"):
        db, thread = args[1], args[2]
        operation = phase[: -len("_op")]
        out = asyncio.run(hp.run_provider_op(db, thread, operation))
    elif phase == "thin":
        db, thread = args[1], args[2]
        resume = "--resume" in sys.argv[1:]
        out = asyncio.run(hp.run_thin_phase(db, thread, resume=resume))
    elif phase == "intr_start":
        db, thread = args[1], args[2]
        out = asyncio.run(hp.run_interrupt_phase(db, thread, phase="start"))
    elif phase == "intr_resume":
        db, thread = args[1], args[2]
        reply = args[4] if len(args) > 4 and args[3] == "--reply" else "yes"
        out = asyncio.run(hp.run_interrupt_phase(db, thread, phase="resume", inject_reply=reply))
    elif phase == "get_state":
        db, thread = args[1], args[2]
        out = asyncio.run(hp.dump_state(db, thread))
    else:
        print(json.dumps({"error": f"unknown phase {phase}"}), file=sys.stderr)
        raise SystemExit(2)

    print(json.dumps(out, ensure_ascii=False, default=str), flush=True)
    if crash:
        os._exit(0)  # hard kill: no connection/atexit cleanup runs


if __name__ == "__main__":
    _main()