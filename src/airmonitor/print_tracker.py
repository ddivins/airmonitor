"""Associate air samples with print records."""

from __future__ import annotations

import logging
import time
from typing import Any, Mapping

from airmonitor.database import finish_print, start_or_update_print


LOG = logging.getLogger(__name__)

ACTIVE_STATES = {"PREPARE", "RUNNING", "PAUSE"}
TERMINAL_STATES = {"FINISH", "FAILED", "CANCELLED", "CANCELED", "IDLE", "SLICING"}


class PrintTracker:
    """Track the current print using normalized printer MQTT state.

    Samples are associated with an active print while the printer is in an
    active state. When a print reaches a terminal state, the print is closed,
    but samples continue to reference that print for a short post-print context
    window so VOC/PM decay can still be attributed to the completed print.
    """

    def __init__(self, conn, *, post_print_context_seconds: int = 1800) -> None:
        self.conn = conn
        self.post_print_context_seconds = post_print_context_seconds
        self.active_print_id: int | None = None
        self.recent_print_id: int | None = None
        self.recent_until: float | None = None
        self.last_state: str | None = None

    def update(
        self,
        *,
        printer_state: Mapping[str, Any] | None,
        printer_available: str | None,
    ) -> int | None:
        if not printer_state:
            return self._recent_or_none()

        state = _upper_or_none(printer_state.get("gcode_state"))
        active = bool(printer_state.get("active")) or state in ACTIVE_STATES

        if state != self.last_state:
            LOG.info("Print tracker state transition: %s -> %s", self.last_state, state)
            self.last_state = state

        if active:
            self.recent_print_id = None
            self.recent_until = None
            self.active_print_id = start_or_update_print(
                self.conn,
                print_id=self.active_print_id,
                printer_state=printer_state,
                printer_available=printer_available,
                started_state=state,
            )
            return self.active_print_id

        disconnected = printer_available != "online" or not printer_state.get("connected")

        if self.active_print_id is not None and (state in TERMINAL_STATES or disconnected):
            closed_id = self.active_print_id
            finish_print(
                self.conn,
                print_id=closed_id,
                printer_state=printer_state,
                printer_available=printer_available,
                ended_state=state,
            )
            self.active_print_id = None
            self.recent_print_id = closed_id
            self.recent_until = time.time() + self.post_print_context_seconds
            LOG.info(
                "Print %s closed at state=%s; keeping post-print context for %ss",
                closed_id,
                state,
                self.post_print_context_seconds,
            )
            return closed_id

        if self.active_print_id is not None:
            # Ambiguous, non-terminal reading (e.g. gcode_state momentarily
            # null during bed-leveling/calibration) while the printer is
            # still connected: keep the current print open rather than
            # fragmenting it into a spurious extra row.
            return self.active_print_id

        return self._recent_or_none()

    def _recent_or_none(self) -> int | None:
        if self.recent_print_id is None or self.recent_until is None:
            return None
        if time.time() > self.recent_until:
            LOG.info("Post-print context expired for print %s", self.recent_print_id)
            self.recent_print_id = None
            self.recent_until = None
            return None
        return self.recent_print_id


def _upper_or_none(value: Any) -> str | None:
    if isinstance(value, str):
        return value.strip().upper()
    return None
