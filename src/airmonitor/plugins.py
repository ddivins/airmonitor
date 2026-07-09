"""Plugin interface scaffolding for AirMonitor integrations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable, Any


@dataclass(frozen=True)
class PluginInfo:
    name: str
    kind: str
    enabled: bool = True


@runtime_checkable
class SensorPlugin(Protocol):
    info: PluginInfo

    def read(self) -> Any:
        """Read one sample from the sensor."""


@runtime_checkable
class PrinterPlugin(Protocol):
    info: PluginInfo

    def snapshot(self) -> dict[str, Any]:
        """Return the current printer state."""


@runtime_checkable
class FilterPlugin(Protocol):
    info: PluginInfo

    def set_enabled(self, enabled: bool) -> None:
        """Turn the filter on or off."""
