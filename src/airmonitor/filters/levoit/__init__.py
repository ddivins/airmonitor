"""Levoit room filter integration."""

from __future__ import annotations

from dataclasses import dataclass

from airmonitor.filters.control import FilterState
from airmonitor.plugins import FilterPlugin, PluginInfo


@dataclass
class LevoitFilter:
    """Levoit/Core purifier plugin descriptor.

    The VeSync-backed automation and manual commands live in
    :mod:`airmonitor.filters.levoit.service`.
    """

    info: PluginInfo = PluginInfo(name="levoit", kind="filter")

    def set_enabled(self, enabled: bool) -> None:
        raise NotImplementedError("Use airmonitor.filters.levoit.service for device control")

    def desired_state(self, enabled: bool) -> FilterState:
        return FilterState.ON if enabled else FilterState.OFF


def plugin() -> FilterPlugin:
    return LevoitFilter()


__all__ = ["LevoitFilter", "plugin"]
