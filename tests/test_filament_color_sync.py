from __future__ import annotations

import json
from pathlib import Path

from airmonitor.database import connect, init_db
from airmonitor.filament_color_sync import (
    build_color_mappings,
    distinct_filament_colors,
    normalize_filament_color,
    sync_color_mappings_in_dashboard,
)


def test_normalize_filament_color_matches_panel_sql() -> None:
    assert normalize_filament_color("76d9f4ff") == "#76D9F4"
    assert normalize_filament_color("  0086d6  ") == "#0086D6"
    assert normalize_filament_color("abc") is None
    assert normalize_filament_color(None) is None


def test_distinct_filament_colors_dedupes_and_sorts(tmp_path: Path) -> None:
    conn = connect(tmp_path / "test.sqlite3")
    init_db(conn)
    for color in ("76d9f4ff", "0086D6FF", "76D9F4FF", None, "abc"):
        conn.execute(
            "INSERT INTO prints (started_gcode_state, filament_color) VALUES ('RUNNING', ?)",
            (color,),
        )
    conn.commit()

    assert distinct_filament_colors(conn) == ["#0086D6", "#76D9F4"]


def test_build_color_mappings_keys_by_own_hex() -> None:
    mappings = build_color_mappings(["#76D9F4", "#000000"])
    assert mappings == [
        {
            "type": "value",
            "options": {
                "#000000": {"index": 0, "text": "#000000", "color": "#000000"},
                "#76D9F4": {"index": 1, "text": "#76D9F4", "color": "#76D9F4"},
            },
        }
    ]


def _dashboard_fixture() -> dict:
    return {
        "panels": [
            {
                "title": "Selected Prints",
                "fieldConfig": {
                    "overrides": [
                        {
                            "matcher": {"id": "byName", "options": "color"},
                            "properties": [
                                {
                                    "id": "mappings",
                                    "value": [
                                        {
                                            "type": "value",
                                            "options": {
                                                "#000000": {
                                                    "index": 0,
                                                    "text": "#000000",
                                                    "color": "#000000",
                                                }
                                            },
                                        }
                                    ],
                                }
                            ],
                        }
                    ]
                },
            }
        ]
    }


def test_sync_updates_mappings_in_place_when_changed(tmp_path: Path) -> None:
    dashboard_path = tmp_path / "dashboard.json"
    dashboard_path.write_text(json.dumps(_dashboard_fixture()), encoding="utf-8")

    changed = sync_color_mappings_in_dashboard(dashboard_path, ["#000000", "#76D9F4"])

    assert changed is True
    data = json.loads(dashboard_path.read_text(encoding="utf-8"))
    mappings = data["panels"][0]["fieldConfig"]["overrides"][0]["properties"][0]["value"]
    assert mappings == build_color_mappings(["#000000", "#76D9F4"])


def test_sync_is_a_no_op_when_mappings_already_match(tmp_path: Path) -> None:
    dashboard_path = tmp_path / "dashboard.json"
    dashboard_path.write_text(json.dumps(_dashboard_fixture()), encoding="utf-8")

    changed = sync_color_mappings_in_dashboard(dashboard_path, ["#000000"])

    assert changed is False
