from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from airmonitor.database import (
    SCHEMA_VERSION,
    connect,
    init_db,
    insert_sgx_voc_sample,
    start_or_update_print,
)
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


def test_schema_migrates_chamber_temperature_history(tmp_path: Path) -> None:
    conn = connect(tmp_path / "airmonitor.sqlite3")
    init_db(conn)

    print_columns = {row["name"] for row in conn.execute("PRAGMA table_info(prints)")}
    sample_columns = {row["name"] for row in conn.execute("PRAGMA table_info(sgx_voc_samples)")}
    versions = {row["version"] for row in conn.execute("SELECT version FROM schema_version")}

    assert "chamber_temperature_c" in print_columns
    assert "chamber_temperature_c" in sample_columns
    assert SCHEMA_VERSION in versions
    conn.close()


def test_chamber_temperature_is_stored_with_print_and_sgx_sample(tmp_path: Path) -> None:
    conn = connect(tmp_path / "airmonitor.sqlite3")
    init_db(conn)
    conn.execute(
        "INSERT INTO sensors(sensor_id, manufacturer, product, model, transport) "
        "VALUES ('sgx-voc-01', 'Amphenol', 'PS1', 'PS1', 'usb-uart')"
    )
    state = {
        "connected": True,
        "active": True,
        "gcode_state": "RUNNING",
        "chamber_temperature_c": 36.5,
    }
    print_id = start_or_update_print(
        conn,
        print_id=None,
        printer_state=state,
        printer_available="online",
        started_state="RUNNING",
    )
    insert_sgx_voc_sample(
        conn,
        sensor_id="sgx-voc-01",
        session_id=None,
        print_id=print_id,
        sensor_protocol="2023",
        sensor_port="/dev/airmonitor-sgx",
        measurement=SimpleNamespace(
            gas_ppm=0.1,
            gas_mass=0.0,
            full_scale=1000,
            temperature_c=24.0,
            humidity_rh=45.0,
        ),
        printer_state=state,
        frame_hex="ff",
    )

    assert conn.execute(
        "SELECT chamber_temperature_c FROM prints WHERE id = ?", (print_id,)
    ).fetchone()[0] == 36.5
    assert conn.execute(
        "SELECT chamber_temperature_c FROM sgx_voc_samples WHERE print_id = ?", (print_id,)
    ).fetchone()[0] == 36.5
    conn.close()
