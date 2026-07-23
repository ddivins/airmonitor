# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
This project is pre-1.0, so minor version bumps may include breaking changes;
see `docs/roadmap.md` for the path to a defined v1.0.

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
