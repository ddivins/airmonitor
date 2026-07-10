"""Bento Box filter integration."""

from __future__ import annotations

from dataclasses import dataclass

from airmonitor.filters.control import FilterState
from airmonitor.plugins import FilterPlugin, PluginInfo


@dataclass
class BentoFilter:
    """Bento Box filter plugin descriptor.

    The long-running Kasa/MQTT controller lives in
    :mod:`airmonitor.filters.bento.service`; this lightweight object gives the
    umbrella app a stable plugin surface for discovery and tests.
    """

    info: PluginInfo = PluginInfo(name="bento", kind="filter")

    def set_enabled(self, enabled: bool) -> None:
        raise NotImplementedError("Use airmonitor.filters.bento.service for device control")

    def desired_state(self, enabled: bool) -> FilterState:
        return FilterState.ON if enabled else FilterState.OFF


def plugin() -> FilterPlugin:
    return BentoFilter()


__all__ = ["BentoFilter", "plugin"]
