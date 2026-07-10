from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from airmonitor.database import connect, init_db
from airmonitor.database.repositories import FilterControlRepository
from airmonitor.filters.control import resolve_filter_state
from airmonitor.state_freshness import assess_state, safe_automation_request


def test_fresh_policy_request_flows_to_filter_controller(tmp_path: Path) -> None:
    conn = connect(tmp_path / "airmonitor.sqlite3")
    init_db(conn)
    repo = FilterControlRepository(conn)

    freshness = assess_state(
        {"updated_at": datetime.now(timezone.utc).isoformat(), "gcode_state": "RUNNING"},
        max_age_seconds=120,
    )
    automation_request, reason = safe_automation_request("on", freshness)
    assert automation_request == "on"

    record = repo.update("bento", automation_request=automation_request, reason=reason)
    decision = resolve_filter_state(
        filter_id="bento",
        manual_mode=record.manual_mode,
        automation_request=record.automation_request,
        automation_reason=record.reason or "automation",
    )
    assert decision.effective_state.value == "on"

    persisted = repo.update(
        "bento",
        effective_state=decision.effective_state.value,
        reason=decision.reason,
    )
    assert persisted.automation_request == "on"
    assert persisted.effective_state == "on"
    conn.close()


def test_manual_off_wins_over_fresh_automation_on(tmp_path: Path) -> None:
    conn = connect(tmp_path / "airmonitor.sqlite3")
    init_db(conn)
    repo = FilterControlRepository(conn)
    repo.set_manual_mode("levoit", "off")
    record = repo.update("levoit", automation_request="on", reason="printing ABS")

    decision = resolve_filter_state(
        filter_id="levoit",
        manual_mode=record.manual_mode,
        automation_request=record.automation_request,
        automation_reason=record.reason or "automation",
    )
    assert decision.effective_state.value == "off"
    assert decision.reason == "manual override: off"
    conn.close()
