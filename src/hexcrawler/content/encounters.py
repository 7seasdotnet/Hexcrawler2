from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ENCOUNTER_TABLE_SCHEMA_VERSION = 1
DEFAULT_ENCOUNTER_TABLE_PATH = "content/examples/encounters/basic_encounters.json"


def _is_json_primitive(value: Any) -> bool:
    return value is None or isinstance(value, (bool, int, float, str))


def _normalize_json_value(value: Any, *, field_name: str) -> Any:
    if _is_json_primitive(value):
        return value
    if isinstance(value, list):
        return [_normalize_json_value(item, field_name=field_name) for item in value]
    if isinstance(value, dict):
        normalized: dict[str, Any] = {}
        for key in sorted(value):
            if not isinstance(key, str):
                raise ValueError(f"{field_name} keys must be strings")
            normalized[key] = _normalize_json_value(value[key], field_name=field_name)
        return normalized
    raise ValueError(f"{field_name} must contain only JSON-serializable values")


@dataclass(frozen=True)
class EncounterEntry:
    entry_id: str
    weight: int
    tags: tuple[str, ...]
    payload: dict[str, Any]


@dataclass(frozen=True)
class EncounterTable:
    schema_version: int
    table_id: str
    description: str | None
    entries: tuple[EncounterEntry, ...]

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "EncounterTable":
        validate_encounter_table_payload(payload)
        normalized_entries: list[EncounterEntry] = []
        for index, row in enumerate(payload["entries"]):
            raw_tags = row.get("tags", [])
            normalized_tags = tuple(sorted(dict.fromkeys(raw_tags)))
            normalized_payload = _normalize_json_value(row["payload"], field_name=f"entries[{index}].payload")
            normalized_entries.append(
                EncounterEntry(
                    entry_id=row["entry_id"],
                    weight=int(row["weight"]),
                    tags=normalized_tags,
                    payload=normalized_payload,
                )
            )

        return cls(
            schema_version=int(payload["schema_version"]),
            table_id=payload["table_id"],
            description=payload.get("description"),
            entries=tuple(normalized_entries),
        )


def validate_encounter_table_payload(payload: dict[str, Any]) -> None:
    if not isinstance(payload, dict):
        raise ValueError("encounter table payload must be an object")

    schema_version = payload.get("schema_version")
    if not isinstance(schema_version, int):
        raise ValueError("encounter table must contain integer field: schema_version")
    if schema_version != ENCOUNTER_TABLE_SCHEMA_VERSION:
        raise ValueError(f"unsupported encounter table schema_version: {schema_version}")

    table_id = payload.get("table_id")
    if not isinstance(table_id, str) or not table_id:
        raise ValueError("encounter table must contain non-empty string field: table_id")

    description = payload.get("description")
    if description is not None and not isinstance(description, str):
        raise ValueError("encounter table field description must be a string when present")

    entries = payload.get("entries")
    if not isinstance(entries, list) or not entries:
        raise ValueError("encounter table must contain non-empty list field: entries")

    seen_ids: set[str] = set()
    for index, row in enumerate(entries):
        if not isinstance(row, dict):
            raise ValueError(f"entries[{index}] must be an object")

        entry_id = row.get("entry_id")
        if not isinstance(entry_id, str) or not entry_id:
            raise ValueError(f"entries[{index}] must contain non-empty string field: entry_id")
        if entry_id in seen_ids:
            raise ValueError(f"duplicate encounter entry_id: {entry_id}")
        seen_ids.add(entry_id)

        weight = row.get("weight")
        if not isinstance(weight, int) or weight < 1:
            raise ValueError(f"entries[{index}] must contain integer weight >= 1")

        tags = row.get("tags", [])
        if not isinstance(tags, list):
            raise ValueError(f"entries[{index}] field tags must be a list when present")
        for tag_index, tag in enumerate(tags):
            if not isinstance(tag, str) or not tag:
                raise ValueError(f"entries[{index}].tags[{tag_index}] must be a non-empty string")

        if "payload" not in row:
            raise ValueError(f"entries[{index}] missing required field: payload")
        payload_value = row["payload"]
        if not isinstance(payload_value, dict):
            raise ValueError(f"entries[{index}] field payload must be an object")
        _normalize_json_value(payload_value, field_name=f"entries[{index}].payload")


def load_encounter_table_json(path: str | Path) -> EncounterTable:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return EncounterTable.from_payload(payload)
