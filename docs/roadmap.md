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
- [ ] Add sensor freshness and last-good-reading checks to `airmonitor-doctor`.
- [ ] Add simulator/fake serial fixtures so sensor behavior is testable without physical hardware.

## Phase 3 — Safety alerting and notifications

Promoted ahead of multi-sensor and UX work: the project's core promise ("Monitor. Understand. Don't Die.") depends on someone being told when air quality is bad, not just able to look it up.

- [ ] Add VOC/PM safety warnings while preserving explicit user override policy.
- [ ] Add a notification channel (webhook, ntfy, or Pushover) for dangerous air-quality conditions, stale sensors, and failed filters.
- [ ] Add configurable thresholds per sensor/metric, stored alongside hardware config.
- [ ] Add a notification-history/acknowledgment record so alerts are auditable, not just fire-and-forget.

## Phase 4 — Filter control and observability

- [ ] Wire persisted `auto`, `on`, and `off` control modes into the Bento and Levoit services.
- [ ] Add CLI commands for filter status and override control.
- [ ] Record automation request, manual mode, effective state, actual state, reason, and command timestamp.
- [ ] Detect and honor external/manual device changes without immediately fighting the user.
- [ ] Add stale printer-state handling directly into filter controllers.
- [ ] Add filter state/reason panels to Grafana.

## Phase 5 — Release hygiene

New phase covering reproducibility gaps that matter more now that the fresh-host installer is meant for others to use.

- [ ] Pin dependency versions with a lockfile (e.g. `uv.lock` or pip-compile output) instead of open version ranges in `pyproject.toml`.
- [ ] Add a committed ruff configuration and enforce it in CI (currently run ad hoc, not gated).
- [ ] Add a `CHANGELOG.md` and start recording notable changes per release.

## Phase 6 — Multiple sensors and service instances

- [ ] Replace the single sensor service assumption with a registry-driven multi-sensor supervisor.
- [ ] Support multiple SGX and SPS30 units simultaneously.
- [ ] Add templated or generated systemd units per hardware id.
- [ ] Store sensor location and role, such as room, enclosure, exhaust, or chamber.
- [ ] Make dashboards filterable by sensor id and location.
- [ ] Add duplicate USB identity and conflicting device-path detection.

## Phase 7 — Appliance management UX

- [ ] Add `airmonitor inventory` and `airmonitor hardware ...` aliases to the main CLI.
- [ ] Add `sudo airmonitor update` as the supported wrapper around the update lifecycle.
- [ ] Add `sudo airmonitor install` for first-time installation.
- [ ] Add an interactive `airmonitor setup` flow for printer, sensors, filters, Grafana, and MQTT.
- [ ] Add EEPROM provisioning behind a guarded AirMonitor CLI command while retaining factory backup requirements.
- [ ] Add structured human-readable doctor output in addition to JSON.
- [ ] Add service log collection for support bundles with secrets redacted.

## Phase 8 — Reliability and releases

- [ ] Add end-to-end tests covering MQTT printer state through policy, filter decisions, database writes, and Grafana query generation.
- [ ] Add database backup/restore commands and documented retention policy.
- [ ] Add release tags and installed Git commit reporting.
- [ ] Add automatic rollback when install, update, service startup, or doctor fails.
- [ ] Add documented recovery from a damaged SQLite database or missing configuration.
- [ ] Define and test the v1.0 supported hardware and upgrade path.

## Phase 9 — Optional future expansion

- [ ] Additional particulate, CO2, temperature, humidity, and gas sensors through the plugin interfaces.
- [ ] Additional printer families through normalized MQTT or API adapters.
- [ ] Home Assistant and generic MQTT discovery integration.
- [ ] Remote appliance status without exposing secrets or control endpoints by default.

## Current next actions

1. Add sensor freshness and last-good-reading checks to `airmonitor-doctor`.
2. Add VOC/PM safety warnings and a basic notification channel (webhook/ntfy/Pushover).
3. Finish persisted filter override integration.
4. Pin dependencies with a lockfile and enforce ruff in CI.
5. Add automatic rollback on failed update health checks.
