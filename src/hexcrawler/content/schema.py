from __future__ import annotations

from typing import Any

SUPPORTED_SCHEMA_VERSIONS = {1}
REQUIRED_HEX_RECORD_FIELDS = {"terrain_type", "site_type", "metadata"}
VALID_SITE_TYPES = {"none", "town", "dungeon"}
VALID_TOPOLOGY_TYPES = {"custom", "hex_disk", "hex_rectangle", "overworld_hex", "dungeon_grid"}


def _is_json_primitive(value: Any) -> bool:
    return value is None or isinstance(value, (bool, int, float, str))


def _validate_json_value(value: Any, *, field_name: str) -> None:
    if _is_json_primitive(value):
        return
    if isinstance(value, list):
        for item in value:
            _validate_json_value(item, field_name=field_name)
        return
    if isinstance(value, dict):
        for key, nested_value in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{field_name} keys must be strings")
            _validate_json_value(nested_value, field_name=field_name)
        return
    raise ValueError(f"{field_name} must contain only canonical JSON primitives")




def _validate_space_shape(space: dict[str, Any], *, field_name: str) -> None:
    space_id = space.get("space_id")
    if not isinstance(space_id, str) or not space_id:
        raise ValueError(f"{field_name}.space_id must be a non-empty string")

    topology_type = space.get("topology_type")
    if not isinstance(topology_type, str):
        raise ValueError(f"{field_name}.topology_type must be a string")
    if topology_type not in VALID_TOPOLOGY_TYPES:
        raise ValueError(f"unsupported topology_type: {topology_type}")

    topology_params = space.get("topology_params")
    if not isinstance(topology_params, dict):
        raise ValueError(f"{field_name}.topology_params must be an object")

    hexes = space.get("hexes")
    if not isinstance(hexes, list):
        raise ValueError(f"{field_name}.hexes must be a list")

    for index, row in enumerate(hexes):
        if not isinstance(row, dict):
            raise ValueError(f"{field_name}.hexes[{index}] must be an object")
        if "coord" not in row or "record" not in row:
            raise ValueError(f"{field_name}.hexes[{index}] missing coord or record")

        coord = row["coord"]
        if not isinstance(coord, dict) or not {"q", "r"} <= coord.keys():
            raise ValueError(f"{field_name}.hexes[{index}] invalid coord")

        record = row["record"]
        if not isinstance(record, dict):
            raise ValueError(f"{field_name}.hexes[{index}].record must be object")

        missing = REQUIRED_HEX_RECORD_FIELDS - set(record.keys())
        if missing:
            raise ValueError(f"{field_name}.hexes[{index}] missing record fields: {sorted(missing)}")

        if record["site_type"] not in VALID_SITE_TYPES:
            raise ValueError(f"{field_name}.hexes[{index}] invalid site_type: {record['site_type']}")

        if not isinstance(record["metadata"], dict):
            raise ValueError(f"{field_name}.hexes[{index}] metadata must be object")

def _validate_world_shape(payload: dict[str, Any], *, field_prefix: str) -> None:
    spaces = payload.get("spaces")
    if spaces is not None:
        if not isinstance(spaces, list):
            raise ValueError(f"{field_prefix}.spaces must be a list when present")
        for index, space in enumerate(spaces):
            if not isinstance(space, dict):
                raise ValueError(f"{field_prefix}.spaces[{index}] must be an object")
            _validate_space_shape(space, field_name=f"{field_prefix}.spaces[{index}]")

        if not any(space.get("space_id") == "overworld" for space in spaces if isinstance(space, dict)):
            raise ValueError(f"{field_prefix}.spaces must include default space_id: overworld")
    else:
        legacy_space = {
            "space_id": "overworld",
            "topology_type": payload.get("topology_type"),
            "topology_params": payload.get("topology_params"),
            "hexes": payload.get("hexes"),
        }
        _validate_space_shape(legacy_space, field_name=field_prefix)

    signals = payload.get("signals", [])
    if not isinstance(signals, list):
        raise ValueError(f"{field_prefix}.signals must be a list when present")
    for index, signal in enumerate(signals):
        if not isinstance(signal, dict):
            raise ValueError(f"{field_prefix}.signals[{index}] must be an object")

    tracks = payload.get("tracks", [])
    if not isinstance(tracks, list):
        raise ValueError(f"{field_prefix}.tracks must be a list when present")
    for index, track in enumerate(tracks):
        if not isinstance(track, dict):
            raise ValueError(f"{field_prefix}.tracks[{index}] must be an object")

    spawn_descriptors = payload.get("spawn_descriptors", [])
    if not isinstance(spawn_descriptors, list):
        raise ValueError(f"{field_prefix}.spawn_descriptors must be a list when present")
    for index, descriptor in enumerate(spawn_descriptors):
        if not isinstance(descriptor, dict):
            raise ValueError(f"{field_prefix}.spawn_descriptors[{index}] must be an object")
        _validate_spawn_descriptor(
            descriptor,
            field_name=f"{field_prefix}.spawn_descriptors[{index}]",
        )

    rumors = payload.get("rumors", [])
    if not isinstance(rumors, list):
        raise ValueError(f"{field_prefix}.rumors must be a list when present")
    for index, record in enumerate(rumors):
        if not isinstance(record, dict):
            raise ValueError(f"{field_prefix}.rumors[{index}] must be an object")
        _validate_rumor_record(record, field_name=f"{field_prefix}.rumors[{index}]")


def _validate_spawn_descriptor(descriptor: dict[str, Any], *, field_name: str) -> None:
    required_int_fields = {"created_tick", "quantity"}
    for key in required_int_fields:
        value = descriptor.get(key)
        if not isinstance(value, int):
            raise ValueError(f"{field_name}.{key} must be an integer")

    required_string_fields = {"template_id", "source_event_id", "action_uid"}
    for key in required_string_fields:
        value = descriptor.get(key)
        if not isinstance(value, str) or not value:
            raise ValueError(f"{field_name}.{key} must be a non-empty string")

    location = descriptor.get("location")
    if not isinstance(location, dict):
        raise ValueError(f"{field_name}.location must be an object")

    expires_tick = descriptor.get("expires_tick")
    if expires_tick is not None and not isinstance(expires_tick, int):
        raise ValueError(f"{field_name}.expires_tick must be an integer when present")




def _validate_rumor_record(record: dict[str, Any], *, field_name: str) -> None:
    required_string_fields = {"rumor_id", "template_id", "source_action_uid"}
    for key in required_string_fields:
        value = record.get(key)
        if not isinstance(value, str) or not value:
            raise ValueError(f"{field_name}.{key} must be a non-empty string")

    required_int_fields = {"created_tick", "hop", "expires_tick"}
    for key in required_int_fields:
        value = record.get(key)
        if not isinstance(value, int):
            raise ValueError(f"{field_name}.{key} must be an integer")

    confidence = record.get("confidence")
    if not isinstance(confidence, (int, float)):
        raise ValueError(f"{field_name}.confidence must be numeric")
    if float(confidence) < 0.0 or float(confidence) > 1.0:
        raise ValueError(f"{field_name}.confidence must be within [0.0, 1.0]")

    location = record.get("location")
    if not isinstance(location, dict):
        raise ValueError(f"{field_name}.location must be an object")

    payload = record.get("payload")
    if payload is not None:
        if not isinstance(payload, dict):
            raise ValueError(f"{field_name}.payload must be an object when present")
        _validate_json_value(payload, field_name=f"{field_name}.payload")

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

    _validate_world_shape(payload, field_prefix="world payload")


def _validate_simulation_state(simulation_state: dict[str, Any]) -> None:
    required_int_fields = {"schema_version", "seed", "master_seed", "tick", "next_event_counter"}
    for field_name in required_int_fields:
        value = simulation_state.get(field_name)
        if not isinstance(value, int):
            raise ValueError(f"simulation_state.{field_name} must be an integer")

    entities = simulation_state.get("entities")
    if not isinstance(entities, list):
        raise ValueError("simulation_state.entities must be a list")

    pending_events = simulation_state.get("pending_events")
    if not isinstance(pending_events, list):
        raise ValueError("simulation_state.pending_events must be a list")

    rules_state = simulation_state.get("rules_state")
    if not isinstance(rules_state, dict):
        raise ValueError("simulation_state.rules_state must be an object")

    event_trace = simulation_state.get("event_trace")
    if not isinstance(event_trace, list):
        raise ValueError("simulation_state.event_trace must be a list")

    rng_state = simulation_state.get("rng_state")
    if not isinstance(rng_state, dict):
        raise ValueError("simulation_state.rng_state must be an object")


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
    _validate_world_shape(world_state, field_prefix="world_state")

    simulation_state = payload.get("simulation_state")
    if not isinstance(simulation_state, dict):
        raise ValueError("save payload must contain object field: simulation_state")
    _validate_simulation_state(simulation_state)

    input_log = payload.get("input_log")
    if not isinstance(input_log, list):
        raise ValueError("save payload must contain list field: input_log")

    if "metadata" in payload and not isinstance(payload["metadata"], dict):
        raise ValueError("save payload field metadata must be an object when present")

    _validate_json_value(payload["world_state"], field_name="world_state")
    _validate_json_value(payload["input_log"], field_name="input_log")
    if "metadata" in payload:
        _validate_json_value(payload["metadata"], field_name="metadata")
