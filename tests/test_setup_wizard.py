from __future__ import annotations

from pathlib import Path
from unittest import mock

from airmonitor.setup_wizard import (
    Prompter,
    get_env_value,
    read_env_lines,
    report_grafana_status,
    run_mqtt_section,
    run_section,
    run_setup,
    set_env_values,
    SECTIONS,
)


def _canned_prompter(answers: list[str]) -> Prompter:
    iterator = iter(answers)
    outputs: list[str] = []
    return Prompter(
        ask=lambda _prompt: next(iterator),
        ask_secret=lambda _prompt: next(iterator),
        out=outputs.append,
    ), outputs


# --- pure env line helpers -------------------------------------------------

def test_get_env_value_finds_key() -> None:
    lines = ["# comment", "FOO=bar", "BAZ=qux"]
    assert get_env_value(lines, "FOO") == "bar"
    assert get_env_value(lines, "BAZ") == "qux"
    assert get_env_value(lines, "MISSING") is None


def test_set_env_values_updates_in_place_and_reports_changed() -> None:
    lines = ["# header", "FOO=old", "BAR=same"]
    updated, changed = set_env_values(lines, {"FOO": "new", "BAR": "same"})
    assert updated == ["# header", "FOO=new", "BAR=same"]
    assert changed == {"FOO"}


def test_set_env_values_appends_missing_keys() -> None:
    lines = ["FOO=1"]
    updated, changed = set_env_values(lines, {"FOO": "1", "NEW_KEY": "value"})
    assert updated == ["FOO=1", "NEW_KEY=value"]
    assert changed == {"NEW_KEY"}


def test_read_env_lines_missing_file_returns_empty(tmp_path: Path) -> None:
    assert read_env_lines(tmp_path / "nope.env") == []


# --- run_section -------------------------------------------------------------

def test_run_section_writes_file_with_secure_permissions(tmp_path: Path) -> None:
    prompter, outputs = _canned_prompter(["192.168.1.50", "ABC123", "secretcode"])
    section = SECTIONS[0]  # printer-mqtt.env
    changed = run_section(tmp_path, section, prompter)

    assert changed == {"PRINTER_HOST", "PRINTER_SERIAL", "PRINTER_ACCESS_CODE"}
    env_path = tmp_path / "printer-mqtt.env"
    assert env_path.exists()
    assert oct(env_path.stat().st_mode)[-3:] == "600"
    content = env_path.read_text(encoding="utf-8")
    assert "PRINTER_HOST=192.168.1.50" in content
    assert "PRINTER_ACCESS_CODE=secretcode" in content


def test_run_section_pressing_enter_keeps_existing_value(tmp_path: Path) -> None:
    env_path = tmp_path / "printer-mqtt.env"
    env_path.write_text("PRINTER_HOST=192.168.1.99\nPRINTER_SERIAL=OLD\nPRINTER_ACCESS_CODE=oldcode\n", encoding="utf-8")

    prompter, outputs = _canned_prompter(["", "", ""])  # blank = keep current
    section = SECTIONS[0]
    changed = run_section(tmp_path, section, prompter)

    assert changed == set()
    assert "No changes." in outputs
    assert env_path.read_text(encoding="utf-8") == "PRINTER_HOST=192.168.1.99\nPRINTER_SERIAL=OLD\nPRINTER_ACCESS_CODE=oldcode\n"


# --- MQTT section: per-file key-name mapping --------------------------------

def test_run_mqtt_section_updates_bare_and_prefixed_keys_consistently(tmp_path: Path) -> None:
    (tmp_path / "printer-mqtt.env").write_text("LOCAL_MQTT_HOST=localhost\nLOCAL_MQTT_PORT=1883\n", encoding="utf-8")
    (tmp_path / "bento.env").write_text("LOCAL_MQTT_HOST=localhost\nLOCAL_MQTT_PORT=1883\n", encoding="utf-8")
    (tmp_path / "levoit.env").write_text("LOCAL_MQTT_HOST=localhost\nLOCAL_MQTT_PORT=1883\n", encoding="utf-8")
    (tmp_path / "sgx-voc.env").write_text(
        "AIRMONITOR_LOCAL_MQTT_HOST=localhost\nAIRMONITOR_LOCAL_MQTT_PORT=1883\n", encoding="utf-8"
    )
    (tmp_path / "sps30.env").write_text("AIRMONITOR_SPS30_SENSOR_LOCATION=printer-room\n", encoding="utf-8")

    prompter, outputs = _canned_prompter(["mqtt.internal", "8883"])
    changed_files = run_mqtt_section(tmp_path, prompter)

    assert changed_files == {"printer-mqtt.env", "bento.env", "levoit.env", "sgx-voc.env"}
    assert "LOCAL_MQTT_HOST=mqtt.internal" in (tmp_path / "bento.env").read_text(encoding="utf-8")
    assert "AIRMONITOR_LOCAL_MQTT_HOST=mqtt.internal" in (tmp_path / "sgx-voc.env").read_text(encoding="utf-8")
    # sps30.env has no local MQTT connection and must be left untouched.
    assert (tmp_path / "sps30.env").read_text(encoding="utf-8") == "AIRMONITOR_SPS30_SENSOR_LOCATION=printer-room\n"


def test_run_mqtt_section_defaults_when_no_files_exist_yet(tmp_path: Path) -> None:
    prompter, outputs = _canned_prompter(["", ""])  # keep host/port defaults
    changed_files = run_mqtt_section(tmp_path, prompter)
    assert changed_files == set()  # nothing existed to update


# --- Grafana status reporting -----------------------------------------------

def test_report_grafana_status_suggests_full_install_when_core(tmp_path: Path) -> None:
    (tmp_path / "install.conf").write_text("MODE=core\n", encoding="utf-8")
    outputs: list[str] = []
    report_grafana_status(tmp_path, Prompter(out=outputs.append))
    assert any("airmonitor install --full" in line for line in outputs)


def test_report_grafana_status_silent_when_already_full(tmp_path: Path) -> None:
    (tmp_path / "install.conf").write_text("MODE=full\nDOMAIN=example.com\n", encoding="utf-8")
    outputs: list[str] = []
    report_grafana_status(tmp_path, Prompter(out=outputs.append))
    assert not any("--full" in line for line in outputs)
    assert any("example.com" in line for line in outputs)


def test_report_grafana_status_does_nothing_without_install_conf(tmp_path: Path) -> None:
    outputs: list[str] = []
    report_grafana_status(tmp_path, Prompter(out=outputs.append))
    assert outputs == []


# --- run_setup guards and end-to-end -----------------------------------------

def test_run_setup_refuses_without_a_tty(tmp_path: Path) -> None:
    with mock.patch("airmonitor.setup_wizard.sys.stdin.isatty", return_value=False):
        exit_code = run_setup(config_dir=tmp_path)
    assert exit_code == 1


def test_run_setup_refuses_without_root(tmp_path: Path) -> None:
    with mock.patch("airmonitor.setup_wizard.sys.stdin.isatty", return_value=True), \
         mock.patch("airmonitor.setup_wizard.os.geteuid", return_value=1000):
        exit_code = run_setup(config_dir=tmp_path)
    assert exit_code == 1


def test_run_setup_end_to_end_writes_all_sections(tmp_path: Path) -> None:
    answers = iter([
        "192.168.1.50", "SN123", "code123",       # printer
        "chamber",                                 # sgx location
        "printer-room",                             # sps30 location
        "192.168.1.60", "", "",                     # bento (blank kasa creds)
        "", "", "",                                  # levoit (all blank)
        "", "",                                      # mqtt host/port (keep defaults)
    ])
    prompter = Prompter(ask=lambda _p: next(answers), ask_secret=lambda _p: next(answers), out=lambda _l: None)
    exit_code = run_setup(config_dir=tmp_path, prompter=prompter, require_tty=False, require_root=False)

    assert exit_code == 0
    assert "PRINTER_HOST=192.168.1.50" in (tmp_path / "printer-mqtt.env").read_text(encoding="utf-8")
    assert "OUTLET_HOST=192.168.1.60" in (tmp_path / "bento.env").read_text(encoding="utf-8")
    assert "AIRMONITOR_SENSOR_LOCATION=chamber" in (tmp_path / "sgx-voc.env").read_text(encoding="utf-8")


# --- CLI dispatch -------------------------------------------------------------

def test_cli_setup_dispatches_with_config_dir(tmp_path: Path) -> None:
    from airmonitor.cli import main

    with mock.patch("airmonitor.setup_wizard.run_setup") as run_setup_mock:
        run_setup_mock.return_value = 0
        exit_code = main(["setup", "--config-dir", str(tmp_path)])
    assert exit_code == 0
    run_setup_mock.assert_called_once_with(config_dir=str(tmp_path))
