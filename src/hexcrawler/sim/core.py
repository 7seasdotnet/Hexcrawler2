from __future__ import annotations

import random
from dataclasses import dataclass, field

from hexcrawler.sim.movement import axial_to_world_xy, nearest_direction_step
from hexcrawler.sim.world import HexCoord, WorldState

TICKS_PER_DAY = 240


@dataclass
class EntityState:
    entity_id: str
    hex_coord: HexCoord
    offset_x: float = 0.0
    offset_y: float = 0.0
    speed_per_tick: float = 0.15
    destination: HexCoord | None = None

    def world_xy(self) -> tuple[float, float]:
        return axial_to_world_xy(self.hex_coord, self.offset_x, self.offset_y)


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
        self.rng = random.Random(seed)

    def add_entity(self, entity: EntityState) -> None:
        self.state.entities[entity.entity_id] = entity

    def set_entity_destination(self, entity_id: str, destination: HexCoord) -> None:
        self.state.entities[entity_id].destination = destination

    def advance_ticks(self, ticks: int) -> None:
        for _ in range(ticks):
            self._tick_once()

    def advance_days(self, days: int) -> None:
        self.advance_ticks(days * TICKS_PER_DAY)

    def _tick_once(self) -> None:
        for entity_id in sorted(self.state.entities):
            self._advance_entity(self.state.entities[entity_id])
        self.state.tick += 1

    def _advance_entity(self, entity: EntityState) -> None:
        if entity.destination is None:
            return

        destination_xy = axial_to_world_xy(entity.destination)
        current_x, current_y = entity.world_xy()
        delta_x = destination_xy[0] - current_x
        delta_y = destination_xy[1] - current_y
        distance = (delta_x * delta_x + delta_y * delta_y) ** 0.5

        if distance <= entity.speed_per_tick:
            entity.hex_coord = entity.destination
            entity.offset_x = 0.0
            entity.offset_y = 0.0
            return

        step_ratio = entity.speed_per_tick / distance
        next_x = current_x + delta_x * step_ratio
        next_y = current_y + delta_y * step_ratio

        next_hex = nearest_direction_step(entity.hex_coord, entity.destination)
        hex_center_x, hex_center_y = axial_to_world_xy(next_hex)
        if ((next_x - hex_center_x) ** 2 + (next_y - hex_center_y) ** 2) < 0.65**2:
            entity.hex_coord = next_hex
            entity.offset_x = next_x - hex_center_x
            entity.offset_y = next_y - hex_center_y
        else:
            current_center_x, current_center_y = axial_to_world_xy(entity.hex_coord)
            entity.offset_x = next_x - current_center_x
            entity.offset_y = next_y - current_center_y
