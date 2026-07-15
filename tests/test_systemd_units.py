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


def test_voc_unit_is_managed_only_by_target():
    assert "[Install]" not in unit("airmonitor-voc.service")


def test_status_service_can_persist_filter_controls():
    status = unit("airmonitor-status.service")
    assert "ReadWritePaths=/var/lib/airmonitor" in status
    assert "ReadOnlyPaths=/var/lib/airmonitor" not in status
