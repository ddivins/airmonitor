from __future__ import annotations

from pathlib import Path

from airmonitor.health import run_checks


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
