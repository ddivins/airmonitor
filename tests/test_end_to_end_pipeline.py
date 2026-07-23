"""End-to-end pipeline test: MQTT printer state -> policy -> filter decisions ->
database writes -> Grafana query generation.

Matches the codebase's existing testing style (direct function/module
composition against a temporary SQLite database, no real MQTT broker or
network) rather than spinning up live services, but exercises the full chain
in one test instead of each stage in isolation.
"""

from __future__ import annotations

import dataclasses
import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("PRINTER_HOST", "192.0.2.10")
os.environ.setdefault("PRINTER_SERIAL", "00000000000000")
os.environ.setdefault("PRINTER_ACCESS_CODE", "00000000")

from airmonitor.cli import enrich_printer_state_with_policy
from airmonitor.database import connect, init_db, insert_sgx_voc_sample
from airmonitor.database.repositories import FilterControlRepository
from airmonitor.filament_policy import FilamentPolicy
from airmonitor.filters.control import resolve_filter_state
from airmonitor.print_tracker import PrintTracker
from airmonitor.printers.bambu.mqtt_service import normalize_state
from airmonitor.sps30_service import ensure_schema as ensure_sps30_schema

REPO_ROOT = Path(__file__).parents[1]
POLICY_PATH = REPO_ROOT / "config" / "filament-policy.yaml"

BAMBU_ABS_PRINT_PAYLOAD = json.dumps(
    {
        "print": {
            "gcode_state": "RUNNING",
            "mc_percent": 42,
            "layer_num": 100,
            "total_layer_num": 240,
            "subtask_name": "e2e_test_part",
            "chamber_temper": 45.0,
            "nozzle_temper": 250.0,
            "bed_temper": 90.0,
            "ams": {
                "tray_now": "0",
                "ams": [{"id": "0", "tray": [{"id": "0", "tray_type": "ABS", "tray_color": "000000FF"}]}],
            },
        }
    }
).encode("utf-8")


def load_dashboard_generator():
    path = REPO_ROOT / "tools" / "generate-grafana-dashboard.py"
    spec = importlib.util.spec_from_file_location("generate_grafana_dashboard_e2e", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _resolve_and_persist(repo: FilterControlRepository, filter_id: str, automation_request: str, reason: str) -> str:
    manual_mode = repo.get(filter_id).manual_mode
    decision = resolve_filter_state(
        filter_id=filter_id,
        manual_mode=manual_mode,
        automation_request=automation_request,
        automation_reason=reason,
    )
    repo.update(
        filter_id,
        automation_request=automation_request,
        actual_state=decision.effective_state.value,
        effective_state=decision.effective_state.value,
        reason=decision.reason,
    )
    return decision.effective_state.value


def test_bambu_mqtt_state_flows_through_policy_filters_database_and_grafana(tmp_path: Path) -> None:
    # 1. MQTT: normalize a raw Bambu status-report payload into a PrinterState,
    #    the same function the printer-mqtt normalizer service calls per message.
    state = normalize_state(BAMBU_ABS_PRINT_PAYLOAD)
    assert state is not None
    assert state.active is True
    assert state.gcode_state == "RUNNING"
    assert state.filament_type == "ABS"

    # 2. Policy: enrich with the real, shipped filament policy (not a stub).
    policy = FilamentPolicy.load(POLICY_PATH)
    printer_state = enrich_printer_state_with_policy(dataclasses.asdict(state), policy)
    assert printer_state["filament_emission_class"] == "high"
    assert printer_state["bento_recommended"] is True
    assert printer_state["room_filter_recommended"] is True

    # 3. Database: record the print and both sensor types against it.
    conn = connect(str(tmp_path / "airmonitor.sqlite3"))
    init_db(conn)
    ensure_sps30_schema(conn)
    conn.execute("INSERT INTO sensors (sensor_id, transport) VALUES ('sgx-1', 'usb-uart')")
    conn.execute("INSERT INTO sensors (sensor_id, transport) VALUES ('sps30-1', 'usb-uart')")

    print_id = PrintTracker(conn).update(printer_state=printer_state, printer_available="online")
    assert print_id is not None

    insert_sgx_voc_sample(
        conn,
        sensor_id="sgx-1",
        session_id=None,
        print_id=print_id,
        sensor_protocol="2023",
        sensor_port="/dev/airmonitor-sgx",
        measurement=SimpleNamespace(gas_ppm=6.5, gas_mass=None, full_scale=1000, temperature_c=24.0, humidity_rh=40.0),
        printer_state=printer_state,
        frame_hex="ff",
    )
    conn.execute("INSERT INTO sps30_samples (sensor_id, mass_pm2_5) VALUES ('sps30-1', 12.3)")
    conn.commit()

    assert tuple(conn.execute(
        "SELECT filament_emission_class, room_filter_recommended FROM prints WHERE id = ?", (print_id,)
    ).fetchone()) == ("high", 1)

    # 4. Filter decisions: Bento runs for any active print; Levoit only because
    #    this filament's policy recommends the room filter (the policy-driven
    #    behavior that's easy to regress silently).
    repo = FilterControlRepository(conn)
    bento_request = "on" if printer_state["active"] else "off"
    bento_effective = _resolve_and_persist(
        repo, "bento", bento_request, f"printer active: state={printer_state['gcode_state']}"
    )
    levoit_request = "on" if printer_state["active"] and printer_state["room_filter_recommended"] else "off"
    levoit_effective = _resolve_and_persist(repo, "levoit", levoit_request, "active print requires room filter")

    assert bento_effective == "on"
    assert levoit_effective == "on"

    # 5. Grafana: the generator's real SQL queries should surface exactly what
    #    was just written, not merely execute without error.
    generator = load_dashboard_generator()

    filters_sql = generator.validation_sql(generator.SQL["filters"]).rstrip(";")
    filter_rows = {
        row["filter_id"]: dict(row) for row in conn.execute(f"SELECT * FROM ({filters_sql})").fetchall()
    }
    assert filter_rows["bento"]["effective_state"] == "on"
    assert filter_rows["levoit"]["effective_state"] == "on"

    conn.close()


def test_pla_print_does_not_recommend_the_room_filter(tmp_path: Path) -> None:
    """Contrast case: a low-emission filament should not trigger Levoit."""

    payload = json.dumps(
        {
            "print": {
                "gcode_state": "RUNNING",
                "ams": {
                    "tray_now": "0",
                    "ams": [{"id": "0", "tray": [{"id": "0", "tray_type": "PLA", "tray_color": "FFFFFFFF"}]}],
                },
            }
        }
    ).encode("utf-8")

    state = normalize_state(payload)
    assert state is not None
    assert state.filament_type == "PLA"

    policy = FilamentPolicy.load(POLICY_PATH)
    printer_state = enrich_printer_state_with_policy(dataclasses.asdict(state), policy)

    assert printer_state["filament_emission_class"] == "low"
    assert printer_state["room_filter_recommended"] is False

    conn = connect(str(tmp_path / "airmonitor.sqlite3"))
    init_db(conn)
    repo = FilterControlRepository(conn)
    levoit_request = "on" if printer_state["active"] and printer_state["room_filter_recommended"] else "off"
    levoit_effective = _resolve_and_persist(repo, "levoit", levoit_request, "active print does not require room filter")

    assert levoit_effective == "off"
    conn.close()
