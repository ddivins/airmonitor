# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
This project is pre-1.0, so minor version bumps may include breaking changes;
see `docs/roadmap.md` for the path to a defined v1.0.

## [0.7.0] - 2026-07-27

### Added

- New `airmonitor-compare-prints` Grafana dashboard: pick up to four prints
  and see them side by side, both as a summary table and as overlaid
  VOC/PM2.5/temperature charts aligned on elapsed time since print start.
  `docs/architecture.md` had always framed the project around comparative
  experiments (filtered vs. unfiltered, one filter medium vs. another), but
  nothing in the UI actually let you view two prints at once until now.
- A clickable AirMonitor logo banner on every custom Grafana dashboard,
  and — via an nginx `sub_filter` injection in front of Grafana's own pages
  — on Grafana's built-in pages too (`/grafana/dashboards`, etc.), so
  navigation back to the status page is consistent everywhere, not just on
  pages this project generates itself.
- `airmonitor alerts ack|unack|list`: an explicit acknowledgement/silence
  mechanism so a knowingly-accepted alert condition doesn't keep
  re-notifying. Persisted in the database (survives a service restart) and
  auto-cleared once the condition actually resolves.
- Filter-mismatch alerts now escalate from warning to critical if still open
  10 minutes later, instead of staying a flat "warning" indefinitely.
- Fake serial fixtures (`tests/fake_serial.py`) so the SGX/SPS30 read loops
  are tested against the real protocol-driving code — framing, checksums,
  measurement decoding — without physical hardware.
- Status page UI polish: a readable Services grid (was truncating labels
  and producing uneven card heights), a rebalanced Appliance panel, and a
  logo that consistently links home across every page.
- `tools/install.sh --migrate-from`: exercised end-to-end for the first
  time this release, migrating the production appliance from a Raspberry
  Pi 4 to a Raspberry Pi 5 (see `docs/hardware-bom.md`).

### Fixed

- Anonymous (logged-out) Grafana access silently requiring login whenever
  the configured organization name didn't match a real Grafana
  organization — Grafana doesn't error on this, it just can't attach the
  anonymous session, so it's easy to ship without noticing.
- Grafana's "AirMonitor Status" link, and the injected native-page banner,
  landing back on `/grafana` instead of the real status page — Grafana
  resolves root-relative links against its own sub-path.
- "Values must be in ascending order" on Compare Prints' overlay charts,
  caused by an elapsed-minutes column being misread as epoch time.
- Five bugs found while exercising `--migrate-from` end-to-end for the
  first time, all in the migration/install path rather than the appliance
  itself: `GRAFANA_ANONYMOUS_ORG_NAME` silently dropped across migration;
  `sudo -v` hanging under a host with both a password-required and a
  `NOPASSWD` sudoers grant; a global `umask 077` leaking into the venv and
  `pip install`, leaving files unreadable by the `automation`/`grafana`
  service accounts (including the Grafana SQLite plugin itself, which made
  every dashboard show no data); and, most seriously, migration corrupting
  the WAL-mode SQLite databases in transit — now checkpointed on the source
  and integrity-verified before install, so a bad copy fails loudly instead
  of silently going live.

## [0.6.0] - 2026-07-23

### Added

- Sensor freshness / last-good-reading checks in `airmonitor-doctor`
  (`sgx_freshness`, `sps30_freshness`), so a service that's systemd-active but
  silently producing no data is caught.
- New `airmonitor-alerts` service: evaluates VOC/PM readings against
  configurable thresholds (`config/alert-thresholds.yaml.example`), sensor
  freshness, and filter actual/effective-state mismatches, recording every
  transition in a new `alert_events` table and optionally notifying via a
  generic webhook or [ntfy](https://ntfy.sh) push
  (`config/env/alerts.env.example`). See `docs/alerting.md`.
- Stale printer-state handling in the Bento and Levoit filter services: a
  local MQTT printer-state feed that goes silent no longer gets silently read
  as "printer idle" — the last commanded filter state is held instead of
  risking filtration being cut off mid-print.
- Dependency pinning: `uv.lock` (authoritative) and a derived
  `requirements-lock.txt` consumed as a pip constraints file by
  `tools/update.sh` and CI, so appliance installs and CI runs resolve the
  same dependency versions.
- Committed ruff configuration and a lint step in CI (scoped to ruff's
  default rule set, which the existing codebase already passes cleanly).
- Automatic rollback: `tools/update.sh` now runs `tools/rollback.sh` itself
  if a service fails to (re)start or `airmonitor-doctor` reports a required
  failure, instead of only printing a manual rollback suggestion. Opt out
  with `AUTO_ROLLBACK=0`. See `docs/update-rollback.md`.

### Fixed

- `rollback.sh`'s default `SERVICE_LIST` was missing the alerts service.
- Re-prioritized `docs/roadmap.md`: promoted safety alerting ahead of
  multi-sensor/UX work, and corrected several Phase 4 (filter control)
  checklist items that were already implemented but not marked done.

## [0.5.0] and earlier

Predates this changelog. See `git log` for history, including the
config-driven fresh-host installer (`tools/install.sh`), the SPS30
particulate sensor driver, the status/landing page, and print-report
exports.
