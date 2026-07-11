# AirMonitor Roadmap

This roadmap is ordered by dependency and operational value. Items near the top should be completed before lower items unless a hardware arrival changes priority.

## Phase 1 — Stabilize the appliance foundation

- [x] Consolidate legacy repositories into `ddivins/airmonitor`.
- [x] Preserve separate systemd services inside one package.
- [x] Add generated Grafana provisioning.
- [x] Add SQLite schema management and repositories.
- [x] Add appliance health checks and CI.
- [x] Add USB identity discovery, manual serial registration, and hot-plug recovery.
- [x] Add one-command hardware enrollment.
- [ ] Add an appliance inventory command that reports package version, registered hardware, resolved serial paths, service state, MQTT/Grafana reachability, and database status.
- [ ] Make `tools/update.sh` run the full doctor and fail clearly if required checks fail.
- [ ] Add rollback guidance and retain the previously installed wheel/version during updates.

## Phase 2 — Complete the sensor platform

- [ ] Implement the Sensirion SPS30 driver under `airmonitor.sensors.sensirion.sps30`.
- [ ] Support SPS30 USB-UART discovery and manual UART registration through the hardware registry.
- [ ] Add particulate sample tables and repository methods for PM1.0, PM2.5, PM4, PM10, particle counts, and typical particle size.
- [ ] Add an SPS30 service entry point with hot-plug behavior equivalent to the SGX service.
- [ ] Add SPS30 panels and combined environmental dashboards in Grafana.
- [ ] Add sensor freshness and last-good-reading checks to `airmonitor-doctor`.
- [ ] Add simulator/fake serial fixtures so sensor behavior is testable without physical hardware.

## Phase 3 — Multiple sensors and service instances

- [ ] Replace the single sensor service assumption with a registry-driven multi-sensor supervisor.
- [ ] Support multiple SGX and SPS30 units simultaneously.
- [ ] Add templated or generated systemd units per hardware id.
- [ ] Store sensor location and role, such as room, enclosure, exhaust, or chamber.
- [ ] Make dashboards filterable by sensor id and location.
- [ ] Add duplicate USB identity and conflicting device-path detection.

## Phase 4 — Filter control and observability

- [ ] Wire persisted `auto`, `on`, and `off` control modes into the Bento and Levoit services.
- [ ] Add CLI commands for filter status and override control.
- [ ] Record automation request, manual mode, effective state, actual state, reason, and command timestamp.
- [ ] Detect and honor external/manual device changes without immediately fighting the user.
- [ ] Add stale printer-state handling directly into filter controllers.
- [ ] Add filter state/reason panels to Grafana.
- [ ] Add VOC/PM safety warnings while preserving explicit user override policy.

## Phase 5 — Appliance management UX

- [ ] Add `airmonitor inventory` and `airmonitor hardware ...` aliases to the main CLI.
- [ ] Add `sudo airmonitor update` as the supported wrapper around the update lifecycle.
- [ ] Add `sudo airmonitor install` for first-time installation.
- [ ] Add an interactive `airmonitor setup` flow for printer, sensors, filters, Grafana, and MQTT.
- [ ] Add EEPROM provisioning behind a guarded AirMonitor CLI command while retaining factory backup requirements.
- [ ] Add structured human-readable doctor output in addition to JSON.
- [ ] Add service log collection for support bundles with secrets redacted.

## Phase 6 — Reliability and releases

- [ ] Add end-to-end tests covering MQTT printer state through policy, filter decisions, database writes, and Grafana query generation.
- [ ] Add database backup/restore commands and documented retention policy.
- [ ] Add release tags, changelog generation, and installed Git commit reporting.
- [ ] Add update rollback when install, migration, service startup, or doctor fails.
- [ ] Add documented recovery from a damaged SQLite database or missing configuration.
- [ ] Define and test the v1.0 supported hardware and upgrade path.

## Phase 7 — Optional future expansion

- [ ] Additional particulate, CO2, temperature, humidity, and gas sensors through the plugin interfaces.
- [ ] Additional printer families through normalized MQTT or API adapters.
- [ ] Home Assistant and generic MQTT discovery integration.
- [ ] Notifications for dangerous air-quality conditions, stale sensors, and failed filters.
- [ ] Remote appliance status without exposing secrets or control endpoints by default.

## Current next actions

1. Finish the inventory command and integrate it into tests/documentation.
2. Complete SPS30 protocol support and sample persistence.
3. Add SPS30 hot-plug service and Grafana panels.
4. Finish persisted filter override integration.
5. Convert the updater into a doctor-verified, rollback-capable lifecycle command.
