from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any

from hexcrawler.sim.movement import axial_to_world_xy, normalized_vector, world_xy_to_axial
from hexcrawler.sim.rng import derive_stream_seed
from hexcrawler.sim.world import HexCoord, WorldState

TICKS_PER_DAY = 240
TARGET_REACHED_THRESHOLD = 0.05

RNG_SIM_STREAM_NAME = "rng_sim"
RNG_WORLDGEN_STREAM_NAME = "rng_worldgen"


@dataclass
class EntityState:
    entity_id: str
    position_x: float
    position_y: float
    speed_per_tick: float = 0.15
    move_input_x: float = 0.0
    move_input_y: float = 0.0
    target_position: tuple[float, float] | None = None

    @classmethod
    def from_hex(cls, entity_id: str, hex_coord: HexCoord, speed_per_tick: float = 0.15) -> "EntityState":
        x, y = axial_to_world_xy(hex_coord)
        return cls(entity_id=entity_id, position_x=x, position_y=y, speed_per_tick=speed_per_tick)

    @property
    def hex_coord(self) -> HexCoord:
        return world_xy_to_axial(self.position_x, self.position_y)

    def world_xy(self) -> tuple[float, float]:
        return (self.position_x, self.position_y)


@dataclass
class SimulationState:
    world: WorldState
    tick: int = 0
    entities: dict[str, EntityState] = field(default_factory=dict)

    @property
    def day(self) -> int:
        return self.tick // TICKS_PER_DAY


class Simulation:
    def __init__(self, world: WorldState, seed: int) -> None:
        self.state = SimulationState(world=world)
        self.seed = seed
        self.master_seed = seed
        self.rng_worldgen = random.Random(derive_stream_seed(master_seed=self.master_seed, stream_name=RNG_WORLDGEN_STREAM_NAME))
        self.rng_sim = random.Random(derive_stream_seed(master_seed=self.master_seed, stream_name=RNG_SIM_STREAM_NAME))
        # Backward compatibility: preserve existing `sim.rng` consumers as simulation stream.
        self.rng = self.rng_sim

    def add_entity(self, entity: EntityState) -> None:
        self.state.entities[entity.entity_id] = entity

    def set_entity_destination(self, entity_id: str, destination: HexCoord) -> None:
        if self.state.world.get_hex_record(destination) is None:
            return
        destination_xy = axial_to_world_xy(destination)
        self.set_entity_target_position(entity_id, destination_xy[0], destination_xy[1])

    def set_entity_target_position(self, entity_id: str, x: float, y: float) -> None:
        if not self._position_is_within_world(x, y):
            return
        self.state.entities[entity_id].target_position = (x, y)

    def set_entity_move_vector(self, entity_id: str, x: float, y: float) -> None:
        move_x, move_y = normalized_vector(x, y)
        entity = self.state.entities[entity_id]
        entity.move_input_x = move_x
        entity.move_input_y = move_y

    def advance_ticks(self, ticks: int) -> None:
        for _ in range(ticks):
            self._tick_once()

    def advance_days(self, days: int) -> None:
        self.advance_ticks(days * TICKS_PER_DAY)

    def rng_state_payload(self) -> dict[str, Any]:
        return {
            "master_seed": self.master_seed,
            "rng_sim_state": self.rng_sim.getstate(),
            "rng_worldgen_state": self.rng_worldgen.getstate(),
        }

    def restore_rng_state(self, payload: dict[str, Any]) -> None:
        self.master_seed = int(payload["master_seed"])
        self.seed = self.master_seed
        self.rng_worldgen = random.Random(derive_stream_seed(master_seed=self.master_seed, stream_name=RNG_WORLDGEN_STREAM_NAME))
        self.rng_sim = random.Random(derive_stream_seed(master_seed=self.master_seed, stream_name=RNG_SIM_STREAM_NAME))
        self.rng_sim.setstate(payload["rng_sim_state"])
        self.rng_worldgen.setstate(payload["rng_worldgen_state"])
        self.rng = self.rng_sim

    def _tick_once(self) -> None:
        for entity_id in sorted(self.state.entities):
            self._advance_entity(self.state.entities[entity_id])
        self.state.tick += 1

    def _advance_entity(self, entity: EntityState) -> None:
        move_x = entity.move_input_x
        move_y = entity.move_input_y
        target = entity.target_position

        if move_x == 0.0 and move_y == 0.0 and target is not None:
            delta_x = target[0] - entity.position_x
            delta_y = target[1] - entity.position_y
            distance_sq = delta_x * delta_x + delta_y * delta_y
            if distance_sq <= TARGET_REACHED_THRESHOLD * TARGET_REACHED_THRESHOLD:
                entity.target_position = None
                return
            distance = distance_sq ** 0.5
            move_x = delta_x / distance
            move_y = delta_y / distance

        if move_x == 0.0 and move_y == 0.0:
            return

        step_size = entity.speed_per_tick
        if target is not None and entity.move_input_x == 0.0 and entity.move_input_y == 0.0:
            delta_x = target[0] - entity.position_x
            delta_y = target[1] - entity.position_y
            distance = (delta_x * delta_x + delta_y * delta_y) ** 0.5
            if distance < step_size:
                step_size = distance

        next_x = entity.position_x + move_x * step_size
        next_y = entity.position_y + move_y * step_size

        if self._position_is_within_world(next_x, next_y):
            entity.position_x = next_x
            entity.position_y = next_y
        elif target is not None and entity.move_input_x == 0.0 and entity.move_input_y == 0.0:
            entity.target_position = None

    def _position_is_within_world(self, x: float, y: float) -> bool:
        return self.state.world.get_hex_record(world_xy_to_axial(x, y)) is not None
