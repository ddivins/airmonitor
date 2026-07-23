from __future__ import annotations

import json
from pathlib import Path

import pytest

from airmonitor.cli import main
from airmonitor.database import connect, init_db, open_alert_event


@pytest.fixture
def database(tmp_path: Path) -> str:
    db_path = tmp_path / "airmonitor.sqlite3"
    conn = connect(str(db_path))
    init_db(conn)
    open_alert_event(conn, alert_key="sgx_gas_ppm", level="critical", message="VOC at 20", value=20.0, threshold=10.0)
    conn.close()
    return str(db_path)


def test_alerts_list_shows_open_alerts_unacknowledged_by_default(database: str, capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["alerts", "list", "--database", database])
    assert exit_code == 0
    records = json.loads(capsys.readouterr().out)
    assert len(records) == 1
    assert records[0]["alert_key"] == "sgx_gas_ppm"
    assert records[0]["acknowledged"] is False


def test_alerts_ack_then_list_reflects_acknowledgement(database: str, capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["alerts", "ack", "sgx_gas_ppm", "waiting", "on", "part", "--database", database])
    assert exit_code == 0
    capsys.readouterr()

    main(["alerts", "list", "--database", database])
    records = json.loads(capsys.readouterr().out)
    assert records[0]["acknowledged"] is True
    assert records[0]["acknowledgement_note"] == "waiting on part"


def test_alerts_unack_clears_it(database: str, capsys: pytest.CaptureFixture[str]) -> None:
    main(["alerts", "ack", "sgx_gas_ppm", "--database", database])
    capsys.readouterr()

    exit_code = main(["alerts", "unack", "sgx_gas_ppm", "--database", database])
    assert exit_code == 0
    capsys.readouterr()

    main(["alerts", "list", "--database", database])
    records = json.loads(capsys.readouterr().out)
    assert records[0]["acknowledged"] is False


def test_alerts_rejects_unknown_subcommand(database: str) -> None:
    with pytest.raises(SystemExit):
        main(["alerts", "bogus", "--database", database])
