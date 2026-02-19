from __future__ import annotations

import random
import json
from dataclasses import dataclass, field
from typing import Any

from hexcrawler.sim.rng import derive_stream_seed

SITE_TYPES = {"none", "town", "dungeon"}
RNG_WORLDGEN_STREAM_NAME = "rng_worldgen"
DEFAULT_TERRAIN_OPTIONS = ("plains", "forest", "hills")
DEFAULT_OVERWORLD_SPACE_ID = "overworld"
SQUARE_GRID_TOPOLOGY = "square_grid"
MAX_SIGNALS = 256
MAX_OCCLUSION_EDGES = 2048


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




def _require_non_negative_int(value: Any, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} must be an integer")
    if value < 0:
        raise ValueError(f"{field_name} must be >= 0")
    return value


def _normalize_signal_origin(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("signal.origin must be an object")
    space_id = value.get("space_id")
    topology_type = value.get("topology_type")
    coord = value.get("coord")
    if not isinstance(space_id, str) or not space_id:
        raise ValueError("signal.origin.space_id must be a non-empty string")
    if not isinstance(topology_type, str) or not topology_type:
        raise ValueError("signal.origin.topology_type must be a non-empty string")
    if not isinstance(coord, dict):
        raise ValueError("signal.origin.coord must be an object")
    normalized_coord: dict[str, int] = {}
    for key, raw in coord.items():
        if not isinstance(key, str):
            raise ValueError("signal.origin.coord keys must be strings")
        if isinstance(raw, bool) or not isinstance(raw, int):
            raise ValueError(f"signal.origin.coord[{key}] must be an integer")
        normalized_coord[key] = raw
    return {"space_id": space_id, "topology_type": topology_type, "coord": normalized_coord}


def _normalize_signal_record(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("signal record must be an object")

    if "signal_id" not in value:
        _validate_json_value(value, field_name="signal")
        return dict(value)

    signal_id = value.get("signal_id")
    space_id = value.get("space_id")
    channel = value.get("channel")
    falloff_model = value.get("falloff_model")
    if not isinstance(signal_id, str) or not signal_id:
        raise ValueError("signal.signal_id must be a non-empty string")
    if not isinstance(space_id, str) or not space_id:
        raise ValueError("signal.space_id must be a non-empty string")
    if not isinstance(channel, str) or not channel:
        raise ValueError("signal.channel must be a non-empty string")
    if not isinstance(falloff_model, str) or not falloff_model:
        raise ValueError("signal.falloff_model must be a non-empty string")
    metadata = value.get("metadata", {})
    if not isinstance(metadata, dict):
        raise ValueError("signal.metadata must be an object")
    _validate_json_value(metadata, field_name="signal.metadata")
    return {
        "signal_id": signal_id,
        "tick_emitted": _require_non_negative_int(value.get("tick_emitted"), field_name="signal.tick_emitted"),
        "space_id": space_id,
        "origin": _normalize_signal_origin(value.get("origin")),
        "channel": channel,
        "base_intensity": _require_non_negative_int(value.get("base_intensity"), field_name="signal.base_intensity"),
        "falloff_model": falloff_model,
        "max_radius": _require_non_negative_int(value.get("max_radius"), field_name="signal.max_radius"),
        "ttl_ticks": _require_non_negative_int(value.get("ttl_ticks"), field_name="signal.ttl_ticks"),
        "metadata": dict(metadata),
    }


def _coord_sort_key(coord: dict[str, int]) -> tuple[int, int, int]:
    if "q" in coord and "r" in coord:
        return (0, int(coord["q"]), int(coord["r"]))
    if "x" in coord and "y" in coord:
        return (1, int(coord["x"]), int(coord["y"]))
    raise ValueError("coord must contain q/r or x/y")


def _canonicalize_edge_cells(cell_a: dict[str, Any], cell_b: dict[str, Any]) -> tuple[dict[str, int], dict[str, int]]:
    normalized_a = _normalize_coord_dict(dict(cell_a), field_name="structure_occlusion.cell_a")
    normalized_b = _normalize_coord_dict(dict(cell_b), field_name="structure_occlusion.cell_b")
    if set(normalized_a.keys()) != set(normalized_b.keys()):
        raise ValueError("structure_occlusion edge coords must share the same topology keys")
    if _coord_sort_key(normalized_b) < _coord_sort_key(normalized_a):
        return normalized_b, normalized_a
    return normalized_a, normalized_b


def canonical_occlusion_edge_key(space_id: str, cell_a: dict[str, Any], cell_b: dict[str, Any]) -> str:
    normalized_a, normalized_b = _canonicalize_edge_cells(cell_a, cell_b)
    if not isinstance(space_id, str) or not space_id:
        raise ValueError("structure_occlusion.space_id must be a non-empty string")
    payload = {"space_id": space_id, "cell_a": normalized_a, "cell_b": normalized_b}
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _normalize_occlusion_edge_record(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("structure_occlusion entry must be an object")
    space_id = value.get("space_id")
    if not isinstance(space_id, str) or not space_id:
        raise ValueError("structure_occlusion.space_id must be a non-empty string")
    cell_a, cell_b = _canonicalize_edge_cells(value.get("cell_a", {}), value.get("cell_b", {}))
    occlusion_value = _require_non_negative_int(value.get("occlusion_value"), field_name="structure_occlusion.occlusion_value")
    return {
        "space_id": space_id,
        "cell_a": cell_a,
        "cell_b": cell_b,
        "occlusion_value": occlusion_value,
    }

def _build_default_hex_record(rng_worldgen: random.Random) -> HexRecord:
    return HexRecord(terrain_type=rng_worldgen.choice(DEFAULT_TERRAIN_OPTIONS))


def generate_hex_disk(radius: int, rng_worldgen: random.Random) -> dict[HexCoord, HexRecord]:
    if radius < 0:
        raise ValueError("radius must be >= 0")

    hexes: dict[HexCoord, HexRecord] = {}
    for q in range(-radius, radius + 1):
        min_r = max(-radius, -q - radius)
        max_r = min(radius, -q + radius)
        for r in range(min_r, max_r + 1):
            coord = HexCoord(q=q, r=r)
            hexes[coord] = _build_default_hex_record(rng_worldgen)
    return hexes


def generate_hex_rectangle(width: int, height: int, rng_worldgen: random.Random) -> dict[HexCoord, HexRecord]:
    if width <= 0 or height <= 0:
        raise ValueError("width and height must be > 0")

    hexes: dict[HexCoord, HexRecord] = {}
    for q in range(width):
        for r in range(height):
            coord = HexCoord(q=q, r=r)
            hexes[coord] = _build_default_hex_record(rng_worldgen)
    return hexes


@dataclass(frozen=True, order=True)
class HexCoord:
    """Axial hex coordinate (q, r)."""

    q: int
    r: int

    def to_dict(self) -> dict[str, int]:
        return {"q": self.q, "r": self.r}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "HexCoord":
        return cls(q=int(data["q"]), r=int(data["r"]))


@dataclass
class HexRecord:
    terrain_type: str
    site_type: str = "none"
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.site_type not in SITE_TYPES:
            raise ValueError(f"invalid site_type: {self.site_type}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "terrain_type": self.terrain_type,
            "site_type": self.site_type,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "HexRecord":
        return cls(
            terrain_type=str(data["terrain_type"]),
            site_type=str(data.get("site_type", "none")),
            metadata=dict(data.get("metadata", {})),
        )


@dataclass
class RumorRecord:
    rumor_id: str
    created_tick: int
    location: dict[str, Any]
    template_id: str
    source_action_uid: str
    confidence: float
    hop: int
    expires_tick: int
    payload: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.rumor_id, str) or not self.rumor_id:
            raise ValueError("rumor_id must be a non-empty string")
        if not isinstance(self.created_tick, int):
            raise ValueError("created_tick must be an integer")
        if not isinstance(self.location, dict):
            raise ValueError("location must be an object")
        if not isinstance(self.template_id, str) or not self.template_id:
            raise ValueError("template_id must be a non-empty string")
        if not isinstance(self.source_action_uid, str) or not self.source_action_uid:
            raise ValueError("source_action_uid must be a non-empty string")
        if not isinstance(self.confidence, (int, float)):
            raise ValueError("confidence must be numeric")
        self.confidence = float(self.confidence)
        if self.confidence < 0.0 or self.confidence > 1.0:
            raise ValueError("confidence must be within [0.0, 1.0]")
        if not isinstance(self.hop, int) or self.hop < 0:
            raise ValueError("hop must be a non-negative integer")
        if not isinstance(self.expires_tick, int):
            raise ValueError("expires_tick must be an integer")
        if self.payload is not None:
            if not isinstance(self.payload, dict):
                raise ValueError("payload must be an object when present")
            _validate_json_value(self.payload, field_name="rumor.payload")

    def to_dict(self) -> dict[str, Any]:
        data = {
            "rumor_id": self.rumor_id,
            "created_tick": self.created_tick,
            "location": dict(self.location),
            "template_id": self.template_id,
            "source_action_uid": self.source_action_uid,
            "confidence": self.confidence,
            "hop": self.hop,
            "expires_tick": self.expires_tick,
        }
        if self.payload is not None:
            data["payload"] = dict(self.payload)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RumorRecord":
        return cls(
            rumor_id=str(data["rumor_id"]),
            created_tick=int(data["created_tick"]),
            location=dict(data["location"]),
            template_id=str(data["template_id"]),
            source_action_uid=str(data["source_action_uid"]),
            confidence=float(data["confidence"]),
            hop=int(data["hop"]),
            expires_tick=int(data["expires_tick"]),
            payload=(dict(data["payload"]) if data.get("payload") is not None else None),
        )


def _normalize_coord_dict(coord: dict[str, Any], *, field_name: str) -> dict[str, int]:
    if not isinstance(coord, dict):
        raise ValueError(f"{field_name} must be an object")
    if "x" in coord or "y" in coord:
        if "x" not in coord or "y" not in coord:
            raise ValueError(f"{field_name} requires x and y")
        return {"x": int(coord["x"]), "y": int(coord["y"])}
    if "q" in coord or "r" in coord:
        if "q" not in coord or "r" not in coord:
            raise ValueError(f"{field_name} requires q and r")
        return {"q": int(coord["q"]), "r": int(coord["r"])}
    raise ValueError(f"{field_name} requires either x/y or q/r")


@dataclass
class DoorRecord:
    door_id: str
    space_id: str
    a: dict[str, int]
    b: dict[str, int]
    state: str
    flags: dict[str, bool] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.door_id, str) or not self.door_id:
            raise ValueError("door_id must be a non-empty string")
        if not isinstance(self.space_id, str) or not self.space_id:
            raise ValueError("space_id must be a non-empty string")
        self.a = _normalize_coord_dict(self.a, field_name="door.a")
        self.b = _normalize_coord_dict(self.b, field_name="door.b")
        if self.state not in {"open", "closed"}:
            raise ValueError("door state must be 'open' or 'closed'")
        self.flags = {
            "locked": bool(self.flags.get("locked", False)),
            "blocked": bool(self.flags.get("blocked", False)),
        }
        _validate_json_value(self.metadata, field_name="door.metadata")

    def to_dict(self) -> dict[str, Any]:
        return {
            "door_id": self.door_id,
            "space_id": self.space_id,
            "a": dict(self.a),
            "b": dict(self.b),
            "state": self.state,
            "flags": dict(self.flags),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DoorRecord":
        return cls(
            door_id=str(data["door_id"]),
            space_id=str(data["space_id"]),
            a=dict(data["a"]),
            b=dict(data["b"]),
            state=str(data["state"]),
            flags=dict(data.get("flags", {})),
            metadata=dict(data.get("metadata", {})),
        )


@dataclass
class AnchorRecord:
    anchor_id: str
    space_id: str
    coord: dict[str, int]
    kind: str
    target: dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.anchor_id, str) or not self.anchor_id:
            raise ValueError("anchor_id must be a non-empty string")
        if not isinstance(self.space_id, str) or not self.space_id:
            raise ValueError("space_id must be a non-empty string")
        self.coord = _normalize_coord_dict(self.coord, field_name="anchor.coord")
        if self.kind not in {"exit", "return", "transition"}:
            raise ValueError("anchor kind must be one of exit|return|transition")
        if not isinstance(self.target, dict):
            raise ValueError("anchor.target must be an object")
        target_type = str(self.target.get("type", ""))
        if target_type not in {"space", "site"}:
            raise ValueError("anchor.target.type must be space or site")
        normalized_target: dict[str, Any] = {"type": target_type}
        if target_type == "space":
            space_id = self.target.get("space_id")
            if not isinstance(space_id, str) or not space_id:
                raise ValueError("anchor.target.space_id must be a non-empty string")
            normalized_target["space_id"] = space_id
        else:
            site_id = self.target.get("site_id")
            if not isinstance(site_id, str) or not site_id:
                raise ValueError("anchor.target.site_id must be a non-empty string")
            normalized_target["site_id"] = site_id
            if isinstance(self.target.get("space_id"), str) and self.target.get("space_id"):
                normalized_target["space_id"] = str(self.target["space_id"])
        self.target = normalized_target
        _validate_json_value(self.metadata, field_name="anchor.metadata")

    def to_dict(self) -> dict[str, Any]:
        return {
            "anchor_id": self.anchor_id,
            "space_id": self.space_id,
            "coord": dict(self.coord),
            "kind": self.kind,
            "target": dict(self.target),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AnchorRecord":
        return cls(
            anchor_id=str(data["anchor_id"]),
            space_id=str(data["space_id"]),
            coord=dict(data["coord"]),
            kind=str(data["kind"]),
            target=dict(data["target"]),
            metadata=dict(data.get("metadata", {})),
        )


@dataclass
class InteractableRecord:
    interactable_id: str
    space_id: str
    coord: dict[str, int]
    kind: str
    state: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.interactable_id, str) or not self.interactable_id:
            raise ValueError("interactable_id must be a non-empty string")
        if not isinstance(self.space_id, str) or not self.space_id:
            raise ValueError("space_id must be a non-empty string")
        self.coord = _normalize_coord_dict(self.coord, field_name="interactable.coord")
        if not isinstance(self.kind, str) or not self.kind:
            raise ValueError("interactable kind must be a non-empty string")
        if not isinstance(self.state, dict):
            raise ValueError("interactable state must be an object")
        _validate_json_value(self.state, field_name="interactable.state")
        _validate_json_value(self.metadata, field_name="interactable.metadata")

    def to_dict(self) -> dict[str, Any]:
        return {
            "interactable_id": self.interactable_id,
            "space_id": self.space_id,
            "coord": dict(self.coord),
            "kind": self.kind,
            "state": dict(self.state),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "InteractableRecord":
        return cls(
            interactable_id=str(data["interactable_id"]),
            space_id=str(data["space_id"]),
            coord=dict(data["coord"]),
            kind=str(data["kind"]),
            state=dict(data.get("state", {})),
            metadata=dict(data.get("metadata", {})),
        )


@dataclass
class SpaceState:
    space_id: str
    topology_type: str
    topology_params: dict[str, Any] = field(default_factory=dict)
    hexes: dict[HexCoord, HexRecord] = field(default_factory=dict)
    doors: dict[str, DoorRecord] = field(default_factory=dict)
    anchors: dict[str, AnchorRecord] = field(default_factory=dict)
    interactables: dict[str, InteractableRecord] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.topology_type == SQUARE_GRID_TOPOLOGY:
            self.topology_params = self._normalized_square_topology_params(self.topology_params)
        self._normalize_space_records()

    def _normalize_space_records(self) -> None:
        normalized_doors: dict[str, DoorRecord] = {}
        for door_id, record in self.doors.items():
            normalized_id = str(door_id)
            normalized = record if isinstance(record, DoorRecord) else DoorRecord.from_dict(dict(record))
            if normalized.door_id != normalized_id:
                raise ValueError("door record id mismatch")
            if normalized.space_id != self.space_id:
                raise ValueError("door record space_id mismatch")
            if not self.is_valid_cell(normalized.a) or not self.is_valid_cell(normalized.b):
                raise ValueError("door endpoints must reference valid cells")
            normalized_doors[normalized_id] = normalized
        self.doors = normalized_doors

        normalized_anchors: dict[str, AnchorRecord] = {}
        for anchor_id, record in self.anchors.items():
            normalized_id = str(anchor_id)
            normalized = record if isinstance(record, AnchorRecord) else AnchorRecord.from_dict(dict(record))
            if normalized.anchor_id != normalized_id:
                raise ValueError("anchor record id mismatch")
            if normalized.space_id != self.space_id:
                raise ValueError("anchor record space_id mismatch")
            if not self.is_valid_cell(normalized.coord):
                raise ValueError("anchor coord must reference a valid cell")
            normalized_anchors[normalized_id] = normalized
        self.anchors = normalized_anchors

        normalized_interactables: dict[str, InteractableRecord] = {}
        for interactable_id, record in self.interactables.items():
            normalized_id = str(interactable_id)
            normalized = (
                record if isinstance(record, InteractableRecord) else InteractableRecord.from_dict(dict(record))
            )
            if normalized.interactable_id != normalized_id:
                raise ValueError("interactable record id mismatch")
            if normalized.space_id != self.space_id:
                raise ValueError("interactable record space_id mismatch")
            if not self.is_valid_cell(normalized.coord):
                raise ValueError("interactable coord must reference a valid cell")
            normalized_interactables[normalized_id] = normalized
        self.interactables = normalized_interactables

    @staticmethod
    def _normalized_square_topology_params(topology_params: dict[str, Any]) -> dict[str, Any]:
        width = int(topology_params.get("width", 0))
        height = int(topology_params.get("height", 0))
        if width <= 0 or height <= 0:
            raise ValueError("square_grid topology requires width > 0 and height > 0")
        origin = topology_params.get("origin", {"x": 0, "y": 0})
        if not isinstance(origin, dict):
            raise ValueError("square_grid origin must be an object")
        origin_x = int(origin.get("x", 0))
        origin_y = int(origin.get("y", 0))
        return {
            "width": width,
            "height": height,
            "origin": {"x": origin_x, "y": origin_y},
        }

    def is_valid_cell(self, coord: dict[str, Any]) -> bool:
        if self.topology_type == SQUARE_GRID_TOPOLOGY:
            try:
                x = int(coord["x"])
                y = int(coord["y"])
            except (KeyError, TypeError, ValueError):
                return False
            params = self._normalized_square_topology_params(self.topology_params)
            origin = params["origin"]
            return (
                origin["x"] <= x < origin["x"] + params["width"]
                and origin["y"] <= y < origin["y"] + params["height"]
            )
        try:
            return HexCoord.from_dict(coord) in self.hexes
        except (KeyError, TypeError, ValueError):
            return False

    def iter_cells(self) -> list[dict[str, int]]:
        if self.topology_type == SQUARE_GRID_TOPOLOGY:
            params = self._normalized_square_topology_params(self.topology_params)
            origin = params["origin"]
            return [
                {"x": x, "y": y}
                for y in range(origin["y"], origin["y"] + params["height"])
                for x in range(origin["x"], origin["x"] + params["width"])
            ]
        return [coord.to_dict() for coord in sorted(self.hexes)]

    def default_spawn_coord(self) -> dict[str, int]:
        spawn = self.topology_params.get("spawn") if isinstance(self.topology_params, dict) else None
        if isinstance(spawn, dict) and self.is_valid_cell(spawn):
            return dict(spawn)
        if self.topology_type == SQUARE_GRID_TOPOLOGY:
            params = self._normalized_square_topology_params(self.topology_params)
            origin = params["origin"]
            return {"x": origin["x"], "y": origin["y"]}
        return {"q": 0, "r": 0}

    def to_dict(self) -> dict[str, Any]:
        hex_rows = []
        for coord in sorted(self.hexes):
            hex_rows.append({"coord": coord.to_dict(), "record": self.hexes[coord].to_dict()})
        payload = {
            "space_id": self.space_id,
            "topology_type": self.topology_type,
            "topology_params": dict(self.topology_params),
            "hexes": hex_rows,
        }
        if self.doors:
            payload["doors"] = {record_id: self.doors[record_id].to_dict() for record_id in sorted(self.doors)}
        if self.anchors:
            payload["anchors"] = {record_id: self.anchors[record_id].to_dict() for record_id in sorted(self.anchors)}
        if self.interactables:
            payload["interactables"] = {
                record_id: self.interactables[record_id].to_dict() for record_id in sorted(self.interactables)
            }
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SpaceState":
        space = cls(
            space_id=str(data["space_id"]),
            topology_type=str(data.get("topology_type", "custom")),
            topology_params=dict(data.get("topology_params", {})),
        )
        for row in data.get("hexes", []):
            coord = HexCoord.from_dict(row["coord"])
            record = HexRecord.from_dict(row["record"])
            space.hexes[coord] = record
        space.doors = {
            str(door_id): DoorRecord.from_dict(dict(row)) for door_id, row in dict(data.get("doors", {})).items()
        }
        space.anchors = {
            str(anchor_id): AnchorRecord.from_dict(dict(row)) for anchor_id, row in dict(data.get("anchors", {})).items()
        }
        space.interactables = {
            str(interactable_id): InteractableRecord.from_dict(dict(row))
            for interactable_id, row in dict(data.get("interactables", {})).items()
        }
        space._normalize_space_records()
        return space


@dataclass
class ContainerState:
    container_id: str
    location: dict[str, Any] | None = None
    owner_entity_id: str | None = None
    items: dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.container_id, str) or not self.container_id:
            raise ValueError("container_id must be a non-empty string")
        if self.location is not None and not isinstance(self.location, dict):
            raise ValueError("container location must be an object when present")
        if self.owner_entity_id is not None and (not isinstance(self.owner_entity_id, str) or not self.owner_entity_id):
            raise ValueError("owner_entity_id must be a non-empty string when present")

        normalized_items: dict[str, int] = {}
        for item_id, quantity in self.items.items():
            if not isinstance(item_id, str) or not item_id:
                raise ValueError("container item_id keys must be non-empty strings")
            if not isinstance(quantity, int):
                raise ValueError("container item quantities must be integers")
            if quantity < 0:
                raise ValueError("container item quantities must be >= 0")
            if quantity > 0:
                normalized_items[item_id] = quantity
        self.items = normalized_items

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "container_id": self.container_id,
            "items": {item_id: self.items[item_id] for item_id in sorted(self.items)},
        }
        if self.location is not None:
            payload["location"] = dict(self.location)
        if self.owner_entity_id is not None:
            payload["owner_entity_id"] = self.owner_entity_id
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ContainerState":
        return cls(
            container_id=str(data["container_id"]),
            location=(dict(data["location"]) if data.get("location") is not None else None),
            owner_entity_id=(str(data["owner_entity_id"]) if data.get("owner_entity_id") is not None else None),
            items=dict(data.get("items", {})),
        )


@dataclass
class SiteRecord:
    site_id: str
    site_type: str
    location: dict[str, Any]
    name: str | None = None
    description: str | None = None
    tags: list[str] = field(default_factory=list)
    entrance: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.site_id, str) or not self.site_id:
            raise ValueError("site_id must be a non-empty string")
        if not isinstance(self.site_type, str) or not self.site_type:
            raise ValueError("site_type must be a non-empty string")
        if not isinstance(self.location, dict):
            raise ValueError("location must be an object")
        if not isinstance(self.location.get("space_id"), str) or not self.location.get("space_id"):
            raise ValueError("location.space_id must be a non-empty string")
        coord = self.location.get("coord")
        if not isinstance(coord, dict):
            raise ValueError("location.coord must be an object")
        if self.name is not None and not isinstance(self.name, str):
            raise ValueError("name must be a string when present")
        if self.description is not None and not isinstance(self.description, str):
            raise ValueError("description must be a string when present")
        if not isinstance(self.tags, list):
            raise ValueError("tags must be a list")
        normalized_tags = sorted({str(tag) for tag in self.tags})
        self.tags = normalized_tags
        if self.entrance is not None:
            if not isinstance(self.entrance, dict):
                raise ValueError("entrance must be an object when present")
            target_space_id = self.entrance.get("target_space_id")
            if not isinstance(target_space_id, str) or not target_space_id:
                raise ValueError("entrance.target_space_id must be a non-empty string")
            spawn = self.entrance.get("spawn")
            if spawn is not None and not isinstance(spawn, dict):
                raise ValueError("entrance.spawn must be an object when present")

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "site_id": self.site_id,
            "site_type": self.site_type,
            "location": dict(self.location),
            "tags": list(self.tags),
        }
        if self.name is not None:
            payload["name"] = self.name
        if self.description is not None:
            payload["description"] = self.description
        if self.entrance is not None:
            payload["entrance"] = {
                "target_space_id": self.entrance["target_space_id"],
                "spawn": dict(self.entrance["spawn"]) if isinstance(self.entrance.get("spawn"), dict) else None,
            }
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SiteRecord":
        entrance_payload = data.get("entrance")
        entrance: dict[str, Any] | None
        if entrance_payload is None:
            entrance = None
        else:
            entrance = {
                "target_space_id": str(entrance_payload["target_space_id"]),
                "spawn": (
                    dict(entrance_payload["spawn"])
                    if isinstance(entrance_payload.get("spawn"), dict)
                    else None
                ),
            }
        return cls(
            site_id=str(data["site_id"]),
            site_type=str(data["site_type"]),
            location=dict(data["location"]),
            name=(str(data["name"]) if data.get("name") is not None else None),
            description=(str(data["description"]) if data.get("description") is not None else None),
            tags=[str(tag) for tag in data.get("tags", [])],
            entrance=entrance,
        )


@dataclass
class WorldState:
    hexes: dict[HexCoord, HexRecord] = field(default_factory=dict)
    topology_type: str = "custom"
    topology_params: dict[str, int] = field(default_factory=dict)
    spaces: dict[str, SpaceState] = field(default_factory=dict)
    signals: list[dict[str, Any]] = field(default_factory=list)
    structure_occlusion: list[dict[str, Any]] = field(default_factory=list)
    tracks: list[dict[str, Any]] = field(default_factory=list)
    spawn_descriptors: list[dict[str, Any]] = field(default_factory=list)
    rumors: list[dict[str, Any]] = field(default_factory=list)
    containers: dict[str, ContainerState] = field(default_factory=dict)
    sites: dict[str, SiteRecord] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.spaces:
            overworld_space = self.spaces.get(DEFAULT_OVERWORLD_SPACE_ID)
            if overworld_space is None:
                raise ValueError(f"spaces must include default '{DEFAULT_OVERWORLD_SPACE_ID}' space")
            self.hexes = overworld_space.hexes
            self.topology_type = overworld_space.topology_type
            self.topology_params = dict(overworld_space.topology_params)
            self._ensure_closed_door_occlusion_defaults()
            return
        self.spaces[DEFAULT_OVERWORLD_SPACE_ID] = SpaceState(
            space_id=DEFAULT_OVERWORLD_SPACE_ID,
            topology_type=self.topology_type,
            topology_params=dict(self.topology_params),
            hexes=self.hexes,
        )
        self._ensure_closed_door_occlusion_defaults()

    @classmethod
    def create_with_topology(
        cls,
        master_seed: int,
        topology_type: str,
        topology_params: dict[str, int],
    ) -> "WorldState":
        rng_worldgen = random.Random(
            derive_stream_seed(master_seed=master_seed, stream_name=RNG_WORLDGEN_STREAM_NAME)
        )
        if topology_type == "hex_disk":
            radius = int(topology_params["radius"])
            hexes = generate_hex_disk(radius=radius, rng_worldgen=rng_worldgen)
        elif topology_type == "hex_rectangle":
            width = int(topology_params["width"])
            height = int(topology_params["height"])
            hexes = generate_hex_rectangle(width=width, height=height, rng_worldgen=rng_worldgen)
        else:
            raise ValueError(f"unsupported topology_type: {topology_type}")

        return cls(hexes=hexes, topology_type=topology_type, topology_params=dict(topology_params))

    def set_hex_record(self, coord: HexCoord, record: HexRecord) -> None:
        self.hexes[coord] = record

    def get_hex_record(self, coord: HexCoord) -> HexRecord | None:
        return self.hexes.get(coord)

    def to_legacy_dict(self) -> dict[str, Any]:
        hex_rows = []
        for coord in sorted(self.hexes):
            hex_rows.append({"coord": coord.to_dict(), "record": self.hexes[coord].to_dict()})
        payload = {
            "topology_type": self.topology_type,
            "topology_params": self.topology_params,
            "hexes": hex_rows,
        }
        if self.signals:
            payload["signals"] = sorted(
                (dict(record) for record in self.signals),
                key=lambda record: str(record.get("signal_id", record.get("signal_uid", ""))),
            )
        if self.tracks:
            payload["tracks"] = sorted(
                (dict(record) for record in self.tracks),
                key=lambda record: str(record.get("track_uid", "")),
            )
        if self.spawn_descriptors:
            payload["spawn_descriptors"] = [dict(record) for record in self.spawn_descriptors]
        if self.rumors:
            payload["rumors"] = [RumorRecord.from_dict(record).to_dict() for record in self.rumors]
        if self.containers:
            payload["containers"] = {
                container_id: self.containers[container_id].to_dict()
                for container_id in sorted(self.containers)
            }
        if self.sites:
            payload["sites"] = {
                site_id: self.sites[site_id].to_dict()
                for site_id in sorted(self.sites)
            }
        return payload

    def to_dict(self) -> dict[str, Any]:
        spaces_payload = [
            self.spaces[space_id].to_dict()
            for space_id in sorted(self.spaces)
        ]
        hex_rows = []
        for coord in sorted(self.hexes):
            hex_rows.append({"coord": coord.to_dict(), "record": self.hexes[coord].to_dict()})
        payload = {
            "topology_type": self.topology_type,
            "topology_params": self.topology_params,
            "hexes": hex_rows,
            "spaces": spaces_payload,
        }
        if self.signals:
            payload["signals"] = sorted(
                (dict(record) for record in self.signals),
                key=lambda record: str(record.get("signal_id", record.get("signal_uid", ""))),
            )
        if self.structure_occlusion:
            payload["structure_occlusion"] = sorted(
                (dict(record) for record in self.structure_occlusion),
                key=lambda record: canonical_occlusion_edge_key(
                    str(record.get("space_id", "")),
                    dict(record.get("cell_a", {})),
                    dict(record.get("cell_b", {})),
                ),
            )
        if self.tracks:
            payload["tracks"] = sorted(
                (dict(record) for record in self.tracks),
                key=lambda record: str(record.get("track_uid", "")),
            )
        if self.spawn_descriptors:
            payload["spawn_descriptors"] = [dict(record) for record in self.spawn_descriptors]
        if self.rumors:
            payload["rumors"] = [RumorRecord.from_dict(record).to_dict() for record in self.rumors]
        if self.containers:
            payload["containers"] = {
                container_id: self.containers[container_id].to_dict()
                for container_id in sorted(self.containers)
            }
        if self.sites:
            payload["sites"] = {
                site_id: self.sites[site_id].to_dict()
                for site_id in sorted(self.sites)
            }
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorldState":
        raw_spaces = data.get("spaces")
        if raw_spaces is None:
            world = cls(
                topology_type=str(data.get("topology_type", "custom")),
                topology_params=dict(data.get("topology_params", {})),
            )
            for row in data.get("hexes", []):
                coord = HexCoord.from_dict(row["coord"])
                record = HexRecord.from_dict(row["record"])
                world.set_hex_record(coord, record)
        else:
            if not isinstance(raw_spaces, list):
                raise ValueError("spaces must be a list")
            spaces: dict[str, SpaceState] = {}
            for entry in raw_spaces:
                if not isinstance(entry, dict):
                    raise ValueError("space entry must be an object")
                space = SpaceState.from_dict(entry)
                spaces[space.space_id] = space
            world = cls(spaces=spaces)
            legacy_hex_rows = data.get("hexes")
            if legacy_hex_rows is not None:
                legacy_world = cls(
                    topology_type=str(data.get("topology_type", world.topology_type)),
                    topology_params=dict(data.get("topology_params", world.topology_params)),
                )
                for row in legacy_hex_rows:
                    coord = HexCoord.from_dict(row["coord"])
                    record = HexRecord.from_dict(row["record"])
                    legacy_world.set_hex_record(coord, record)
                if legacy_world.to_legacy_dict() != world.to_legacy_dict():
                    raise ValueError("legacy overworld fields disagree with spaces.overworld payload")
        raw_signals = data.get("signals", [])
        if not isinstance(raw_signals, list):
            raise ValueError("signals must be a list")
        world.signals = [_normalize_signal_record(row) for row in raw_signals]
        if len(world.signals) > MAX_SIGNALS:
            world.signals = world.signals[-MAX_SIGNALS:]

        raw_structure_occlusion = data.get("structure_occlusion", [])
        if not isinstance(raw_structure_occlusion, list):
            raise ValueError("structure_occlusion must be a list")
        world.structure_occlusion = [_normalize_occlusion_edge_record(row) for row in raw_structure_occlusion]
        if len(world.structure_occlusion) > MAX_OCCLUSION_EDGES:
            world.structure_occlusion = world.structure_occlusion[-MAX_OCCLUSION_EDGES:]
        world._ensure_closed_door_occlusion_defaults()

        raw_tracks = data.get("tracks", [])
        if not isinstance(raw_tracks, list):
            raise ValueError("tracks must be a list")
        world.tracks = [dict(row) for row in raw_tracks]

        raw_spawn_descriptors = data.get("spawn_descriptors", [])
        if not isinstance(raw_spawn_descriptors, list):
            raise ValueError("spawn_descriptors must be a list")
        world.spawn_descriptors = [dict(row) for row in raw_spawn_descriptors]

        raw_rumors = data.get("rumors", [])
        if not isinstance(raw_rumors, list):
            raise ValueError("rumors must be a list")
        world.rumors = [RumorRecord.from_dict(dict(row)).to_dict() for row in raw_rumors]

        raw_containers = data.get("containers", {})
        if not isinstance(raw_containers, dict):
            raise ValueError("containers must be an object")
        world.containers = {}
        for container_id in sorted(raw_containers):
            row = raw_containers[container_id]
            if not isinstance(row, dict):
                raise ValueError(f"container '{container_id}' must be an object")
            if "container_id" not in row:
                row = {**row, "container_id": container_id}
            container = ContainerState.from_dict(row)
            if container.container_id != container_id:
                raise ValueError(f"container key/id mismatch for '{container_id}'")
            world.containers[container_id] = container

        raw_sites = data.get("sites", {})
        if not isinstance(raw_sites, dict):
            raise ValueError("sites must be an object")
        world.sites = {}
        for site_id in sorted(raw_sites):
            row = raw_sites[site_id]
            if not isinstance(row, dict):
                raise ValueError(f"site '{site_id}' must be an object")
            if "site_id" not in row:
                row = {**row, "site_id": site_id}
            site = SiteRecord.from_dict(row)
            if site.site_id != site_id:
                raise ValueError(f"site key/id mismatch for '{site_id}'")
            world.sites[site_id] = site
        return world

    def get_sites_at_location(self, location_ref: dict[str, Any]) -> list[SiteRecord]:
        space_id = str(location_ref.get("space_id", ""))
        coord = location_ref.get("coord")
        if not isinstance(coord, dict):
            return []
        matches = [
            site
            for site in self.sites.values()
            if site.location.get("space_id") == space_id and site.location.get("coord") == coord
        ]
        return sorted(matches, key=lambda site: site.site_id)

    def upsert_signal(self, record: dict[str, Any]) -> bool:
        signal_uid = str(record["signal_uid"])
        for existing in self.signals:
            if str(existing.get("signal_uid")) == signal_uid:
                return False
        self.signals.append(dict(record))
        return True

    def append_signal_record(self, record: dict[str, Any]) -> None:
        self.signals.append(_normalize_signal_record(record))
        if len(self.signals) > MAX_SIGNALS:
            del self.signals[: len(self.signals) - MAX_SIGNALS]

    def get_structure_occlusion_value(self, *, space_id: str, cell_a: dict[str, Any], cell_b: dict[str, Any]) -> int:
        edge_key = canonical_occlusion_edge_key(space_id, cell_a, cell_b)
        for record in self.structure_occlusion:
            if canonical_occlusion_edge_key(record["space_id"], record["cell_a"], record["cell_b"]) == edge_key:
                return int(record["occlusion_value"])
        return 0

    def set_structure_occlusion_edge(self, *, space_id: str, cell_a: dict[str, Any], cell_b: dict[str, Any], occlusion_value: int) -> None:
        normalized = _normalize_occlusion_edge_record(
            {
                "space_id": space_id,
                "cell_a": cell_a,
                "cell_b": cell_b,
                "occlusion_value": occlusion_value,
            }
        )
        edge_key = canonical_occlusion_edge_key(normalized["space_id"], normalized["cell_a"], normalized["cell_b"])
        for index, record in enumerate(self.structure_occlusion):
            existing_key = canonical_occlusion_edge_key(record["space_id"], record["cell_a"], record["cell_b"])
            if existing_key != edge_key:
                continue
            if normalized["occlusion_value"] <= 0:
                del self.structure_occlusion[index]
                return
            self.structure_occlusion[index] = normalized
            return
        if normalized["occlusion_value"] <= 0:
            return
        self.structure_occlusion.append(normalized)
        if len(self.structure_occlusion) > MAX_OCCLUSION_EDGES:
            del self.structure_occlusion[: len(self.structure_occlusion) - MAX_OCCLUSION_EDGES]

    def _ensure_closed_door_occlusion_defaults(self) -> None:
        for space_id in sorted(self.spaces):
            space = self.spaces[space_id]
            for door_id in sorted(space.doors):
                door = space.doors[door_id]
                if door.state != "closed":
                    continue
                edge_value = self.get_structure_occlusion_value(space_id=space_id, cell_a=door.a, cell_b=door.b)
                if edge_value > 0:
                    continue
                self.set_structure_occlusion_edge(
                    space_id=space_id,
                    cell_a=door.a,
                    cell_b=door.b,
                    occlusion_value=1,
                )

    def upsert_track(self, record: dict[str, Any]) -> bool:
        track_uid = str(record["track_uid"])
        for existing in self.tracks:
            if str(existing.get("track_uid")) == track_uid:
                return False
        self.tracks.append(dict(record))
        return True

    def append_spawn_descriptor(self, record: dict[str, Any]) -> None:
        self.spawn_descriptors.append(dict(record))

    def append_rumor(self, record: RumorRecord | dict[str, Any]) -> None:
        normalized = record if isinstance(record, RumorRecord) else RumorRecord.from_dict(record)
        self.rumors.append(normalized.to_dict())
