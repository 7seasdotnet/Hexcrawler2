from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from hexcrawler.sim.world import HexCoord

OVERWORLD_HEX_TOPOLOGY = "overworld_hex"
DEFAULT_SPACE_ID = "overworld"


@dataclass(frozen=True)
class LocationRef:
    """Opaque, serializable location reference for event contracts."""

    space_id: str
    topology_type: str
    coord: dict[str, Any]

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
