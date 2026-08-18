"""The built-in ``cron`` tool: schema contract, owner injection, actions."""

from __future__ import annotations

import time

import pytest

from lumen.app.cron.service import CronService
from lumen.runtime.tools.builtin.cron_tool import run_cron_action


@pytest.fixture
def cron_service(tmp_path, monkeypatch):
    import lumen.app.cron.service as service_mod
    import lumen.runtime.tools.builtin.cron_tool as tool_mod

    service = CronService(store_path=tmp_path / "jobs.json")
    monkeypatch.setattr(service_mod, "_service", service)
    monkeypatch.setattr(tool_mod, "get_cron_service", lambda: service)
    return service


CHAT_OWNER = {"kind": "chat", "user_id": "local-admin", "session_id": "s1"}
OTHER_OWNER = {"kind": "chat", "user_id": "another-user", "session_id": "s2"}


class TestCronTool:
    def test_requires_injected_owner(self, cron_service):
        outcome = run_cron_action({"action": "schedule", "message": "x", "every_seconds": 60})
        assert outcome.ok is False
        assert "not available" in outcome.text

    def test_schedule_every_and_list_and_cancel(self, cron_service):
        outcome = run_cron_action(
            {
                "action": "schedule",
                "message": "summarize my day",
                "name": "daily recap",
                "every_seconds": 3600,
                "_cron_owner": CHAT_OWNER,
            }
        )
        assert outcome.ok, outcome.text
        job_id = outcome.meta["job_id"]

        listed = run_cron_action({"action": "list", "_cron_owner": CHAT_OWNER})
        assert job_id in listed.text and "daily recap" in listed.text

        # Another owner can't see or cancel it.
        other = run_cron_action({"action": "list", "_cron_owner": OTHER_OWNER})
        assert "No scheduled tasks" in other.text
        steal = run_cron_action({"action": "cancel", "job_id": job_id, "_cron_owner": OTHER_OWNER})
        assert steal.ok is False

        cancelled = run_cron_action(
            {"action": "cancel", "job_id": job_id, "_cron_owner": CHAT_OWNER}
        )
        assert cancelled.ok, cancelled.text

    def test_nanobot_action_aliases(self, cron_service):
        outcome = run_cron_action(
            {
                "action": "add",
                "message": "summarize my day",
                "every_seconds": 3600,
                "_cron_owner": CHAT_OWNER,
            }
        )
        assert outcome.ok, outcome.text
        job_id = outcome.meta["job_id"]

        cancelled = run_cron_action(
            {"action": "remove", "job_id": job_id, "_cron_owner": CHAT_OWNER}
        )
        assert cancelled.ok, cancelled.text

    def test_schedule_at_parses_iso(self, cron_service):
        from datetime import datetime, timedelta

        at = (datetime.now().astimezone() + timedelta(hours=1)).isoformat()
        outcome = run_cron_action(
            {"action": "schedule", "message": "remind me", "at": at, "_cron_owner": CHAT_OWNER}
        )
        assert outcome.ok, outcome.text
        job = cron_service.get_job(outcome.meta["job_id"])
        assert job is not None and job.schedule.kind == "at"
        assert job.delete_after_run is True

    def test_schedule_requires_exactly_one_kind(self, cron_service):
        outcome = run_cron_action(
            {
                "action": "schedule",
                "message": "x",
                "every_seconds": 60,
                "cron_expr": "0 9 * * *",
                "_cron_owner": CHAT_OWNER,
            }
        )
        assert outcome.ok is False
        assert "exactly one" in outcome.text

    def test_schedule_rejected_inside_cron_context(self, cron_service):
        outcome = run_cron_action(
            {
                "action": "schedule",
                "message": "x",
                "every_seconds": 60,
                "_cron_owner": CHAT_OWNER,
                "_cron_in_context": True,
            }
        )
        assert outcome.ok is False
        assert "inside a running scheduled task" in outcome.text

    def test_schedule_rejects_past_at(self, cron_service):
        outcome = run_cron_action(
            {
                "action": "schedule",
                "message": "x",
                "at": "2020-01-01T00:00:00",
                "_cron_owner": CHAT_OWNER,
            }
        )
        assert outcome.ok is False
        assert "past" in outcome.text


class TestRegistryIntegration:
    def test_cron_tool_is_builtin_and_automounted(self):
        from deeptutor.agents._shared.tool_composition import AUTO_MOUNTED_TOOLS
        from deeptutor.tools.builtin import BUILTIN_TOOL_NAMES

        assert "cron" in BUILTIN_TOOL_NAMES
        assert "cron" in AUTO_MOUNTED_TOOLS

    def test_schema_has_action_enum(self):
        from deeptutor.tools.builtin import CronTool

        schema = CronTool().get_definition().to_openai_schema()
        action = schema["function"]["parameters"]["properties"]["action"]
        assert set(action["enum"]) == {"schedule", "list", "cancel"}
