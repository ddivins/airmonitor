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
        "airmonitor-alerts.service",
    ):
        assert name in target


def test_application_members_follow_target_lifecycle_but_status_survives():
    for name in (
        "airmonitor-voc.service",
        "airmonitor-sps30.service",
        "airmonitor-printer-mqtt.service",
        "airmonitor-bento.service",
        "airmonitor-levoit.service",
        "airmonitor-alerts.service",
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


def test_status_service_can_still_read_root_secrets_for_backup_bundle():
    """Regression test: ProtectHome=true bind-mounts /root empty and
    inaccessible inside this service's mount namespace. sudo doesn't create
    a new mount namespace for the child it execs, so the backup-bundle
    helper -- invoked via subprocess.run(["sudo", ...]) from this service,
    escalating to root -- still inherited that same restricted view and
    silently saw no /root/.secrets/cloudflare.ini (confirmed live via
    /proc/<pid>/root/root showing empty). ProtectHome=read-only grants read
    access to /root without reopening write access, which this service
    never needed anyway."""

    status = unit("airmonitor-status.service")
    assert "ProtectHome=read-only" in status
    assert "ProtectHome=true" not in status


def test_target_managed_units_are_static():
    for name in (
        "airmonitor-voc.service",
        "airmonitor-sps30.service",
        "airmonitor-printer-mqtt.service",
        "airmonitor-bento.service",
        "airmonitor-levoit.service",
        "airmonitor-status.service",
        "airmonitor-export.service",
        "airmonitor-alerts.service",
    ):
        assert "[Install]" not in unit(name)


def test_backup_timer_runs_daily_and_is_independent_of_target():
    service = unit("airmonitor-backup.service")
    timer = unit("airmonitor-backup.timer")
    assert "Type=oneshot" in service
    assert "PartOf=airmonitor.target" not in service
    assert "ExecStart=/opt/airmonitor/venv/bin/airmonitor backup" in service
    assert "OnCalendar=daily" in timer
    assert "[Install]" in timer


def test_filament_colors_sync_timer_runs_every_6_hours_and_is_independent_of_target():
    service = unit("airmonitor-filament-colors-sync.service")
    timer = unit("airmonitor-filament-colors-sync.timer")
    assert "Type=oneshot" in service
    assert "PartOf=airmonitor.target" not in service
    assert "ExecStart=/opt/airmonitor/venv/bin/airmonitor sync-filament-colors" in service
    assert "OnCalendar=*-*-* 0/6:00:00" in timer
    assert "[Install]" in timer


def test_rollback_tolerates_services_absent_from_older_commit():
    rollback = (UNIT_DIR.parent / "tools" / "rollback.sh").read_text(encoding="utf-8")
    assert 'if [[ -f "$WORKTREE/systemd/$service" ]]' in rollback
    assert 'sudo rm -f "/etc/systemd/system/$service"' in rollback
