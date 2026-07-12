"""Keep the cloud-dependent Levoit service alive with conservative retries."""

from __future__ import annotations

import logging
import os
import sys
import time

from airmonitor.filters.levoit import service

LOG = logging.getLogger("airmonitor-levoit-supervisor")
DEFAULT_RETRY_DELAYS = (60, 120, 300, 900, 3600)


def parse_retry_delays(value: str | None) -> tuple[int, ...]:
    """Parse a comma-separated retry schedule, rejecting unsafe short delays."""
    if not value:
        return DEFAULT_RETRY_DELAYS

    delays: list[int] = []
    for item in value.split(","):
        item = item.strip()
        if not item:
            continue
        try:
            delay = int(item)
        except ValueError as exc:
            raise RuntimeError(
                "LEVOIT_RETRY_BACKOFF_SECONDS must be comma-separated integers"
            ) from exc
        if delay < 60:
            raise RuntimeError(
                "LEVOIT_RETRY_BACKOFF_SECONDS entries must be at least 60 seconds"
            )
        delays.append(delay)

    if not delays:
        raise RuntimeError("LEVOIT_RETRY_BACKOFF_SECONDS must contain at least one delay")
    return tuple(delays)


def sleep_interruptibly(seconds: int) -> None:
    """Sleep while still responding promptly to SIGTERM handled by service.py."""
    deadline = time.monotonic() + seconds
    while service.running and time.monotonic() < deadline:
        time.sleep(min(1.0, deadline - time.monotonic()))


def main() -> int:
    service.setup_logging()
    retry_delays = parse_retry_delays(os.environ.get("LEVOIT_RETRY_BACKOFF_SECONDS"))
    attempt = 0

    LOG.info("VeSync retry schedule: %s seconds", ", ".join(map(str, retry_delays)))

    while service.running:
        try:
            result = service.run_service()
            if not service.running:
                return result
            raise RuntimeError(f"Levoit service returned unexpectedly with status {result}")
        except KeyboardInterrupt:
            return 0
        except Exception as exc:
            delay = retry_delays[min(attempt, len(retry_delays) - 1)]
            attempt += 1
            reason = f"VeSync unavailable: {type(exc).__name__}: {exc}"
            LOG.warning("%s; retrying in %ss", reason, delay)
            service.record_filter_state(
                actual_state=service.FilterState.UNKNOWN.value,
                reason=reason,
            )
            sleep_interruptibly(delay)

    return 0


if __name__ == "__main__":
    sys.exit(main())
