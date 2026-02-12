from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

SITE_TYPES = {"none", "town", "dungeon"}


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

    def set_hex_record(self, coord: HexCoord, record: HexRecord) -> None:
        self.hexes[coord] = record

    def get_hex_record(self, coord: HexCoord) -> HexRecord | None:
        return self.hexes.get(coord)

    def to_dict(self) -> dict[str, Any]:
        hex_rows = []
        for coord in sorted(self.hexes):
            hex_rows.append({"coord": coord.to_dict(), "record": self.hexes[coord].to_dict()})
        return {"hexes": hex_rows}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorldState":
        world = cls()
        for row in data.get("hexes", []):
            coord = HexCoord.from_dict(row["coord"])
            record = HexRecord.from_dict(row["record"])
            world.set_hex_record(coord, record)
        return world
