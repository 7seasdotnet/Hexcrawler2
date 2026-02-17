from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from hexcrawler.sim.world import HexCoord

OVERWORLD_HEX_TOPOLOGY = "overworld_hex"
SQUARE_GRID_TOPOLOGY = "square_grid"
DEFAULT_SPACE_ID = "overworld"


@dataclass(frozen=True)
class LocationRef:
    """Opaque, serializable location reference for event contracts."""

    space_id: str
    topology_type: str
    coord: dict[str, Any]

    def __post_init__(self) -> None:
        if not isinstance(self.space_id, str) or not self.space_id:
            raise ValueError("space_id must be a non-empty string")
        if not isinstance(self.topology_type, str) or not self.topology_type:
            raise ValueError("topology_type must be a non-empty string")
        if not isinstance(self.coord, dict):
            raise ValueError("coord must be an object")
        if self.topology_type == OVERWORLD_HEX_TOPOLOGY:
            HexCoord.from_dict(self.coord)
            return
        if self.topology_type == SQUARE_GRID_TOPOLOGY:
            if "x" not in self.coord or "y" not in self.coord:
                raise ValueError("square_grid coords require x and y")
            int(self.coord["x"])
            int(self.coord["y"])

    def to_dict(self) -> dict[str, Any]:
        return {
            "space_id": self.space_id,
            "topology_type": self.topology_type,
            "coord": dict(self.coord),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LocationRef":
        return cls(
            space_id=str(data.get("space_id", DEFAULT_SPACE_ID)),
            topology_type=str(data["topology_type"]),
            coord=dict(data["coord"]),
        )

    @classmethod
    def from_overworld_hex(cls, hex_coord: HexCoord) -> "LocationRef":
        return cls(
            space_id=DEFAULT_SPACE_ID,
            topology_type=OVERWORLD_HEX_TOPOLOGY,
            coord=hex_coord.to_dict(),
        )
