from __future__ import annotations

import random
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from hexcrawler.sim.movement import axial_to_world_xy, normalized_vector, world_xy_to_axial
from hexcrawler.sim.rng import derive_stream_seed
from hexcrawler.sim.world import HexCoord, WorldState

TICKS_PER_DAY = 240
TARGET_REACHED_THRESHOLD = 0.05

RNG_SIM_STREAM_NAME = "rng_sim"
RNG_WORLDGEN_STREAM_NAME = "rng_worldgen"


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

def _json_list_to_tuple(value: Any) -> Any:
    if isinstance(value, list):
        return tuple(_json_list_to_tuple(item) for item in value)
    return value


@dataclass
class SimCommand:
    tick: int
    command_type: str
    params: dict[str, Any]
    entity_id: str | None = None
    unknown_fields: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.tick, int) or self.tick < 0:
            raise ValueError("command tick must be a non-negative integer")
        if not isinstance(self.command_type, str) or not self.command_type:
            raise ValueError("command_type must be a non-empty string")
        if self.entity_id is not None and not isinstance(self.entity_id, str):
            raise ValueError("entity_id must be a string or None")
        if not isinstance(self.params, dict):
            raise ValueError("params must be a dict")
        _validate_json_value(self.params, field_name="params")

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "tick": self.tick,
            "entity_id": self.entity_id,
            "command_type": self.command_type,
            "params": self.params,
        }
        payload.update(self.unknown_fields)
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SimCommand":
        known_fields = {"tick", "entity_id", "command_type", "params"}
        unknown_fields = {key: value for key, value in data.items() if key not in known_fields}
        return cls(
            tick=int(data["tick"]),
            entity_id=data.get("entity_id"),
            command_type=str(data["command_type"]),
            params=dict(data.get("params", {})),
            unknown_fields=unknown_fields,
        )


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
        self.input_log: list[SimCommand] = []
        self.save_metadata: dict[str, Any] = {}
        self._pending_commands: dict[int, list[SimCommand]] = defaultdict(list)

    def add_entity(self, entity: EntityState) -> None:
        self.state.entities[entity.entity_id] = entity

    def append_command(self, command: SimCommand | dict[str, Any]) -> None:
        normalized = command if isinstance(command, SimCommand) else SimCommand.from_dict(command)
        self.input_log.append(normalized)
        self._pending_commands[normalized.tick].append(normalized)

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

    def stop_entity(self, entity_id: str) -> None:
        entity = self.state.entities[entity_id]
        entity.move_input_x = 0.0
        entity.move_input_y = 0.0
        entity.target_position = None

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
        self.rng_sim.setstate(_json_list_to_tuple(payload["rng_sim_state"]))
        self.rng_worldgen.setstate(_json_list_to_tuple(payload["rng_worldgen_state"]))
        self.rng = self.rng_sim

    def simulation_payload(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "seed": self.seed,
            "master_seed": self.master_seed,
            "tick": self.state.tick,
            "rng_state": self.rng_state_payload(),
            "world": self.state.world.to_dict(),
            "entities": [
                {
                    "entity_id": entity.entity_id,
                    "position_x": entity.position_x,
                    "position_y": entity.position_y,
                    "speed_per_tick": entity.speed_per_tick,
                    "move_input_x": entity.move_input_x,
                    "move_input_y": entity.move_input_y,
                    "target_position": list(entity.target_position) if entity.target_position else None,
                }
                for entity in sorted(self.state.entities.values(), key=lambda current: current.entity_id)
            ],
            "input_log": [command.to_dict() for command in self.input_log],
        }

    @classmethod
    def from_simulation_payload(cls, payload: dict[str, Any]) -> "Simulation":
        schema_version = int(payload["schema_version"])
        if schema_version != 1:
            raise ValueError(f"unsupported simulation schema_version: {schema_version}")

        sim = cls(world=WorldState.from_dict(payload["world"]), seed=int(payload["seed"]))
        sim.master_seed = int(payload.get("master_seed", payload["seed"]))
        sim.state.tick = int(payload["tick"])

        for row in payload.get("entities", []):
            entity = EntityState(
                entity_id=str(row["entity_id"]),
                position_x=float(row["position_x"]),
                position_y=float(row["position_y"]),
                speed_per_tick=float(row.get("speed_per_tick", 0.15)),
                move_input_x=float(row.get("move_input_x", 0.0)),
                move_input_y=float(row.get("move_input_y", 0.0)),
                target_position=(tuple(row["target_position"]) if row.get("target_position") is not None else None),
            )
            sim.add_entity(entity)

        for row in payload.get("input_log", []):
            sim.append_command(SimCommand.from_dict(row))

        if "rng_state" in payload:
            sim.restore_rng_state(payload["rng_state"])
        return sim

    def _tick_once(self) -> None:
        self._apply_commands_for_tick(self.state.tick)
        for entity_id in sorted(self.state.entities):
            self._advance_entity(self.state.entities[entity_id])
        self.state.tick += 1

    def _apply_commands_for_tick(self, tick: int) -> None:
        for command in self._pending_commands.get(tick, []):
            self._execute_command(command)

    def _execute_command(self, command: SimCommand) -> None:
        entity_id = command.entity_id
        if entity_id is None or entity_id not in self.state.entities:
            return

        if command.command_type == "set_move_vector":
            self.set_entity_move_vector(
                entity_id,
                float(command.params.get("x", 0.0)),
                float(command.params.get("y", 0.0)),
            )
        elif command.command_type == "set_target_position":
            self.set_entity_target_position(
                entity_id,
                float(command.params.get("x", 0.0)),
                float(command.params.get("y", 0.0)),
            )
        elif command.command_type == "stop":
            self.stop_entity(entity_id)

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


def run_replay(
    initial_world_state: WorldState | Simulation,
    command_log: list[SimCommand | dict[str, Any]],
    ticks_to_run: int,
) -> Simulation:
    if isinstance(initial_world_state, Simulation):
        simulation = Simulation.from_simulation_payload(initial_world_state.simulation_payload())
    else:
        simulation = Simulation(world=WorldState.from_dict(initial_world_state.to_dict()), seed=0)
    for command in command_log:
        simulation.append_command(command)
    simulation.advance_ticks(ticks_to_run)
    return simulation
