"""PrintTracker session-splitting behavior around ambiguous printer states."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from airmonitor.database import connect, init_db
from airmonitor.print_tracker import PrintTracker


def _tracker(tmp_path: Path) -> tuple[PrintTracker, sqlite3.Connection]:
    conn = connect(tmp_path / "test.sqlite3")
    init_db(conn)
    return PrintTracker(conn), conn


def _running_state(**overrides) -> dict:
    state = {
        "active": True,
        "connected": True,
        "gcode_state": "RUNNING",
        "subtask_name": "EXP1-baseline",
    }
    state.update(overrides)
    return state


def test_transient_null_state_while_connected_does_not_split_print(tmp_path: Path) -> None:
    tracker, conn = _tracker(tmp_path)

    first_id = tracker.update(printer_state=_running_state(), printer_available="online")
    assert first_id is not None

    # Bed-leveling/calibration blip: printer still connected, gcode_state
    # momentarily unknown. This used to be misread as "print ended".
    blip_id = tracker.update(
        printer_state={"active": False, "connected": True, "gcode_state": None},
        printer_available="online",
    )
    assert blip_id == first_id

    resumed_id = tracker.update(printer_state=_running_state(), printer_available="online")
    assert resumed_id == first_id

    rows = conn.execute("SELECT COUNT(*) FROM prints").fetchone()[0]
    assert rows == 1


def test_terminal_state_closes_the_print(tmp_path: Path) -> None:
    tracker, conn = _tracker(tmp_path)

    first_id = tracker.update(printer_state=_running_state(), printer_available="online")

    closed_id = tracker.update(
        printer_state={"active": False, "connected": True, "gcode_state": "FINISH"},
        printer_available="online",
    )
    assert closed_id == first_id

    ended_state = conn.execute(
        "SELECT ended_gcode_state FROM prints WHERE id = ?", (first_id,)
    ).fetchone()[0]
    assert ended_state == "FINISH"

    next_id = tracker.update(printer_state=_running_state(), printer_available="online")
    assert next_id != first_id

    rows = conn.execute("SELECT COUNT(*) FROM prints").fetchone()[0]
    assert rows == 2


def test_disconnect_while_ambiguous_state_closes_the_print(tmp_path: Path) -> None:
    tracker, conn = _tracker(tmp_path)

    first_id = tracker.update(printer_state=_running_state(), printer_available="online")

    closed_id = tracker.update(
        printer_state={"active": False, "connected": False, "gcode_state": None},
        printer_available="offline",
    )
    assert closed_id == first_id

    rows = conn.execute("SELECT COUNT(*) FROM prints").fetchone()[0]
    assert rows == 1
