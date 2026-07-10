"""Repository helpers that keep SQL out of application controllers."""

from __future__ import annotations

from dataclasses import dataclass
import sqlite3
from typing import Any

from airmonitor.database import (
    get_filter_control_state,
    set_filter_manual_mode,
    update_filter_control_state,
)


@dataclass(frozen=True)
class FilterControlRecord:
    filter_id: str
    manual_mode: str
    automation_request: str
    actual_state: str
    effective_state: str
    reason: str | None
    updated_at: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "FilterControlRecord":
        return cls(
            filter_id=row["filter_id"],
            manual_mode=row["manual_mode"],
            automation_request=row["automation_request"],
            actual_state=row["actual_state"],
            effective_state=row["effective_state"],
            reason=row["reason"],
            updated_at=row["updated_at"],
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "filter_id": self.filter_id,
            "manual_mode": self.manual_mode,
            "automation_request": self.automation_request,
            "actual_state": self.actual_state,
            "effective_state": self.effective_state,
            "reason": self.reason,
            "updated_at": self.updated_at,
        }


class FilterControlRepository:
    """Persistence boundary for filter override and resolved state."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def get(self, filter_id: str) -> FilterControlRecord:
        return FilterControlRecord.from_row(get_filter_control_state(self.conn, filter_id=filter_id))

    def set_manual_mode(self, filter_id: str, manual_mode: str) -> FilterControlRecord:
        row = set_filter_manual_mode(self.conn, filter_id=filter_id, manual_mode=manual_mode)
        return FilterControlRecord.from_row(row)

    def update(
        self,
        filter_id: str,
        *,
        manual_mode: str | None = None,
        automation_request: str | None = None,
        actual_state: str | None = None,
        effective_state: str | None = None,
        reason: str | None = None,
    ) -> FilterControlRecord:
        row = update_filter_control_state(
            self.conn,
            filter_id=filter_id,
            manual_mode=manual_mode,
            automation_request=automation_request,
            actual_state=actual_state,
            effective_state=effective_state,
            reason=reason,
        )
        return FilterControlRecord.from_row(row)
