from __future__ import annotations

from typing import Any

SUPPORTED_SCHEMA_VERSIONS = {1}
REQUIRED_HEX_RECORD_FIELDS = {"terrain_type", "site_type", "metadata"}
VALID_SITE_TYPES = {"none", "town", "dungeon"}
VALID_TOPOLOGY_TYPES = {"custom", "hex_disk", "hex_rectangle"}


def validate_world_payload(payload: dict[str, Any]) -> None:
    if not isinstance(payload, dict):
        raise ValueError("world payload must be an object")

    schema_version = payload.get("schema_version")
    if not isinstance(schema_version, int):
        raise ValueError("world payload must contain integer field: schema_version")
    if schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        raise ValueError(f"unsupported schema_version: {schema_version}")

    world_digest = payload.get("world_hash")
    if not isinstance(world_digest, str) or not world_digest:
        raise ValueError("world payload must contain string field: world_hash")

    topology_type = payload.get("topology_type")
    if not isinstance(topology_type, str):
        raise ValueError("world payload must contain string field: topology_type")
    if topology_type not in VALID_TOPOLOGY_TYPES:
        raise ValueError(f"unsupported topology_type: {topology_type}")

    topology_params = payload.get("topology_params")
    if not isinstance(topology_params, dict):
        raise ValueError("world payload must contain object field: topology_params")

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


def validate_save_payload(payload: dict[str, Any]) -> None:
    if not isinstance(payload, dict):
        raise ValueError("save payload must be an object")

    schema_version = payload.get("schema_version")
    if not isinstance(schema_version, int):
        raise ValueError("save payload must contain integer field: schema_version")
    if schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        raise ValueError(f"unsupported schema_version: {schema_version}")

    save_digest = payload.get("save_hash")
    if not isinstance(save_digest, str) or not save_digest:
        raise ValueError("save payload must contain string field: save_hash")

    world_state = payload.get("world_state")
    if not isinstance(world_state, dict):
        raise ValueError("save payload must contain object field: world_state")

    simulation_state = payload.get("simulation_state")
    if not isinstance(simulation_state, dict):
        raise ValueError("save payload must contain object field: simulation_state")

    input_log = payload.get("input_log")
    if not isinstance(input_log, list):
        raise ValueError("save payload must contain list field: input_log")

    if "metadata" in payload and not isinstance(payload["metadata"], dict):
        raise ValueError("save payload field metadata must be an object when present")
