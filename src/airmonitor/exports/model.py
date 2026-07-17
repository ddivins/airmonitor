"""Normalized data model shared by every export format."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class Metric:
    name: str
    unit: str
    baseline: float | None
    peak: float | None
    increase: float | None
    time_to_peak_seconds: float | None
    pre_print_samples: int
    in_print_samples: int
    post_print_samples: int
    total_samples: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "unit": self.unit,
            "baseline_method": "median of valid pre-print samples",
            "baseline": self.baseline,
            "peak_during_print": self.peak,
            "increase_above_baseline": self.increase,
            "time_to_peak_seconds": self.time_to_peak_seconds,
            "pre_print_samples": self.pre_print_samples,
            "in_print_samples": self.in_print_samples,
            "post_print_samples": self.post_print_samples,
            "total_samples": self.total_samples,
        }


@dataclass(frozen=True)
class PrintExport:
    print_id: int
    print_record: dict[str, Any]
    started_at: datetime
    ended_at: datetime
    window_start: datetime
    window_end: datetime
    generated_at: datetime
    active: bool
    sgx_samples: tuple[dict[str, Any], ...] = ()
    sps30_samples: tuple[dict[str, Any], ...] = ()
    levoit_samples: tuple[dict[str, Any], ...] = ()
    filter_state: tuple[dict[str, Any], ...] = ()
    metrics: dict[str, Metric] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    project_version: str = "unknown"
    git_commit: str = "unknown"

    @property
    def title(self) -> str:
        return str(self.print_record.get("subtask_name") or f"Print {self.print_id}")

    def metadata(self) -> dict[str, Any]:
        return {
            "project": "AirMonitor",
            "project_version": self.project_version,
            "git_commit": self.git_commit,
            "generated_at": _iso(self.generated_at),
            "print_id": self.print_id,
            "print_title": self.title,
            "print_active_when_generated": self.active,
            "print_started_at": _iso(self.started_at),
            "print_ended_at": _iso(self.ended_at),
            "export_window_start": _iso(self.window_start),
            "export_window_end": _iso(self.window_end),
            "window_methodology": "30 minutes before print start through 30 minutes after print end or last-seen time",
            "baseline_methodology": "median of valid samples in the 30-minute pre-print portion",
            "print": _json_safe(self.print_record),
            "sample_counts": {
                "sgx": len(self.sgx_samples),
                "sps30": len(self.sps30_samples),
                "levoit": len(self.levoit_samples),
            },
            "metrics": {key: value.as_dict() for key, value in self.metrics.items()},
            "filter_state_at_generation": [_json_safe(row) for row in self.filter_state],
            "warnings": list(self.warnings),
            "measurement_limitations": (
                "VOC values are intended for relative and comparative analysis. "
                "They are not compound-specific, regulatory, medical, OSHA-valid, "
                "or life-safety exposure measurements."
            ),
        }


def _iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _json_safe(value: Any) -> Any:
    if isinstance(value, datetime):
        return _iso(value)
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value
