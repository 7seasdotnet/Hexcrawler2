from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ITEMS_SCHEMA_VERSION = 1
DEFAULT_ITEMS_PATH = "content/items/items.json"


@dataclass(frozen=True)
class ItemDef:
    item_id: str
    name: str
    stackable: bool
    unit_mass: float
    tags: tuple[str, ...]


@dataclass(frozen=True)
class ItemRegistry:
    schema_version: int
    items: tuple[ItemDef, ...]

    def by_id(self) -> dict[str, ItemDef]:
        return {item.item_id: item for item in self.items}



def load_items_json(path: str | Path) -> ItemRegistry:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return _registry_from_payload(payload)



def _registry_from_payload(payload: dict[str, Any]) -> ItemRegistry:
    if not isinstance(payload, dict):
        raise ValueError("item registry payload must be an object")

    schema_version = payload.get("schema_version")
    if not isinstance(schema_version, int):
        raise ValueError("item registry must contain integer field: schema_version")
    if schema_version != ITEMS_SCHEMA_VERSION:
        raise ValueError(f"unsupported item registry schema_version: {schema_version}")

    items = payload.get("items")
    if not isinstance(items, list):
        raise ValueError("item registry must contain list field: items")

    normalized: list[ItemDef] = []
    seen_item_ids: set[str] = set()
    for index, row in enumerate(items):
        if not isinstance(row, dict):
            raise ValueError(f"items[{index}] must be an object")

        item_id = row.get("item_id")
        if not isinstance(item_id, str) or not item_id:
            raise ValueError(f"items[{index}].item_id must be a non-empty string")
        if item_id in seen_item_ids:
            raise ValueError(f"duplicate item_id: {item_id}")
        seen_item_ids.add(item_id)

        name = row.get("name")
        if not isinstance(name, str) or not name:
            raise ValueError(f"items[{index}].name must be a non-empty string")

        stackable = row.get("stackable")
        if stackable is not True:
            raise ValueError(f"items[{index}].stackable must be true in this phase")

        unit_mass = row.get("unit_mass")
        if not isinstance(unit_mass, (int, float)):
            raise ValueError(f"items[{index}].unit_mass must be numeric")
        unit_mass_value = float(unit_mass)
        if unit_mass_value < 0.0:
            raise ValueError(f"items[{index}].unit_mass must be >= 0")

        tags_payload = row.get("tags", [])
        if not isinstance(tags_payload, list):
            raise ValueError(f"items[{index}].tags must be a list when present")
        tags: list[str] = []
        for tag_index, tag in enumerate(tags_payload):
            if not isinstance(tag, str) or not tag:
                raise ValueError(f"items[{index}].tags[{tag_index}] must be a non-empty string")
            tags.append(tag)

        normalized.append(
            ItemDef(
                item_id=item_id,
                name=name,
                stackable=True,
                unit_mass=unit_mass_value,
                tags=tuple(sorted(dict.fromkeys(tags))),
            )
        )

    normalized.sort(key=lambda item: item.item_id)
    return ItemRegistry(schema_version=schema_version, items=tuple(normalized))
