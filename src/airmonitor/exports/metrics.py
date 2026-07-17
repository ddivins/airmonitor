"""Defensible summary calculations for print exports."""

from __future__ import annotations

from datetime import datetime
from statistics import median
from typing import Any, Iterable

from airmonitor.exports.model import Metric


def calculate_metric(
    name: str,
    unit: str,
    samples: Iterable[dict[str, Any]],
    value_key: str,
    *,
    print_start: datetime,
    print_end: datetime,
) -> Metric:
    """Use the pre-print median because it resists short transient spikes."""
    valid: list[tuple[datetime, float]] = []
    for sample in samples:
        value = sample.get(value_key)
        sampled_at = sample.get("sampled_at")
        if isinstance(sampled_at, datetime) and isinstance(value, (int, float)):
            valid.append((sampled_at, float(value)))

    pre = [(when, value) for when, value in valid if when < print_start]
    during = [(when, value) for when, value in valid if print_start <= when <= print_end]
    post = [(when, value) for when, value in valid if when > print_end]
    baseline = median(value for _, value in pre) if pre else None
    peak_row = max(during, key=lambda item: item[1], default=None)
    peak = peak_row[1] if peak_row else None
    increase = peak - baseline if peak is not None and baseline is not None else None
    time_to_peak = (peak_row[0] - print_start).total_seconds() if peak_row else None
    return Metric(
        name=name,
        unit=unit,
        baseline=baseline,
        peak=peak,
        increase=increase,
        time_to_peak_seconds=time_to_peak,
        pre_print_samples=len(pre),
        in_print_samples=len(during),
        post_print_samples=len(post),
        total_samples=len(valid),
    )
