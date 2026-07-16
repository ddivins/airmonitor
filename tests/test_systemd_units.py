from pathlib import Path


UNIT_DIR = Path(__file__).parents[1] / "systemd"


def unit(name: str) -> str:
    return (UNIT_DIR / name).read_text(encoding="utf-8")


def test_application_target_wants_all_airmonitor_units():
    target = unit("airmonitor.target")
    for name in (
        "airmonitor-voc.service",
        "airmonitor-sps30.service",
        "airmonitor-printer-mqtt.service",
        "airmonitor-bento.service",
        "airmonitor-levoit.service",
        "airmonitor-status.service",
        "airmonitor-export.service",
    ):
        assert name in target


def test_application_members_follow_target_lifecycle_but_status_survives():
    for name in (
        "airmonitor-voc.service",
        "airmonitor-sps30.service",
        "airmonitor-printer-mqtt.service",
        "airmonitor-bento.service",
        "airmonitor-levoit.service",
    ):
        assert "PartOf=airmonitor.target" in unit(name)
    assert "PartOf=airmonitor.target" not in unit("airmonitor-status.service")
    assert "PartOf=airmonitor.target" not in unit("airmonitor-export.service")


def test_voc_unit_is_managed_only_by_target():
    assert "[Install]" not in unit("airmonitor-voc.service")


def test_status_service_can_persist_filter_controls():
    status = unit("airmonitor-status.service")
    assert "ReadWritePaths=/var/lib/airmonitor" in status
    assert "ReadOnlyPaths=/var/lib/airmonitor" not in status


def test_export_service_is_read_only_and_resource_bounded():
    export = unit("airmonitor-export.service")
    assert "ReadOnlyPaths=/var/lib/airmonitor" in export
    assert "MemoryMax=768M" in export
    assert "ExecStart=/opt/airmonitor/venv/bin/airmonitor-export" in export


def test_target_managed_units_are_static():
    for name in (
        "airmonitor-voc.service",
        "airmonitor-sps30.service",
        "airmonitor-printer-mqtt.service",
        "airmonitor-bento.service",
        "airmonitor-levoit.service",
        "airmonitor-status.service",
        "airmonitor-export.service",
    ):
        assert "[Install]" not in unit(name)


def test_rollback_tolerates_services_absent_from_older_commit():
    rollback = (UNIT_DIR.parent / "tools" / "rollback.sh").read_text(encoding="utf-8")
    assert 'if [[ -f "$WORKTREE/systemd/$service" ]]' in rollback
    assert 'sudo rm -f "/etc/systemd/system/$service"' in rollback
