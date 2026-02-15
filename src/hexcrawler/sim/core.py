from __future__ import annotations

import copy
import hashlib
import random
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from hexcrawler.sim.movement import axial_to_world_xy, normalized_vector, world_xy_to_axial
from hexcrawler.sim.rng import derive_stream_seed
from hexcrawler.sim.rules import RuleModule
from hexcrawler.sim.world import HexCoord, WorldState

TICKS_PER_DAY = 240
TARGET_REACHED_THRESHOLD = 0.05

RNG_SIM_STREAM_NAME = "rng_sim"
RNG_WORLDGEN_STREAM_NAME = "rng_worldgen"
MAX_EVENT_TRACE = 256


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
class SimEvent:
    tick: int
    event_id: str
    event_type: str
    params: dict[str, Any]
    unknown_fields: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.tick, int) or self.tick < 0:
            raise ValueError("event tick must be a non-negative integer")
        if not isinstance(self.event_id, str) or not self.event_id:
            raise ValueError("event_id must be a non-empty string")
        if not isinstance(self.event_type, str) or not self.event_type:
            raise ValueError("event_type must be a non-empty string")
        if not isinstance(self.params, dict):
            raise ValueError("params must be a dict")
        _validate_json_value(self.params, field_name="params")

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "tick": self.tick,
            "event_id": self.event_id,
            "event_type": self.event_type,
            "params": self.params,
        }
        payload.update(self.unknown_fields)
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SimEvent":
        known_fields = {"tick", "event_id", "event_type", "params"}
        unknown_fields = {key: value for key, value in data.items() if key not in known_fields}
        return cls(
            tick=int(data["tick"]),
            event_id=str(data["event_id"]),
            event_type=str(data["event_type"]),
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
    rules_state: dict[str, dict[str, Any]] = field(default_factory=dict)
    event_trace: list[dict[str, Any]] = field(default_factory=list)

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
        self._rng_streams: dict[str, random.Random] = {
            RNG_WORLDGEN_STREAM_NAME: self.rng_worldgen,
            RNG_SIM_STREAM_NAME: self.rng_sim,
        }
        # Backward compatibility: preserve existing `sim.rng` consumers as simulation stream.
        self.rng = self.rng_sim
        self.rule_modules: list[RuleModule] = []
        self.input_log: list[SimCommand] = []
        self.save_metadata: dict[str, Any] = {}
        self._pending_commands: dict[int, list[SimCommand]] = defaultdict(list)
        self._pending_events_by_tick: dict[int, list[SimEvent]] = defaultdict(list)
        self._event_tick_by_id: dict[str, int] = {}
        self._next_event_counter = 1
        self._event_execution_trace: list[str] = []

    def add_entity(self, entity: EntityState) -> None:
        self.state.entities[entity.entity_id] = entity

    def append_command(self, command: SimCommand | dict[str, Any]) -> None:
        normalized = command if isinstance(command, SimCommand) else SimCommand.from_dict(command)
        self.input_log.append(normalized)
        self._pending_commands[normalized.tick].append(normalized)

    def schedule_event(self, event: SimEvent) -> None:
        if event.event_id in self._event_tick_by_id:
            raise ValueError(f"duplicate event_id: {event.event_id}")
        self._pending_events_by_tick[event.tick].append(event)
        self._event_tick_by_id[event.event_id] = event.tick

    def schedule_event_at(self, tick: int, event_type: str, params: dict[str, Any]) -> str:
        event_id = f"evt-{self._next_event_counter:08d}"
        self._next_event_counter += 1
        event = SimEvent(tick=tick, event_id=event_id, event_type=event_type, params=params)
        self.schedule_event(event)
        return event_id

    def cancel_event(self, event_id: str) -> bool:
        if event_id not in self._event_tick_by_id:
            return False
        tick = self._event_tick_by_id.pop(event_id)
        events = self._pending_events_by_tick[tick]
        self._pending_events_by_tick[tick] = [event for event in events if event.event_id != event_id]
        if not self._pending_events_by_tick[tick]:
            del self._pending_events_by_tick[tick]
        return True

    def pending_events(self) -> list[SimEvent]:
        return [
            event
            for tick in sorted(self._pending_events_by_tick)
            for event in self._pending_events_by_tick[tick]
        ]

    def event_execution_trace(self) -> tuple[str, ...]:
        return tuple(self._event_execution_trace)

    def get_event_trace(self) -> list[dict[str, Any]]:
        return copy.deepcopy(self.state.event_trace)

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
        stream_states = {
            name: stream.getstate()
            for name, stream in sorted(self._rng_streams.items(), key=lambda item: item[0])
        }
        return {
            "master_seed": self.master_seed,
            "rng_sim_state": self.rng_sim.getstate(),
            "rng_worldgen_state": self.rng_worldgen.getstate(),
            "rng_stream_states": stream_states,
        }

    def restore_rng_state(self, payload: dict[str, Any]) -> None:
        self.master_seed = int(payload["master_seed"])
        self.seed = self.master_seed
        self.rng_worldgen = random.Random(derive_stream_seed(master_seed=self.master_seed, stream_name=RNG_WORLDGEN_STREAM_NAME))
        self.rng_sim = random.Random(derive_stream_seed(master_seed=self.master_seed, stream_name=RNG_SIM_STREAM_NAME))
        stream_states = payload.get("rng_stream_states")
        if isinstance(stream_states, dict):
            restored_streams: dict[str, random.Random] = {}
            for name in sorted(stream_states):
                stream = random.Random(
                    derive_stream_seed(master_seed=self.master_seed, stream_name=name)
                )
                stream.setstate(_json_list_to_tuple(stream_states[name]))
                restored_streams[name] = stream
            self._rng_streams = restored_streams
            self.rng_sim = self._rng_streams[RNG_SIM_STREAM_NAME]
            self.rng_worldgen = self._rng_streams[RNG_WORLDGEN_STREAM_NAME]
        else:
            self.rng_sim.setstate(_json_list_to_tuple(payload["rng_sim_state"]))
            self.rng_worldgen.setstate(_json_list_to_tuple(payload["rng_worldgen_state"]))
            self._rng_streams = {
                RNG_WORLDGEN_STREAM_NAME: self.rng_worldgen,
                RNG_SIM_STREAM_NAME: self.rng_sim,
            }
        self.rng = self.rng_sim

    def rng_stream(self, name: str) -> random.Random:
        if name not in self._rng_streams:
            self._rng_streams[name] = random.Random(
                derive_stream_seed(master_seed=self.master_seed, stream_name=name)
            )
        return self._rng_streams[name]

    def get_rule_module(self, module_name: str) -> RuleModule | None:
        for module in self.rule_modules:
            if module.name == module_name:
                return module
        return None

    def register_rule_module(self, module: RuleModule) -> None:
        if any(existing.name == module.name for existing in self.rule_modules):
            raise ValueError(f"duplicate rule module name: {module.name}")
        self.rule_modules.append(module)
        module.on_simulation_start(self)

    def get_rules_state(self, module_name: str) -> dict[str, Any]:
        existing = self.state.rules_state.get(module_name, {})
        return copy.deepcopy(existing)

    def set_rules_state(self, module_name: str, state: dict[str, Any]) -> None:
        if not isinstance(module_name, str) or not module_name:
            raise ValueError("module_name must be a non-empty string")
        if not isinstance(state, dict):
            raise ValueError("rules_state value must be a dict")
        _validate_json_value(state, field_name="rules_state")
        self.state.rules_state[module_name] = copy.deepcopy(state)

    def simulation_payload(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "seed": self.seed,
            "master_seed": self.master_seed,
            "tick": self.state.tick,
            "next_event_counter": self._next_event_counter,
            "rng_state": self.rng_state_payload(),
            "rules_state": dict(sorted(self.state.rules_state.items())),
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
            "pending_events": [event.to_dict() for event in self.pending_events()],
            "event_trace": copy.deepcopy(self.state.event_trace),
        }

    @classmethod
    def from_simulation_payload(cls, payload: dict[str, Any]) -> "Simulation":
        schema_version = int(payload["schema_version"])
        if schema_version != 1:
            raise ValueError(f"unsupported simulation schema_version: {schema_version}")

        sim = cls(world=WorldState.from_dict(payload["world"]), seed=int(payload["seed"]))
        sim.master_seed = int(payload.get("master_seed", payload["seed"]))
        sim.state.tick = int(payload["tick"])
        sim._next_event_counter = int(payload.get("next_event_counter", 1))

        raw_rules_state = payload.get("rules_state", {})
        if not isinstance(raw_rules_state, dict):
            raise ValueError("rules_state must be an object")
        for module_name, module_state in raw_rules_state.items():
            if not isinstance(module_state, dict):
                raise ValueError("rules_state entries must be objects")
            sim.set_rules_state(module_name, module_state)

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

        for row in payload.get("pending_events", []):
            sim.schedule_event(SimEvent.from_dict(row))

        raw_event_trace = payload.get("event_trace", [])
        if not isinstance(raw_event_trace, list):
            raise ValueError("event_trace must be a list")
        sim.state.event_trace = []
        for entry in raw_event_trace:
            if not isinstance(entry, dict):
                raise ValueError("event_trace entries must be objects")
            sim._append_event_trace_entry(entry)

        if "rng_state" in payload:
            sim.restore_rng_state(payload["rng_state"])
        return sim

    def _tick_once(self) -> None:
        for module in self.rule_modules:
            module.on_tick_start(self, self.state.tick)
        self._apply_commands_for_tick(self.state.tick)
        self._execute_events_for_tick(self.state.tick)
        for entity_id in sorted(self.state.entities):
            self._advance_entity(self.state.entities[entity_id])
        for module in self.rule_modules:
            module.on_tick_end(self, self.state.tick)
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

    def _execute_events_for_tick(self, tick: int) -> None:
        if tick not in self._pending_events_by_tick:
            return
        events = self._pending_events_by_tick.pop(tick)
        for event in events:
            self._event_tick_by_id.pop(event.event_id, None)
            self._execute_event(event)
            for module in self.rule_modules:
                module.on_event_executed(self, event)
            self._append_event_trace_entry(
                {
                    "tick": tick,
                    "event_id": self._trace_event_id_as_int(event.event_id),
                    "event_type": event.event_type,
                    "params": copy.deepcopy(event.params),
                    "module_hooks_called": bool(self.rule_modules),
                }
            )

    def _execute_event(self, event: SimEvent) -> None:
        if event.event_type in {"noop", "debug_marker"}:
            self._event_execution_trace.append(event.event_id)

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

    def _append_event_trace_entry(self, entry: dict[str, Any]) -> None:
        if not isinstance(entry, dict):
            raise ValueError("event_trace entries must be objects")
        required = {"tick", "event_id", "event_type", "params"}
        if not required.issubset(entry):
            raise ValueError("event_trace entries missing required fields")
        if not isinstance(entry["tick"], int) or entry["tick"] < 0:
            raise ValueError("event_trace tick must be a non-negative integer")
        if not isinstance(entry["event_id"], int):
            raise ValueError("event_trace event_id must be an integer")
        if not isinstance(entry["event_type"], str) or not entry["event_type"]:
            raise ValueError("event_trace event_type must be a non-empty string")
        if not isinstance(entry["params"], dict):
            raise ValueError("event_trace params must be an object")
        _validate_json_value(entry["params"], field_name="event_trace.params")
        if "module_hooks_called" in entry and not isinstance(entry["module_hooks_called"], bool):
            raise ValueError("event_trace module_hooks_called must be boolean")
        self.state.event_trace.append(copy.deepcopy(entry))
        if len(self.state.event_trace) > MAX_EVENT_TRACE:
            overflow = len(self.state.event_trace) - MAX_EVENT_TRACE
            del self.state.event_trace[:overflow]

    @staticmethod
    def _trace_event_id_as_int(event_id: str) -> int:
        if event_id.startswith("evt-") and event_id[4:].isdigit():
            return int(event_id[4:])
        digest = hashlib.sha256(event_id.encode("utf-8")).hexdigest()
        return int(digest[:16], 16)


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
