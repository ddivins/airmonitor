# AirMonitor Roadmap

This roadmap is ordered by dependency and operational value. Items near the top should be completed before lower items unless a hardware arrival changes priority.

## Phase 1 — Stabilize the appliance foundation

- [x] Preserve separate systemd services inside one package.
- [x] Add generated Grafana provisioning.
- [x] Add SQLite schema management and repositories.
- [x] Add appliance health checks and CI.
- [x] Add USB identity discovery, manual serial registration, and hot-plug recovery.
- [x] Add one-command hardware enrollment.
- [x] Add an appliance inventory command that reports package version, registered hardware, resolved serial paths, service state, MQTT/Grafana reachability, and database status.
- [x] Make `tools/update.sh` run the full doctor and fail clearly if required checks fail.
- [x] Add rollback guidance and retain the previous installed commit/version during updates.

## Phase 2 — Complete the sensor platform

- [x] Implement the Sensirion SPS30 driver under `airmonitor.sensors.sensirion.sps30`.
- [x] Support SPS30 USB-UART discovery and manual UART registration through the hardware registry.
- [x] Add particulate sample tables and repository methods for PM1.0, PM2.5, PM4, PM10, particle counts, and typical particle size.
- [x] Add an SPS30 service entry point with hot-plug behavior equivalent to the SGX service.
- [x] Add SPS30 panels and combined environmental dashboards in Grafana.
- [x] Add sensor freshness and last-good-reading checks to `airmonitor-doctor` (`check_sensor_freshness`, `--sensor-freshness`; this landed earlier alongside the SPS30 dashboard work but the checklist above was never updated to reflect it).
- [x] Add simulator/fake serial fixtures so sensor behavior is testable without physical hardware (`tests/fake_serial.py`'s `FakeSGXSerial`/`FakeSPS30Serial`). Both sensor drivers (`cli.read_sgx_once`, `sensirion.sps30.SPS30`) already only require a duck-typed serial object, so the fixtures exercise the real protocol-driving code -- framing, checksum validation, protocol fallback, measurement decoding -- rather than just the frame encode/decode helpers that were tested before.

## Phase 3 — Safety alerting and notifications

Promoted ahead of multi-sensor and UX work: the project's core promise ("Monitor. Understand. Don't Die.") depends on someone being told when air quality is bad, not just able to look it up.

- [x] Add VOC/PM safety warnings (`airmonitor.alerts`, `airmonitor-alerts.service`).
- [x] Add a notification channel (generic JSON webhook and/or ntfy push) for dangerous air-quality conditions and stale/offline sensors.
- [x] Add configurable thresholds per sensor/metric (`config/alert-thresholds.yaml.example`, `ALERT_THRESHOLDS_PATH`).
- [x] Add a notification-history/audit record (`alert_events` table) so alerts are auditable, not just fire-and-forget.
- [x] Add a web UI view of alert state (`/alerts` page, `docs/status-page.md`). Found while auditing the UI: alerts were being recorded but had zero visibility anywhere in the status page or Grafana — only the CLI/raw SQL could see them.
- [x] Add backup-health visibility (last backup time/size, retention count) to the landing page — otherwise a silently-broken `airmonitor-backup.timer` was only visible via `airmonitor-doctor`.
- [x] Add an "update available" indicator to the landing page, comparing the installed commit against upstream via anonymous `git ls-remote` (no credentials or local-write needed) rather than requiring a manual check of `origin/main`.
- [x] Extend filter-mismatch alerting now that Phase 4's persisted control wiring has landed: a mismatch escalates from warning to critical if it's still open 10 minutes later (`FILTER_MISMATCH_ESCALATION_SECONDS`), the same warning-then-critical shape sensor-freshness alerts already use, instead of a single flat "warning" regardless of how long a filter's been stuck.
- [x] Add an "explicit user override" acknowledgment/silence mechanism (`airmonitor alerts ack|unack|list`, `alert_acknowledgements` table) so a knowingly-accepted condition doesn't keep re-notifying. Persisted in the database (survives a service restart, unlike an in-memory flag) and auto-cleared once the condition actually resolves, so it can't silence a future, unrelated recurrence. The alert stays fully visible on `/alerts` with an "Acknowledged" badge -- only the webhook/ntfy notification is suppressed.
- [x] Add cross-print comparison (`airmonitor-compare-prints` Grafana dashboard, `docs/status-page.md`). Found during the same UI audit as the items above: `docs/architecture.md` frames the whole project around comparative experiments (filtered vs. unfiltered, one filter medium vs. another), but nothing in the UI actually let you view two prints side by side -- only one print at a time via `airmonitor-print-window`.

## Phase 4 — Filter control and observability

This phase turned out to be largely complete already; the checklist below
just hadn't been updated to reflect it.

- [x] Wire persisted `auto`, `on`, and `off` control modes into the Bento and Levoit services (`resolve_and_record_filter` / `resolve_desired_filter_state`).
- [x] Add CLI commands for filter status and override control (`airmonitor filter status | {bento,levoit,all} {status,auto,on,off}`).
- [x] Record automation request, manual mode, effective state, actual state, reason, and command timestamp (`filter_control_state` table, `updated_at`).
- [x] Detect and honor external/manual device changes without immediately fighting the user (`external_override_mode` / `record_external_manual_override` in both services).
- [x] Add stale printer-state handling directly into filter controllers: Bento now suspends any pending OFF timer and holds the last commanded outlet state once the local MQTT feed has been silent past `MQTT_WATCHDOG_SECONDS`; Levoit holds the last automation request once its feed has been silent past `PRINTER_STATE_STALE_SECONDS`, instead of either silently reading staleness as "printer idle."
- [x] Add filter state/reason panels to Grafana (`tools/generate-grafana-dashboard.py`'s "Filter Control" table: manual_mode, automation_request, actual_state, effective_state, reason, updated_at).

## Phase 5 — Release hygiene

New phase covering reproducibility gaps that matter more now that the fresh-host installer is meant for others to use.

- [x] Pin dependency versions with a lockfile: `uv.lock` (authoritative) plus a derived `requirements-lock.txt` consumed as a pip constraints file by `tools/update.sh` and CI, so an appliance install and a CI run resolve the same versions instead of whatever the `pyproject.toml` ranges pick up that day. See "Dependency pinning" in the README for the regeneration command.
- [x] Add a committed ruff configuration and enforce it in CI. Deliberately scoped to ruff's default rule set (pyflakes + basic pycodestyle), which the codebase already passes cleanly — broader rules (line length, import sorting, pyupgrade) would require a separate style-focused pass across many unrelated files, so they're left for a dedicated PR rather than bundled in here.
- [x] Add a `CHANGELOG.md` and start recording notable changes per release (see Phase 8).

## Phase 6 — Multiple sensors and service instances

- [ ] Replace the single sensor service assumption with a registry-driven multi-sensor supervisor.
- [ ] Support multiple SGX and SPS30 units simultaneously.
- [ ] Add templated or generated systemd units per hardware id.
- [ ] Store sensor location and role, such as room, enclosure, exhaust, or chamber.
- [ ] Make dashboards filterable by sensor id and location.
- [ ] Add duplicate USB identity and conflicting device-path detection.

## Phase 7 — Appliance management UX

- [x] Add `airmonitor inventory` and `airmonitor hardware ...` aliases to the main CLI, forwarding to the existing `airmonitor-inventory`/`airmonitor-hardware` entry points via `parse_known_args` passthrough (the same leading-flag-safe mechanism as `install`, not a REMAINDER positional).
- [x] Add `airmonitor update` as the supported wrapper around the update lifecycle. Deliberately **not** run via `sudo`: it locates the checkout via a new `REPO_DIR` key in `/etc/airmonitor/install.conf` (written automatically by `tools/install.sh`), then runs `git pull --ff-only` followed by `tools/update.sh` as the invoking user — running the whole thing as root would break `git pull` for a user whose SSH credentials root doesn't have, a bug hit directly this session. `--dry-run` by default; `--no-dry-run` executes.
- [x] Add `airmonitor install` for rerunning the installer (not the very first bootstrap, which unavoidably still needs `git clone && bash tools/install.sh` before any `airmonitor` binary exists to invoke). Extra flags (`--full`, `--non-interactive`, etc.) pass through to `tools/install.sh`.
- [x] Add an interactive `airmonitor setup` flow for printer, sensors, filters, and MQTT (`sudo airmonitor setup` / `airmonitor-setup`). Grafana is reported (current mode/domain) rather than configured here — enabling it is `tools/install.sh`'s job (`airmonitor install --full`), not a credential-entry concern, so this doesn't duplicate that prompt flow.
- [ ] Add EEPROM provisioning behind a guarded AirMonitor CLI command while retaining factory backup requirements.
- [x] Add structured human-readable doctor output in addition to JSON (`airmonitor-doctor --format text`).
- [ ] Add service log collection for support bundles with secrets redacted.

## Phase 8 — Reliability and releases

- [x] Add end-to-end tests covering MQTT printer state through policy, filter decisions, database writes, and Grafana query generation (`tests/test_end_to_end_pipeline.py`).
- [x] Add database backup/restore commands and documented retention policy (`airmonitor backup`/`airmonitor restore`, daily `airmonitor-backup.timer`, 14-backup default retention). See `docs/backup-restore.md`.
- [x] Add installed Git commit reporting (`installed-commit`/`previous-commit`/`target-commit` under `/var/lib/airmonitor/update-state/`, already tracked by `tools/update.sh`/`tools/rollback.sh`).
- [x] Add release tags and a changelog (`CHANGELOG.md`, first entry `v0.6.0`). Tags/changelog are written by hand per release, not auto-generated from commits.
- [x] Add automatic rollback when update, service startup, or doctor fails: `tools/update.sh` now runs `tools/rollback.sh` automatically if any service fails to (re)start or `airmonitor-doctor` reports a required failure, rather than only suggesting a manual rollback. Opt out with `AUTO_ROLLBACK=0` (see `docs/update-rollback.md`). Fresh `tools/install.sh` runs are not covered yet — a failure there still requires manual cleanup.
- [x] Add documented recovery from a damaged SQLite database or missing configuration (`docs/recovery-runbook.md`; the corruption-recovery steps were verified against a deliberately corrupted test database while writing it, not just written from theory).
- [x] Define and test the v1.0 supported hardware and upgrade path (`docs/hardware-bom.md`, "v1.0 upgrade path promise" in `docs/update-rollback.md`, `tests/test_schema_upgrade_path.py`). The package version has not been bumped to `1.0.0` yet — that's a separate, deliberate release decision, not implied by writing the definition down.

## Phase 9 — Optional future expansion

- [ ] Additional particulate, CO2, temperature, humidity, and gas sensors through the plugin interfaces.
- [ ] Additional printer families through normalized MQTT or API adapters.
- [ ] Home Assistant and generic MQTT discovery integration.
- [ ] Remote appliance status without exposing secrets or control endpoints by default.

## Current next actions

Phase 8 is fully complete. Phase 7 has two items left, both deliberately
skipped in the pass that did the rest of it: EEPROM provisioning (low value —
the project's own docs already call that path not part of the recommended
build) and a secrets-redacted support-bundle command.

1. Decide when to actually cut the `1.0.0` release (the definition is written; the version bump is a separate decision).
2. Add a support-bundle CLI command (doctor output + recent service logs, secrets redacted) if needed, or the EEPROM CLI command if it comes up.
3. Begin Phase 6 (multiple sensors and service instances) — bigger, and only worth it once a second sensor unit exists.

## Operations note (2026-07-23)

An early production appliance predated the config-driven install flow. Its
`/etc/airmonitor/install.conf` has since been backfilled (`MODE=full`,
`DOMAIN=airmonitor.example.com`, `CERT_EMAIL`,
`CERTBOT_CLOUDFLARE_CREDENTIALS`, `LEGACY_GRAFANA_REDIRECT=true`), and plain
`bash tools/update.sh` (no env-var overrides) now runs cleanly end to end.
