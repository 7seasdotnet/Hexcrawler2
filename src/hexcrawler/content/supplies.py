from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SUPPLY_PROFILE_SCHEMA_VERSION = 1
DEFAULT_SUPPLY_PROFILES_PATH = "content/supplies/supply_profiles.json"


@dataclass(frozen=True)
class SupplyConsumeDef:
    item_id: str
    quantity: int
    interval_ticks: int


@dataclass(frozen=True)
class SupplyProfileDef:
    profile_id: str
    consumes: tuple[SupplyConsumeDef, ...]


@dataclass(frozen=True)
class SupplyProfileRegistry:
    schema_version: int
    profiles: tuple[SupplyProfileDef, ...]

    def by_id(self) -> dict[str, SupplyProfileDef]:
        return {profile.profile_id: profile for profile in self.profiles}


def load_supply_profiles_json(path: str | Path) -> SupplyProfileRegistry:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return _registry_from_payload(payload)


def _registry_from_payload(payload: dict[str, Any]) -> SupplyProfileRegistry:
    if not isinstance(payload, dict):
        raise ValueError("supply profile payload must be an object")

    schema_version = payload.get("schema_version")
    if not isinstance(schema_version, int):
        raise ValueError("supply profile payload must contain integer field: schema_version")
    if schema_version != SUPPLY_PROFILE_SCHEMA_VERSION:
        raise ValueError(f"unsupported supply profile schema_version: {schema_version}")

    profiles = payload.get("profiles")
    if not isinstance(profiles, list):
        raise ValueError("supply profile payload must contain list field: profiles")

    seen_ids: set[str] = set()
    normalized_profiles: list[SupplyProfileDef] = []
    for index, row in enumerate(profiles):
        if not isinstance(row, dict):
            raise ValueError(f"profiles[{index}] must be an object")

        profile_id = row.get("profile_id")
        if not isinstance(profile_id, str) or not profile_id:
            raise ValueError(f"profiles[{index}].profile_id must be a non-empty string")
        if profile_id in seen_ids:
            raise ValueError(f"duplicate supply profile_id: {profile_id}")
        seen_ids.add(profile_id)

        consumes_payload = row.get("consumes")
        if not isinstance(consumes_payload, list) or not consumes_payload:
            raise ValueError(f"profiles[{index}].consumes must be a non-empty list")

        seen_item_ids: set[str] = set()
        consumes: list[SupplyConsumeDef] = []
        for consume_index, consume_row in enumerate(consumes_payload):
            if not isinstance(consume_row, dict):
                raise ValueError(f"profiles[{index}].consumes[{consume_index}] must be an object")

            item_id = consume_row.get("item_id")
            if not isinstance(item_id, str) or not item_id:
                raise ValueError(
                    f"profiles[{index}].consumes[{consume_index}].item_id must be a non-empty string"
                )
            if item_id in seen_item_ids:
                raise ValueError(f"profiles[{index}] duplicate consumes.item_id: {item_id}")
            seen_item_ids.add(item_id)

            quantity = consume_row.get("quantity")
            if not isinstance(quantity, int) or quantity <= 0:
                raise ValueError(f"profiles[{index}].consumes[{consume_index}].quantity must be integer > 0")

            interval_ticks = consume_row.get("interval_ticks")
            if not isinstance(interval_ticks, int) or interval_ticks <= 0:
                raise ValueError(
                    f"profiles[{index}].consumes[{consume_index}].interval_ticks must be integer > 0"
                )

            consumes.append(
                SupplyConsumeDef(item_id=item_id, quantity=quantity, interval_ticks=interval_ticks)
            )

        consumes.sort(key=lambda current: current.item_id)
        normalized_profiles.append(
            SupplyProfileDef(
                profile_id=profile_id,
                consumes=tuple(consumes),
            )
        )

    normalized_profiles.sort(key=lambda current: current.profile_id)
    return SupplyProfileRegistry(schema_version=schema_version, profiles=tuple(normalized_profiles))
