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
        "master_seed": simulation.master_seed,
        "rng_state": simulation.rng_state_payload(),
        "tick": simulation.state.tick,
        "day": simulation.state.day,
        "world": simulation.state.world.to_dict(),
        "entities": [
            {
                "entity_id": entity.entity_id,
                "hex_coord": entity.hex_coord.to_dict(),
                "position_x": round(entity.position_x, 8),
                "position_y": round(entity.position_y, 8),
                "move_input_x": round(entity.move_input_x, 8),
                "move_input_y": round(entity.move_input_y, 8),
                "speed_per_tick": entity.speed_per_tick,
                "target_position": (
                    [round(entity.target_position[0], 8), round(entity.target_position[1], 8)]
                    if entity.target_position
                    else None
                ),
            }
            for entity in sorted(simulation.state.entities.values(), key=lambda e: e.entity_id)
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
