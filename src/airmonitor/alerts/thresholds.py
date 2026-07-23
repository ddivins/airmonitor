"""Configurable warning/critical thresholds for air-quality alerting.

AirMonitor is explicitly not a certified air-quality instrument (see the
project README), so these defaults are tunable starting points, not
calibrated safety limits. The PM2.5 defaults follow the EPA's published AQI
breakpoints (moderate/unhealthy-for-sensitive-groups boundaries); the VOC
defaults have no equivalent public standard and should be tuned against your
own sensor's baseline.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import yaml


@dataclass(frozen=True)
class MetricThreshold:
    warning: float | None
    critical: float | None


DEFAULT_THRESHOLDS: dict[str, MetricThreshold] = {
    "sgx_gas_ppm": MetricThreshold(warning=3.0, critical=10.0),
    "sps30_mass_pm2_5": MetricThreshold(warning=35.4, critical=150.4),
}


def load_thresholds(path: str | Path | None) -> dict[str, MetricThreshold]:
    """Return default thresholds merged with overrides from an optional YAML file."""

    thresholds = dict(DEFAULT_THRESHOLDS)
    if not path:
        return thresholds
    file = Path(path)
    if not file.exists():
        return thresholds
    data = yaml.safe_load(file.read_text(encoding="utf-8")) or {}
    if not isinstance(data, Mapping):
        return thresholds
    for key, values in data.items():
        if not isinstance(values, Mapping):
            continue
        warning = values.get("warning")
        critical = values.get("critical")
        thresholds[key] = MetricThreshold(
            warning=float(warning) if warning is not None else None,
            critical=float(critical) if critical is not None else None,
        )
    return thresholds
