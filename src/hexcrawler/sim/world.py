from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any

from hexcrawler.sim.rng import derive_stream_seed

SITE_TYPES = {"none", "town", "dungeon"}
RNG_WORLDGEN_STREAM_NAME = "rng_worldgen"
DEFAULT_TERRAIN_OPTIONS = ("plains", "forest", "hills")
DEFAULT_OVERWORLD_SPACE_ID = "overworld"


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


@dataclass
class SpaceState:
    space_id: str
    topology_type: str
    topology_params: dict[str, Any] = field(default_factory=dict)
    hexes: dict[HexCoord, HexRecord] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        hex_rows = []
        for coord in sorted(self.hexes):
            hex_rows.append({"coord": coord.to_dict(), "record": self.hexes[coord].to_dict()})
        return {
            "space_id": self.space_id,
            "topology_type": self.topology_type,
            "topology_params": dict(self.topology_params),
            "hexes": hex_rows,
        }

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
            return
        self.spaces[DEFAULT_OVERWORLD_SPACE_ID] = SpaceState(
            space_id=DEFAULT_OVERWORLD_SPACE_ID,
            topology_type=self.topology_type,
            topology_params=dict(self.topology_params),
            hexes=self.hexes,
        )

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
                key=lambda record: str(record.get("signal_uid", "")),
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
                key=lambda record: str(record.get("signal_uid", "")),
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
        world.signals = [dict(row) for row in raw_signals]

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
