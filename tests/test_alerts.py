from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from airmonitor.alerts.evaluator import (
    diff_alerts,
    evaluate_filter_mismatch,
    evaluate_metric,
    evaluate_sensor_freshness,
)
from airmonitor.alerts.notifier import AlertMessage, NotifierConfig, send
from airmonitor.alerts.service import run_once
from airmonitor.alerts.thresholds import MetricThreshold, load_thresholds
from airmonitor.database import (
    acknowledge_alert_event,
    clear_alert_acknowledgement,
    connect,
    init_db,
    list_acknowledged_alert_events,
    open_alert_event,
    resolve_alert_event,
)


# --- thresholds -------------------------------------------------------------

def test_load_thresholds_without_path_returns_defaults() -> None:
    thresholds = load_thresholds(None)
    assert thresholds["sgx_gas_ppm"].warning == 3.0
    assert thresholds["sps30_mass_pm2_5"].critical == 150.4


def test_load_thresholds_missing_file_returns_defaults(tmp_path: Path) -> None:
    thresholds = load_thresholds(tmp_path / "does-not-exist.yaml")
    assert thresholds["sgx_gas_ppm"].warning == 3.0


def test_load_thresholds_overrides_from_yaml(tmp_path: Path) -> None:
    config = tmp_path / "thresholds.yaml"
    config.write_text("sgx_gas_ppm:\n  warning: 1.0\n  critical: 2.0\n", encoding="utf-8")
    thresholds = load_thresholds(config)
    assert thresholds["sgx_gas_ppm"] == MetricThreshold(warning=1.0, critical=2.0)
    # Untouched metrics keep their defaults.
    assert thresholds["sps30_mass_pm2_5"].warning == 35.4


# --- evaluator: metric thresholds -------------------------------------------

def test_evaluate_metric_below_warning_is_none() -> None:
    assert evaluate_metric("k", 1.0, MetricThreshold(warning=3.0, critical=10.0), label="VOC") is None


def test_evaluate_metric_none_value_is_none() -> None:
    assert evaluate_metric("k", None, MetricThreshold(warning=3.0, critical=10.0), label="VOC") is None


def test_evaluate_metric_warning_level() -> None:
    result = evaluate_metric("k", 5.0, MetricThreshold(warning=3.0, critical=10.0), label="VOC")
    assert result is not None
    assert result.level == "warning"
    assert result.value == 5.0


def test_evaluate_metric_critical_level() -> None:
    result = evaluate_metric("k", 12.0, MetricThreshold(warning=3.0, critical=10.0), label="VOC")
    assert result is not None
    assert result.level == "critical"


# --- evaluator: sensor freshness --------------------------------------------

def test_evaluate_sensor_freshness_missing_sample_is_critical() -> None:
    result = evaluate_sensor_freshness("k", "SGX", None)
    assert result is not None
    assert result.level == "critical"


def test_evaluate_sensor_freshness_fresh_is_none() -> None:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    sampled_at = "2026-01-01T00:00:10Z"
    assert evaluate_sensor_freshness("k", "SGX", sampled_at, now=now) is None


def test_evaluate_sensor_freshness_stale_is_warning() -> None:
    now = datetime(2026, 1, 1, 0, 2, 0, tzinfo=timezone.utc)
    sampled_at = "2026-01-01T00:00:00Z"
    result = evaluate_sensor_freshness("k", "SGX", sampled_at, now=now)
    assert result is not None
    assert result.level == "warning"


def test_evaluate_sensor_freshness_offline_is_critical() -> None:
    now = datetime(2026, 1, 1, 0, 10, 0, tzinfo=timezone.utc)
    sampled_at = "2026-01-01T00:00:00Z"
    result = evaluate_sensor_freshness("k", "SGX", sampled_at, now=now)
    assert result is not None
    assert result.level == "critical"


# --- evaluator: filter mismatch ----------------------------------------------

def test_evaluate_filter_mismatch_matching_states_is_none() -> None:
    assert evaluate_filter_mismatch("k", "bento", "on", "on", None) is None


def test_evaluate_filter_mismatch_unknown_states_are_ignored() -> None:
    assert evaluate_filter_mismatch("k", "bento", "unknown", "on", None) is None
    assert evaluate_filter_mismatch("k", "bento", "on", "unknown", None) is None


def test_evaluate_filter_mismatch_differing_states_warns() -> None:
    result = evaluate_filter_mismatch("k", "bento", "off", "on", "VeSync unavailable")
    assert result is not None
    assert result.level == "warning"
    assert "VeSync unavailable" in result.body


def test_evaluate_filter_mismatch_stays_warning_before_escalation_threshold() -> None:
    now = datetime(2026, 1, 1, 0, 5, 0, tzinfo=timezone.utc)
    open_since = "2026-01-01T00:00:00Z"  # 300s ago
    result = evaluate_filter_mismatch(
        "k", "bento", "off", "on", None, open_since=open_since, now=now, escalate_after_seconds=600.0
    )
    assert result is not None
    assert result.level == "warning"


def test_evaluate_filter_mismatch_escalates_to_critical_after_threshold() -> None:
    now = datetime(2026, 1, 1, 0, 11, 0, tzinfo=timezone.utc)
    open_since = "2026-01-01T00:00:00Z"  # 660s ago
    result = evaluate_filter_mismatch(
        "k", "bento", "off", "on", None, open_since=open_since, now=now, escalate_after_seconds=600.0
    )
    assert result is not None
    assert result.level == "critical"
    assert "unresolved for over 600s" in result.body


def test_evaluate_filter_mismatch_without_open_since_never_escalates() -> None:
    result = evaluate_filter_mismatch("k", "bento", "off", "on", None, escalate_after_seconds=600.0)
    assert result is not None
    assert result.level == "warning"


# --- evaluator: diff_alerts ---------------------------------------------------

def test_diff_alerts_opens_new_alert() -> None:
    candidate = evaluate_metric("k", 5.0, MetricThreshold(warning=3.0, critical=10.0), label="VOC")
    to_open, to_resolve = diff_alerts({"k": candidate}, {})
    assert to_open == [candidate]
    assert to_resolve == []


def test_diff_alerts_does_not_reopen_unchanged_alert() -> None:
    candidate = evaluate_metric("k", 5.0, MetricThreshold(warning=3.0, critical=10.0), label="VOC")
    to_open, to_resolve = diff_alerts({"k": candidate}, {"k": "warning"})
    assert to_open == []
    assert to_resolve == []


def test_diff_alerts_reopens_on_escalation() -> None:
    candidate = evaluate_metric("k", 12.0, MetricThreshold(warning=3.0, critical=10.0), label="VOC")
    to_open, to_resolve = diff_alerts({"k": candidate}, {"k": "warning"})
    assert to_open == [candidate]


def test_diff_alerts_resolves_cleared_alert() -> None:
    to_open, to_resolve = diff_alerts({}, {"k": "warning"})
    assert to_open == []
    assert to_resolve == ["k"]


# --- notifier ------------------------------------------------------------------

def test_send_does_nothing_without_configured_channels() -> None:
    with mock.patch("airmonitor.alerts.notifier.request.urlopen") as urlopen:
        send(NotifierConfig(), AlertMessage("k", "warning", "title", "body"))
        urlopen.assert_not_called()


def test_send_posts_webhook_json_payload() -> None:
    config = NotifierConfig(webhook_url="https://example.invalid/hook")
    with mock.patch("airmonitor.alerts.notifier.request.urlopen") as urlopen:
        send(config, AlertMessage("sgx_gas_ppm", "critical", "VOC critical", "VOC at 12", 12.0, 10.0))
        assert urlopen.call_count == 1
        request_obj = urlopen.call_args[0][0]
        assert request_obj.full_url == "https://example.invalid/hook"
        assert b'"alert_key": "sgx_gas_ppm"' in request_obj.data


def test_send_posts_ntfy_with_priority_header() -> None:
    config = NotifierConfig(ntfy_topic="airmonitor-alerts")
    with mock.patch("airmonitor.alerts.notifier.request.urlopen") as urlopen:
        send(config, AlertMessage("sgx_gas_ppm", "critical", "VOC critical", "VOC at 12"))
        request_obj = urlopen.call_args[0][0]
        assert request_obj.full_url == "https://ntfy.sh/airmonitor-alerts"
        assert request_obj.get_header("Priority") == "urgent"


def test_send_swallows_delivery_errors() -> None:
    from urllib import error

    config = NotifierConfig(webhook_url="https://example.invalid/hook")
    with mock.patch("airmonitor.alerts.notifier.request.urlopen", side_effect=error.URLError("boom")):
        send(config, AlertMessage("k", "warning", "t", "b"))  # must not raise


# --- service integration (real temp SQLite database) ---------------------------

def _insert_sgx_sample(db_path: Path, gas_ppm: float, sampled_at: str) -> None:
    conn = connect(str(db_path))
    init_db(conn)
    conn.execute("INSERT OR IGNORE INTO sensors (sensor_id, transport) VALUES ('sgx-1', 'usb-uart')")
    conn.execute(
        "INSERT INTO sgx_voc_samples (sensor_id, sampled_at, gas_ppm) VALUES ('sgx-1', ?, ?)",
        (sampled_at, gas_ppm),
    )
    conn.commit()
    conn.close()


def test_run_once_opens_and_resolves_alert(tmp_path: Path) -> None:
    db_path = tmp_path / "airmonitor.sqlite3"
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    _insert_sgx_sample(db_path, 20.0, now)  # above critical threshold

    thresholds = load_thresholds(None)
    with mock.patch("airmonitor.alerts.service.send") as sent:
        run_once(database=str(db_path), thresholds=thresholds, notifier_config=NotifierConfig())
        assert sent.call_count >= 1
        opened_keys = {call.args[1].alert_key for call in sent.call_args_list}
        assert "sgx_gas_ppm" in opened_keys

    conn = connect(str(db_path))
    row = conn.execute(
        "SELECT * FROM alert_events WHERE alert_key = 'sgx_gas_ppm' AND resolved_at IS NULL"
    ).fetchone()
    assert row is not None
    assert row["level"] == "critical"

    # Reading drops back to a safe level: the open alert should resolve.
    _insert_sgx_sample(db_path, 0.1, now)
    with mock.patch("airmonitor.alerts.service.send") as sent:
        run_once(database=str(db_path), thresholds=thresholds, notifier_config=NotifierConfig())
        resolved_keys = {call.args[1].alert_key for call in sent.call_args_list if call.args[1].level == "resolved"}
        assert "sgx_gas_ppm" in resolved_keys

    row = conn.execute(
        "SELECT * FROM alert_events WHERE alert_key = 'sgx_gas_ppm' AND resolved_at IS NULL"
    ).fetchone()
    assert row is None
    conn.close()


def test_run_once_escalates_filter_mismatch_that_persists(tmp_path: Path) -> None:
    db_path = tmp_path / "airmonitor.sqlite3"
    conn = connect(str(db_path))
    init_db(conn)
    conn.execute(
        "INSERT INTO filter_control_state (filter_id, actual_state, effective_state, reason) "
        "VALUES ('bento', 'off', 'on', 'automation')"
    )
    long_ago = (datetime.now(timezone.utc) - timedelta(seconds=700)).isoformat().replace("+00:00", "Z")
    conn.execute(
        "INSERT INTO alert_events (alert_key, level, message, fired_at) "
        "VALUES ('filter_bento_mismatch', 'warning', 'bento filter not responding', ?)",
        (long_ago,),
    )
    conn.commit()
    conn.close()

    thresholds = load_thresholds(None)
    with mock.patch("airmonitor.alerts.service.send") as sent:
        run_once(database=str(db_path), thresholds=thresholds, notifier_config=NotifierConfig())
        calls = [call.args[1] for call in sent.call_args_list if call.args[1].alert_key == "filter_bento_mismatch"]
        assert calls and calls[-1].level == "critical"

    conn = connect(str(db_path))
    row = conn.execute(
        "SELECT * FROM alert_events WHERE alert_key = 'filter_bento_mismatch' AND resolved_at IS NULL"
    ).fetchone()
    assert row is not None
    assert row["level"] == "critical"
    conn.close()


def test_run_once_does_not_renotify_unchanged_alert(tmp_path: Path) -> None:
    db_path = tmp_path / "airmonitor.sqlite3"
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    _insert_sgx_sample(db_path, 20.0, now)
    thresholds = load_thresholds(None)

    with mock.patch("airmonitor.alerts.service.send") as sent:
        run_once(database=str(db_path), thresholds=thresholds, notifier_config=NotifierConfig())
        first_call_count = sent.call_count

    _insert_sgx_sample(db_path, 21.0, now)  # still critical, same level
    with mock.patch("airmonitor.alerts.service.send") as sent:
        run_once(database=str(db_path), thresholds=thresholds, notifier_config=NotifierConfig())
        assert sent.call_count == 0

    assert first_call_count >= 1


# --- acknowledgements ----------------------------------------------------------

def test_acknowledge_alert_event_is_idempotent_and_updates_note(tmp_path: Path) -> None:
    conn = connect(str(tmp_path / "airmonitor.sqlite3"))
    init_db(conn)
    acknowledge_alert_event(conn, alert_key="k", note="known issue")
    acknowledge_alert_event(conn, alert_key="k", note="still known")
    acknowledged = list_acknowledged_alert_events(conn)
    assert acknowledged["k"]["note"] == "still known"
    conn.close()


def test_clear_alert_acknowledgement_removes_it(tmp_path: Path) -> None:
    conn = connect(str(tmp_path / "airmonitor.sqlite3"))
    init_db(conn)
    acknowledge_alert_event(conn, alert_key="k")
    clear_alert_acknowledgement(conn, alert_key="k")
    assert list_acknowledged_alert_events(conn) == {}
    conn.close()


def test_resolve_alert_event_clears_its_acknowledgement(tmp_path: Path) -> None:
    conn = connect(str(tmp_path / "airmonitor.sqlite3"))
    init_db(conn)
    open_alert_event(conn, alert_key="k", level="warning", message="m")
    acknowledge_alert_event(conn, alert_key="k")
    resolve_alert_event(conn, alert_key="k")
    assert list_acknowledged_alert_events(conn) == {}
    conn.close()


def test_run_once_suppresses_notification_for_acknowledged_alert(tmp_path: Path) -> None:
    db_path = tmp_path / "airmonitor.sqlite3"
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    _insert_sgx_sample(db_path, 20.0, now)  # above critical threshold
    thresholds = load_thresholds(None)

    conn = connect(str(db_path))
    init_db(conn)
    acknowledge_alert_event(conn, alert_key="sgx_gas_ppm", note="waiting on part")
    conn.close()

    with mock.patch("airmonitor.alerts.service.send") as sent:
        run_once(database=str(db_path), thresholds=thresholds, notifier_config=NotifierConfig())
        notified_keys = {call.args[1].alert_key for call in sent.call_args_list}
        assert "sgx_gas_ppm" not in notified_keys

    conn = connect(str(db_path))
    row = conn.execute(
        "SELECT * FROM alert_events WHERE alert_key = 'sgx_gas_ppm' AND resolved_at IS NULL"
    ).fetchone()
    assert row is not None  # still recorded, just not notified
    conn.close()


def test_run_once_notifies_again_after_unacknowledged(tmp_path: Path) -> None:
    db_path = tmp_path / "airmonitor.sqlite3"
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    _insert_sgx_sample(db_path, 20.0, now)
    thresholds = load_thresholds(None)

    conn = connect(str(db_path))
    init_db(conn)
    acknowledge_alert_event(conn, alert_key="sgx_gas_ppm")
    conn.close()

    with mock.patch("airmonitor.alerts.service.send"):
        run_once(database=str(db_path), thresholds=thresholds, notifier_config=NotifierConfig())

    conn = connect(str(db_path))
    clear_alert_acknowledgement(conn, alert_key="sgx_gas_ppm")
    conn.close()

    # Condition escalates further (still critical, but the resolved/reopened
    # cycle below proves a fresh occurrence notifies normally once unacked).
    _insert_sgx_sample(db_path, 0.1, now)  # clears the condition
    with mock.patch("airmonitor.alerts.service.send") as sent:
        run_once(database=str(db_path), thresholds=thresholds, notifier_config=NotifierConfig())
        resolved_keys = {call.args[1].alert_key for call in sent.call_args_list if call.args[1].level == "resolved"}
        assert "sgx_gas_ppm" in resolved_keys

    _insert_sgx_sample(db_path, 20.0, now)  # re-trips, unacknowledged this time
    with mock.patch("airmonitor.alerts.service.send") as sent:
        run_once(database=str(db_path), thresholds=thresholds, notifier_config=NotifierConfig())
        opened_keys = {call.args[1].alert_key for call in sent.call_args_list}
        assert "sgx_gas_ppm" in opened_keys
