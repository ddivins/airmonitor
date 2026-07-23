# Alerting

`airmonitor-alerts` (`systemd/airmonitor-alerts.service`) is a small,
independent service that periodically checks:

- The latest SGX VOC (`gas_ppm`) and SPS30 particulate (`mass_pm2_5`) readings
  against configurable warning/critical thresholds.
- Sensor freshness — a sensor that hasn't reported in over 90s is "stale", over
  300s is "offline" (the same thresholds the status page uses).
- Filter control mismatches — a filter's `actual_state` disagreeing with its
  `effective_state` (for example, an automation command that didn't take
  effect).

It writes every alert transition (opened, escalated, resolved) to the
`alert_events` table, and optionally sends a push notification. Alerts are
always recorded even with no notification channel configured, so they remain
visible through the database and (once wired up) the status page and
`airmonitor-doctor`.

## Configuring thresholds

Copy `config/alert-thresholds.yaml.example` to
`/etc/airmonitor/alert-thresholds.yaml` and adjust the `warning`/`critical`
values per metric. AirMonitor is not a certified air-quality instrument (see
the top-level README), so treat these as tunable starting points rather than
calibrated safety limits — the PM2.5 defaults follow EPA AQI breakpoints, but
the VOC defaults have no equivalent public standard and should be tuned
against your own sensor's baseline.

## Configuring notifications

Copy `config/env/alerts.env.example` to `/etc/airmonitor/alerts.env` and set
one or both:

- `ALERT_WEBHOOK_URL` — receives a JSON POST for every alert transition:
  `{"alert_key", "level", "title", "message", "value", "threshold"}`.
- `ALERT_NTFY_TOPIC` (with `ALERT_NTFY_SERVER`, default `https://ntfy.sh`) —
  a push notification via [ntfy](https://ntfy.sh).

Neither is required to start the service.

## Notification behavior

A condition only (re)notifies when it newly opens or escalates (for example
warning to critical); it does not repeat every poll cycle while unchanged.
When a condition clears, a single "resolved" notification is sent and the
open `alert_events` row is closed.

## Running a single check

```bash
/opt/airmonitor/venv/bin/airmonitor-alerts --once
```

Useful for testing thresholds/notifications from a cron job or the command
line without running the long-lived service.
