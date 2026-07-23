from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from airmonitor.database import connect, init_db
from airmonitor.health import check_sensor_freshness, run_checks
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
