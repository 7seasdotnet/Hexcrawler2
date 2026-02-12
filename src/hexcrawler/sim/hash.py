from __future__ import annotations

import hashlib
import json

from hexcrawler.sim.core import Simulation
from hexcrawler.sim.world import WorldState


def world_hash(world: WorldState) -> str:
    encoded = json.dumps(
        world.to_dict(),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def simulation_hash(simulation: Simulation) -> str:
    payload = {
        "seed": simulation.seed,
        "tick": simulation.state.tick,
        "day": simulation.state.day,
        "world": simulation.state.world.to_dict(),
        "entities": [
            {
                "entity_id": entity.entity_id,
                "hex_coord": entity.hex_coord.to_dict(),
                "offset_x": round(entity.offset_x, 8),
                "offset_y": round(entity.offset_y, 8),
                "speed_per_tick": entity.speed_per_tick,
                "destination": entity.destination.to_dict() if entity.destination else None,
            }
            for entity in sorted(simulation.state.entities.values(), key=lambda e: e.entity_id)
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
