"""Keep the print-window dashboard's filament color swatch mapping in sync.

Grafana table cells have no built-in way to derive a background color from
the cell's own text value -- "color" value mappings are a literal lookup
table (specific value -> specific color), not a passthrough. Since every
filament color the printer has ever reported is already a real Bambu hex
code, we can at least keep that lookup table populated automatically instead
of hand-editing it whenever a new spool shows up.

This only ever touches the *deployed* dashboard file
(/var/lib/grafana/dashboards/airmonitor/...), not the git-tracked template in
this repo -- the template's own mapping list is just a seed/fallback for a
fresh install before this has run.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable

DEFAULT_DATABASE = "/var/lib/airmonitor/airmonitor.sqlite3"
DEFAULT_DASHBOARD_PATH = "/var/lib/grafana/dashboards/airmonitor/airmonitor-print-window.json"


def normalize_filament_color(raw: str | None) -> str | None:
    """Match the print-window panel's own SQL normalization exactly."""
    if raw is None:
        return None
    trimmed = raw.strip()
    if len(trimmed) < 6:
        return None
    return "#" + trimmed[:6].upper()


def distinct_filament_colors(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT DISTINCT filament_color FROM prints WHERE filament_color IS NOT NULL"
    ).fetchall()
    colors = {normalize_filament_color(row[0]) for row in rows}
    colors.discard(None)
    return sorted(colors)


def build_color_mappings(colors: Iterable[str]) -> list[dict[str, Any]]:
    options: dict[str, Any] = {}
    for index, color in enumerate(sorted(set(colors))):
        options[color] = {"index": index, "text": color, "color": color}
    return [{"type": "value", "options": options}]


def sync_color_mappings_in_dashboard(dashboard_path: Path, colors: Iterable[str]) -> bool:
    """Update the "color" column's value mappings in-place. Returns whether it changed."""
    data = json.loads(dashboard_path.read_text(encoding="utf-8"))
    new_mappings = build_color_mappings(colors)
    changed = False

    for panel in data.get("panels", []):
        for override in panel.get("fieldConfig", {}).get("overrides", []):
            matcher = override.get("matcher", {})
            if matcher.get("id") != "byName" or matcher.get("options") != "color":
                continue
            for prop in override.get("properties", []):
                if prop.get("id") == "mappings" and prop.get("value") != new_mappings:
                    prop["value"] = new_mappings
                    changed = True

    if changed:
        dashboard_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return changed


def sync(
    *,
    database: str = DEFAULT_DATABASE,
    dashboard_path: str | Path = DEFAULT_DASHBOARD_PATH,
) -> dict[str, Any]:
    conn = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    try:
        colors = distinct_filament_colors(conn)
    finally:
        conn.close()

    path = Path(dashboard_path)
    changed = sync_color_mappings_in_dashboard(path, colors)
    return {"dashboard_path": str(path), "colors": colors, "changed": changed}
