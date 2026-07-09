"""Filament environmental policy handling."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml


@dataclass(frozen=True)
class FilamentDecision:
    policy_version: str
    material: str | None
    matched_material: str | None
    emission_class: str
    odor_class: str
    particle_class: str
    bento_recommended: bool
    room_filter_recommended: bool

    def as_printer_state_fields(self) -> dict[str, Any]:
        return {
            "policy_version": self.policy_version,
            "filament_policy_material": self.matched_material,
            "filament_emission_class": self.emission_class,
            "filament_odor_class": self.odor_class,
            "filament_particle_class": self.particle_class,
            "bento_recommended": self.bento_recommended,
            "room_filter_recommended": self.room_filter_recommended,
        }


class FilamentPolicy:
    def __init__(self, raw: Mapping[str, Any]) -> None:
        self.raw = raw
        self.version = str(raw.get("policy_version", "unknown"))
        self.defaults = _as_mapping(raw.get("defaults"))
        self.materials = _as_mapping(raw.get("materials"))
        self.aliases: dict[str, str] = {}

        for material, entry in self.materials.items():
            canonical = normalize_material_name(material)
            self.aliases[canonical] = material
            entry_map = _as_mapping(entry)
            aliases = entry_map.get("aliases") or []
            if isinstance(aliases, list):
                for alias in aliases:
                    self.aliases[normalize_material_name(alias)] = material

    @classmethod
    def load(cls, path: str | Path) -> "FilamentPolicy":
        with Path(path).open("r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
        if not isinstance(raw, Mapping):
            raise ValueError(f"filament policy must be a YAML mapping: {path}")
        return cls(raw)

    def classify(self, material: str | None) -> FilamentDecision:
        normalized = normalize_material_name(material)
        matched = self.aliases.get(normalized)
        entry = _as_mapping(self.materials.get(matched)) if matched else {}

        return FilamentDecision(
            policy_version=self.version,
            material=material,
            matched_material=matched,
            emission_class=str(_first(entry, self.defaults, "emission_class", "unknown")),
            odor_class=str(_first(entry, self.defaults, "odor_class", "unknown")),
            particle_class=str(_first(entry, self.defaults, "particle_class", "unknown")),
            bento_recommended=bool(_first(entry, self.defaults, "bento_recommended", True)),
            room_filter_recommended=bool(_first(entry, self.defaults, "room_filter_recommended", False)),
        )


def normalize_material_name(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).strip().upper().replace("_", "-").split())


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _first(primary: Mapping[str, Any], secondary: Mapping[str, Any], key: str, default: Any) -> Any:
    if key in primary:
        return primary[key]
    if key in secondary:
        return secondary[key]
    return default
