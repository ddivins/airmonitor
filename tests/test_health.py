from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from airmonitor.database import connect, init_db, start_sensor_session
from airmonitor.health import _package_version, check_sensor_freshness, format_text, run_checks
from airmonitor.sps30_service import ensure_schema as ensure_sps30_schema


def test_health_report_uses_temporary_database(tmp_path: Path) -> None:
    db_path = tmp_path / "airmonitor.sqlite3"
    serial_path = tmp_path / "serial"
    serial_path.touch()
    report = run_checks(
        database=str(db_path),
        serial_device=str(serial_path),
        mqtt_host="127.0.0.1",
        mqtt_port=9,
        grafana_host="127.0.0.1",
        grafana_port=9,
        include_systemd=False,
    )

    assert report["ok"] is True
    checks = {item["name"]: item for item in report["checks"]}
    assert checks["sensor_hardware"]["status"] == "ok"
    assert checks["database"]["status"] == "ok"
    assert checks["database_schema"]["status"] == "ok"
    assert checks["mqtt"]["status"] == "warn"
    assert checks["grafana"]["status"] == "warn"
    # No samples recorded yet on a freshly initialized database.
    assert checks["sgx_freshness"]["status"] == "warn"
    assert checks["sps30_freshness"]["status"] == "warn"


def test_sps30_session_records_installed_package_version(tmp_path: Path) -> None:
    from airmonitor import sps30_service

    db_path = tmp_path / "airmonitor.sqlite3"
    conn = connect(str(db_path))
    ensure_sps30_schema(conn)
    conn.execute(
        "INSERT INTO sensors (sensor_id, transport) VALUES (?, 'usb-uart')",
        ("sps30-1",),
    )
    conn.commit()

    session_id = start_sensor_session(
        conn,
        sensor_id="sps30-1",
        software_version=sps30_service._package_version(),
        sensor_protocol="SHDLC",
        sensor_port="/dev/ttyUSB0",
    )

    recorded = conn.execute(
        "SELECT software_version FROM sensor_sessions WHERE id = ?", (session_id,)
    ).fetchone()[0]
    assert recorded == _package_version()
    conn.close()


def _insert_sample(db_path: Path, table: str, sensor_id: str, sampled_at: str) -> None:
    conn = connect(str(db_path))
    if table == "sps30_samples":
        ensure_sps30_schema(conn)
    else:
        init_db(conn)
    conn.execute(
        "INSERT INTO sensors (sensor_id, transport) VALUES (?, 'usb-uart')",
        (sensor_id,),
    )
    conn.execute(
        f"INSERT INTO {table} (sensor_id, sampled_at) VALUES (?, ?)",
        (sensor_id, sampled_at),
    )
    conn.commit()
    conn.close()


def test_sensor_freshness_reports_ok_for_recent_sample(tmp_path: Path) -> None:
    db_path = tmp_path / "airmonitor.sqlite3"
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    _insert_sample(db_path, "sgx_voc_samples", "sgx-1", now)

    checks = {check.name: check for check in check_sensor_freshness(str(db_path))}
    assert checks["sgx_freshness"].status == "ok"
    assert checks["sps30_freshness"].status == "warn"


def test_sensor_freshness_reports_warn_for_stale_sample(tmp_path: Path) -> None:
    db_path = tmp_path / "airmonitor.sqlite3"
    _insert_sample(db_path, "sps30_samples", "sps30-1", "2000-01-01T00:00:00Z")

    checks = {check.name: check for check in check_sensor_freshness(str(db_path))}
    assert checks["sps30_freshness"].status == "warn"
    assert "offline" in checks["sps30_freshness"].detail
    assert checks["sps30_freshness"].required is False


def test_format_text_summarizes_ok_report(tmp_path: Path) -> None:
    db_path = tmp_path / "airmonitor.sqlite3"
    serial_path = tmp_path / "serial"
    serial_path.touch()
    report = run_checks(
        database=str(db_path),
        serial_device=str(serial_path),
        mqtt_host="127.0.0.1",
        mqtt_port=9,
        grafana_host="127.0.0.1",
        grafana_port=9,
        include_systemd=False,
    )

    text = format_text(report)

    assert text.startswith("AirMonitor doctor: OK ")
    assert "sensor_hardware" in text
    assert "[ok" in text
    assert "[warn" in text


def test_format_text_flags_required_failures_prominently() -> None:
    report = {
        "ok": False,
        "summary": {"checks": 2, "required_failures": 1, "warnings": 0},
        "checks": [
            {"name": "database", "status": "fail", "detail": "corrupt", "required": True},
            {"name": "mqtt", "status": "ok", "detail": "127.0.0.1:1883", "required": False},
        ],
    }

    text = format_text(report)

    assert text.startswith("AirMonitor doctor: PROBLEMS FOUND ")
    assert "[FAIL] database" in text
    assert "[ok  ] mqtt" in text
