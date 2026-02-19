from __future__ import annotations

import hashlib
import json
from typing import Any

from hexcrawler.sim.core import Simulation
from hexcrawler.sim.world import WorldState


def world_hash(world: WorldState) -> str:
    encoded = json.dumps(
        world.to_dict(),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def save_hash(payload: dict[str, Any]) -> str:
    hash_payload = {
        "schema_version": payload["schema_version"],
        "world_state": payload["world_state"],
        "simulation_state": payload["simulation_state"],
        "input_log": payload["input_log"],
    }
    encoded = json.dumps(hash_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def simulation_hash(simulation: Simulation) -> str:
    payload = {
        "seed": simulation.seed,
        "master_seed": simulation.master_seed,
        "rng_state": simulation.rng_state_payload(),
        "tick": simulation.state.tick,
        "time": simulation.state.time.to_dict(),
        "day": simulation.get_day_index(),
        "tick_in_day": simulation.get_tick_in_day(),
        "world": simulation.state.world.to_dict(),
        "entities": [
            {
                **{
                    "entity_id": entity.entity_id,
                    "space_id": entity.space_id,
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
                    "template_id": entity.template_id,
                    "source_action_uid": entity.source_action_uid,
                    "selected_entity_id": entity.selected_entity_id,
                    "inventory_container_id": entity.inventory_container_id,
                    "stats": entity.stats,
                },
            }
            for entity in sorted(simulation.state.entities.values(), key=lambda e: e.entity_id)
        ],
        "input_log": [command.to_dict() for command in simulation.input_log],
        "rules_state": dict(sorted(simulation.state.rules_state.items())),
        "next_event_counter": simulation._next_event_counter,
        "pending_events": [event.to_dict() for event in simulation.pending_events()],
        "event_trace": simulation.get_event_trace(),
        "selected_entity_id": simulation.state.selected_entity_id,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
