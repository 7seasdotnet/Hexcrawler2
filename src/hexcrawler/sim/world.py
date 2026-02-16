from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any

from hexcrawler.sim.rng import derive_stream_seed

SITE_TYPES = {"none", "town", "dungeon"}
RNG_WORLDGEN_STREAM_NAME = "rng_worldgen"
DEFAULT_TERRAIN_OPTIONS = ("plains", "forest", "hills")


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
class WorldState:
    hexes: dict[HexCoord, HexRecord] = field(default_factory=dict)
    topology_type: str = "custom"
    topology_params: dict[str, int] = field(default_factory=dict)
    signals: list[dict[str, Any]] = field(default_factory=list)
    tracks: list[dict[str, Any]] = field(default_factory=list)

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

    def to_dict(self) -> dict[str, Any]:
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
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorldState":
        world = cls(
            topology_type=str(data.get("topology_type", "custom")),
            topology_params=dict(data.get("topology_params", {})),
        )
        for row in data.get("hexes", []):
            coord = HexCoord.from_dict(row["coord"])
            record = HexRecord.from_dict(row["record"])
            world.set_hex_record(coord, record)
        raw_signals = data.get("signals", [])
        if not isinstance(raw_signals, list):
            raise ValueError("signals must be a list")
        world.signals = [dict(row) for row in raw_signals]

        raw_tracks = data.get("tracks", [])
        if not isinstance(raw_tracks, list):
            raise ValueError("tracks must be a list")
        world.tracks = [dict(row) for row in raw_tracks]
        return world

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
