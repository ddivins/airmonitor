"""Guards the v1.0 upgrade-path promise in docs/update-rollback.md: any
tagged version can update in place to any later one because schema
migrations are additive only. Simulates updating an appliance whose
database predates a schema change and asserts existing data survives
untouched.
"""

from __future__ import annotations

from pathlib import Path

from airmonitor.database import SCHEMA_VERSION, connect, init_db


def test_upgrading_a_pre_alert_events_database_preserves_existing_data(tmp_path: Path) -> None:
    db_path = tmp_path / "airmonitor.sqlite3"
    conn = connect(str(db_path))
    init_db(conn)

    # Seed data representing a real, already-running appliance.
    conn.execute("INSERT INTO sensors (sensor_id, transport) VALUES ('sgx-1', 'usb-uart')")
    conn.execute(
        "INSERT INTO sgx_voc_samples (sensor_id, sampled_at, gas_ppm) VALUES ('sgx-1', '2026-01-01T00:00:00Z', 2.5)"
    )
    conn.execute(
        "INSERT INTO filter_control_state (filter_id, manual_mode, automation_request, actual_state, effective_state, reason) "
        "VALUES ('bento', 'auto', 'on', 'on', 'on', 'printer active')"
    )
    conn.commit()

    # Roll the database back to look like it predates alert_events (added at
    # SCHEMA_VERSION 8), simulating an appliance that hasn't been updated
    # since before that change shipped.
    conn.execute("DROP INDEX IF EXISTS idx_alert_events_key")
    conn.execute("DROP INDEX IF EXISTS idx_alert_events_open")
    conn.execute("DROP TABLE alert_events")
    conn.execute("DELETE FROM schema_version WHERE version = ?", (SCHEMA_VERSION,))
    conn.commit()

    tables_before = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "alert_events" not in tables_before

    # This is the exact call every service entry point and airmonitor-doctor
    # make on every start; tools/update.sh relies on it being safe to rerun
    # against an existing, populated database.
    init_db(conn)

    tables_after = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "alert_events" in tables_after

    sample = conn.execute("SELECT sensor_id, gas_ppm FROM sgx_voc_samples").fetchone()
    assert tuple(sample) == ("sgx-1", 2.5)

    filter_row = conn.execute(
        "SELECT effective_state, reason FROM filter_control_state WHERE filter_id = 'bento'"
    ).fetchone()
    assert tuple(filter_row) == ("on", "printer active")

    versions = {row[0] for row in conn.execute("SELECT version FROM schema_version")}
    assert SCHEMA_VERSION in versions

    # The new table isn't just present, it's immediately usable.
    conn.execute("INSERT INTO alert_events (alert_key, level, message) VALUES ('sgx_gas_ppm', 'warning', 'test')")
    conn.commit()
    assert conn.execute("SELECT COUNT(*) FROM alert_events").fetchone()[0] == 1

    conn.close()
