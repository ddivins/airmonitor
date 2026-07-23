from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sqlite3

import pytest

from airmonitor.backup import create_backup, list_backups, prune_backups, restore_backup, verify_backup
from airmonitor.cli import main as cli_main
from airmonitor.database import connect, init_db


def _seed_database(db_path: Path, sensor_id: str = "sgx-1") -> None:
    conn = connect(str(db_path))
    init_db(conn)
    conn.execute("INSERT INTO sensors (sensor_id, transport) VALUES (?, 'usb-uart')", (sensor_id,))
    conn.execute(
        "INSERT INTO sgx_voc_samples (sensor_id, sampled_at, gas_ppm) VALUES (?, '2026-01-01T00:00:00Z', 1.23)",
        (sensor_id,),
    )
    conn.commit()
    conn.close()


def test_create_backup_produces_gzipped_consistent_snapshot(tmp_path: Path) -> None:
    db_path = tmp_path / "airmonitor.sqlite3"
    _seed_database(db_path)

    result = create_backup(database=str(db_path), backup_dir=str(tmp_path / "backups"), retention=10)

    assert result.path.exists()
    assert result.path.name.endswith(".sqlite3.gz")
    assert result.size_bytes > 0
    assert result.removed == []


def test_verify_backup_reports_ok_for_a_healthy_backup(tmp_path: Path) -> None:
    db_path = tmp_path / "airmonitor.sqlite3"
    _seed_database(db_path)
    result = create_backup(database=str(db_path), backup_dir=str(tmp_path / "backups"), retention=10)

    assert verify_backup(result.path) == "ok"


def test_verify_backup_detects_corruption(tmp_path: Path) -> None:
    corrupt = tmp_path / "corrupt.sqlite3"
    corrupt.write_bytes(b"not a sqlite database")

    with pytest.raises(sqlite3.DatabaseError):
        verify_backup(corrupt)


def test_restore_backup_round_trips_data(tmp_path: Path) -> None:
    db_path = tmp_path / "airmonitor.sqlite3"
    _seed_database(db_path)
    result = create_backup(database=str(db_path), backup_dir=str(tmp_path / "backups"), retention=10)

    restored_path = tmp_path / "restored.sqlite3"
    pre_restore_copy = restore_backup(result.path, database=str(restored_path))

    assert pre_restore_copy is None  # nothing existed at the destination yet
    conn = sqlite3.connect(str(restored_path))
    row = conn.execute("SELECT gas_ppm FROM sgx_voc_samples").fetchone()
    conn.close()
    assert row == (1.23,)


def test_restore_backup_keeps_pre_restore_copy_of_existing_database(tmp_path: Path) -> None:
    db_path = tmp_path / "airmonitor.sqlite3"
    _seed_database(db_path, sensor_id="sgx-old")
    old_backup = create_backup(database=str(db_path), backup_dir=str(tmp_path / "backups"), retention=10)

    # Simulate the live database moving on after the backup was taken.
    conn = connect(str(db_path))
    conn.execute("INSERT INTO sensors (sensor_id, transport) VALUES ('sgx-new', 'usb-uart')")
    conn.commit()
    conn.close()

    pre_restore_copy = restore_backup(old_backup.path, database=str(db_path))

    assert pre_restore_copy is not None
    assert pre_restore_copy.exists()
    pre_restore_conn = sqlite3.connect(str(pre_restore_copy))
    sensor_ids = {row[0] for row in pre_restore_conn.execute("SELECT sensor_id FROM sensors")}
    pre_restore_conn.close()
    assert "sgx-new" in sensor_ids  # the copy preserves what was about to be overwritten


def test_restore_backup_raises_for_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        restore_backup(tmp_path / "does-not-exist.sqlite3.gz", database=str(tmp_path / "airmonitor.sqlite3"))


def test_prune_backups_keeps_only_the_most_recent(tmp_path: Path) -> None:
    db_path = tmp_path / "airmonitor.sqlite3"
    _seed_database(db_path)
    backup_dir = tmp_path / "backups"

    times = [datetime(2026, 1, day, tzinfo=timezone.utc) for day in (1, 2, 3, 4, 5)]
    for moment in times:
        create_backup(database=str(db_path), backup_dir=str(backup_dir), retention=100, now=moment)

    assert len(list_backups(backup_dir)) == 5
    removed = prune_backups(backup_dir, retention=2)

    assert len(removed) == 3
    remaining = list_backups(backup_dir)
    assert len(remaining) == 2
    # The two most recent (by filename timestamp) survive.
    assert remaining[0].name < remaining[1].name


def test_prune_backups_rejects_negative_retention(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        prune_backups(tmp_path, retention=-1)


# --- CLI wiring ---------------------------------------------------------------

def test_cli_backup_command_creates_a_backup(tmp_path: Path, capsys) -> None:
    db_path = tmp_path / "airmonitor.sqlite3"
    _seed_database(db_path)
    backup_dir = tmp_path / "backups"

    exit_code = cli_main(["backup", "--database", str(db_path), "--backup-dir", str(backup_dir)])

    assert exit_code == 0
    assert len(list_backups(backup_dir)) == 1
    output = capsys.readouterr().out
    assert "size_bytes" in output


def test_cli_restore_command_refuses_without_yes(tmp_path: Path, capsys) -> None:
    backup_file = tmp_path / "airmonitor-20260101T000000Z.sqlite3.gz"
    backup_file.write_bytes(b"placeholder")

    exit_code = cli_main(["restore", str(backup_file), "--database", str(tmp_path / "airmonitor.sqlite3")])

    assert exit_code == 1
    assert "--yes" in capsys.readouterr().err


def test_cli_restore_command_restores_with_yes(tmp_path: Path, capsys) -> None:
    db_path = tmp_path / "airmonitor.sqlite3"
    _seed_database(db_path)
    backup_dir = tmp_path / "backups"
    result = create_backup(database=str(db_path), backup_dir=str(backup_dir), retention=10)

    restored_path = tmp_path / "restored.sqlite3"
    exit_code = cli_main(["restore", str(result.path), "--database", str(restored_path), "--yes"])

    assert exit_code == 0
    conn = sqlite3.connect(str(restored_path))
    row = conn.execute("SELECT gas_ppm FROM sgx_voc_samples").fetchone()
    conn.close()
    assert row == (1.23,)
