from __future__ import annotations

from typing import Any

REQUIRED_HEX_RECORD_FIELDS = {"terrain_type", "site_type", "metadata"}
VALID_SITE_TYPES = {"none", "town", "dungeon"}


def validate_world_payload(payload: dict[str, Any]) -> None:
    if not isinstance(payload, dict):
        raise ValueError("world payload must be an object")

    hexes = payload.get("hexes")
    if not isinstance(hexes, list):
        raise ValueError("world payload must contain a list field: hexes")

    for index, row in enumerate(hexes):
        if not isinstance(row, dict):
            raise ValueError(f"hex row {index} must be an object")
        if "coord" not in row or "record" not in row:
            raise ValueError(f"hex row {index} missing coord or record")

        coord = row["coord"]
        if not isinstance(coord, dict) or not {"q", "r"} <= coord.keys():
            raise ValueError(f"hex row {index} invalid coord")

        record = row["record"]
        if not isinstance(record, dict):
            raise ValueError(f"hex row {index} record must be object")

        missing = REQUIRED_HEX_RECORD_FIELDS - set(record.keys())
        if missing:
            raise ValueError(f"hex row {index} missing record fields: {sorted(missing)}")

        if record["site_type"] not in VALID_SITE_TYPES:
            raise ValueError(f"hex row {index} invalid site_type: {record['site_type']}")

        if not isinstance(record["metadata"], dict):
            raise ValueError(f"hex row {index} metadata must be object")
