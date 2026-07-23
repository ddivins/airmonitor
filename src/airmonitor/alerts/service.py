"""Periodic evaluator that raises/resolves alerts for dangerous readings,
stale sensors, and unresponsive filters.

Runs as its own systemd service (airmonitor-alerts) so a bug in alert
evaluation or notification delivery can't disrupt sensor logging or filter
automation, matching the appliance's existing service-isolation design.
"""

from __future__ import annotations

import argparse
import logging
import os
import sqlite3
import time
from typing import Iterable

from airmonitor.alerts.evaluator import (
    AlertCandidate,
    diff_alerts,
    evaluate_filter_mismatch,
    evaluate_metric,
    evaluate_sensor_freshness,
)
from airmonitor.alerts.notifier import AlertMessage, NotifierConfig, send
from airmonitor.alerts.thresholds import MetricThreshold, load_thresholds
from airmonitor.database import (
    connect,
    init_db,
    list_acknowledged_alert_events,
    list_open_alert_events,
    open_alert_event,
    resolve_alert_event,
)

LOG = logging.getLogger("airmonitor.alerts")

DEFAULT_DATABASE = "/var/lib/airmonitor/airmonitor.sqlite3"
DEFAULT_POLL_SECONDS = 30.0


def _fetchone(conn: sqlite3.Connection, query: str) -> sqlite3.Row | None:
    try:
        return conn.execute(query).fetchone()
    except sqlite3.Error:
        return None


def collect_candidates(
    conn: sqlite3.Connection,
    thresholds: dict[str, MetricThreshold],
    *,
    open_alerts: dict[str, sqlite3.Row] | None = None,
) -> dict[str, AlertCandidate]:
    candidates: dict[str, AlertCandidate] = {}
    open_alerts = open_alerts or {}

    sgx = _fetchone(conn, "SELECT sampled_at, gas_ppm FROM sgx_voc_samples ORDER BY id DESC LIMIT 1")
    metric = evaluate_metric(
        "sgx_gas_ppm", sgx["gas_ppm"] if sgx else None, thresholds["sgx_gas_ppm"], label="VOC (SGX)"
    )
    if metric:
        candidates[metric.key] = metric
    freshness = evaluate_sensor_freshness("sgx_stale", "SGX VOC sensor", sgx["sampled_at"] if sgx else None)
    if freshness:
        candidates[freshness.key] = freshness

    sps30 = _fetchone(conn, "SELECT sampled_at, mass_pm2_5 FROM sps30_samples ORDER BY id DESC LIMIT 1")
    metric = evaluate_metric(
        "sps30_mass_pm2_5", sps30["mass_pm2_5"] if sps30 else None, thresholds["sps30_mass_pm2_5"], label="PM2.5 (SPS30)"
    )
    if metric:
        candidates[metric.key] = metric
    freshness = evaluate_sensor_freshness("sps30_stale", "SPS30 particulate sensor", sps30["sampled_at"] if sps30 else None)
    if freshness:
        candidates[freshness.key] = freshness

    for row in conn.execute("SELECT filter_id, actual_state, effective_state, reason FROM filter_control_state"):
        key = f"filter_{row['filter_id']}_mismatch"
        open_row = open_alerts.get(key)
        mismatch = evaluate_filter_mismatch(
            key,
            f"{row['filter_id']} filter",
            row["actual_state"],
            row["effective_state"],
            row["reason"],
            open_since=open_row["fired_at"] if open_row else None,
        )
        if mismatch:
            candidates[mismatch.key] = mismatch

    return candidates


def run_once(
    *,
    database: str,
    thresholds: dict[str, MetricThreshold],
    notifier_config: NotifierConfig,
) -> None:
    conn = connect(database)
    init_db(conn)
    try:
        open_rows = list_open_alert_events(conn)
        acknowledged = list_acknowledged_alert_events(conn)
        candidates = collect_candidates(conn, thresholds, open_alerts=open_rows)
        open_levels = {key: row["level"] for key, row in open_rows.items()}
        to_open, to_resolve = diff_alerts(candidates, open_levels)

        for candidate in to_open:
            open_alert_event(
                conn,
                alert_key=candidate.key,
                level=candidate.level,
                message=candidate.body,
                value=candidate.value,
                threshold=candidate.threshold,
            )
            LOG.warning("alert opened: %s (%s) - %s", candidate.key, candidate.level, candidate.body)
            if candidate.key in acknowledged:
                LOG.info("alert %s is acknowledged; suppressing notification", candidate.key)
                continue
            send(notifier_config, AlertMessage(candidate.key, candidate.level, candidate.title, candidate.body, candidate.value, candidate.threshold))

        for key in to_resolve:
            resolve_alert_event(conn, alert_key=key)
            LOG.info("alert resolved: %s", key)
            if key in acknowledged:
                continue
            send(notifier_config, AlertMessage(key, "resolved", f"{key} resolved", "Condition returned to normal"))
    finally:
        conn.close()


def _env_float(name: str, default: float) -> float:
    value = os.environ.get(name)
    return float(value) if value else default


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="airmonitor-alerts",
        description="Evaluate air-quality/sensor/filter alert thresholds and notify",
    )
    parser.add_argument("--database", default=os.environ.get("ALERT_DATABASE", DEFAULT_DATABASE))
    parser.add_argument("--thresholds", default=os.environ.get("ALERT_THRESHOLDS_PATH"))
    parser.add_argument("--poll-seconds", type=float, default=_env_float("ALERT_POLL_SECONDS", DEFAULT_POLL_SECONDS))
    parser.add_argument("--once", action="store_true", help="Evaluate a single time and exit")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    thresholds = load_thresholds(args.thresholds)
    notifier_config = NotifierConfig(
        webhook_url=os.environ.get("ALERT_WEBHOOK_URL") or None,
        ntfy_server=os.environ.get("ALERT_NTFY_SERVER", "https://ntfy.sh"),
        ntfy_topic=os.environ.get("ALERT_NTFY_TOPIC") or None,
    )
    if args.once:
        run_once(database=args.database, thresholds=thresholds, notifier_config=notifier_config)
        return 0
    while True:
        try:
            run_once(database=args.database, thresholds=thresholds, notifier_config=notifier_config)
        except Exception:
            LOG.exception("alert evaluation failed")
        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
