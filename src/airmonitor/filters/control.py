"""Filter control state and manual override resolution."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class FilterMode(StrEnum):
    """User-selected filter control mode."""

    AUTO = "auto"
    ON = "on"
    OFF = "off"


class FilterState(StrEnum):
    """Simple filter on/off/unknown state."""

    ON = "on"
    OFF = "off"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class FilterDecision:
    """Resolved filter decision after manual override and automation policy."""

    filter_id: str
    manual_mode: FilterMode
    automation_request: FilterState
    effective_state: FilterState
    reason: str


def resolve_filter_state(
    *,
    filter_id: str,
    manual_mode: FilterMode | str,
    automation_request: FilterState | str,
    automation_reason: str = "automation",
) -> FilterDecision:
    """Resolve the effective filter state.

    Manual modes intentionally win over automation.
    """

    mode = FilterMode(manual_mode)
    request = FilterState(automation_request)

    if mode == FilterMode.ON:
        return FilterDecision(
            filter_id=filter_id,
            manual_mode=mode,
            automation_request=request,
            effective_state=FilterState.ON,
            reason="manual override: on",
        )

    if mode == FilterMode.OFF:
        return FilterDecision(
            filter_id=filter_id,
            manual_mode=mode,
            automation_request=request,
            effective_state=FilterState.OFF,
            reason="manual override: off",
        )

    return FilterDecision(
        filter_id=filter_id,
        manual_mode=mode,
        automation_request=request,
        effective_state=request,
        reason=automation_reason,
    )
