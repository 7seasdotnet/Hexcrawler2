from __future__ import annotations

import copy
import hashlib
import json
import random
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from hexcrawler.content.items import DEFAULT_ITEMS_PATH, load_items_json
from hexcrawler.content.supplies import DEFAULT_SUPPLY_PROFILES_PATH, load_supply_profiles_json
from hexcrawler.sim.location import LocationRef, OVERWORLD_HEX_TOPOLOGY, SQUARE_GRID_TOPOLOGY
from hexcrawler.sim.movement import (
    axial_to_world_xy,
    normalized_vector,
    square_grid_cell_to_world_xy,
    world_xy_to_axial,
    world_xy_to_square_grid_cell,
)
from hexcrawler.sim.rng import derive_stream_seed
from hexcrawler.sim.rules import RuleModule
from hexcrawler.sim.world import ContainerState, DEFAULT_OVERWORLD_SPACE_ID, HexCoord, WorldState

TICKS_PER_DAY = 240
TARGET_REACHED_THRESHOLD = 0.05
TRAVEL_STEP_EVENT_TYPE = "travel_step"

RNG_SIM_STREAM_NAME = "rng_sim"
RNG_WORLDGEN_STREAM_NAME = "rng_worldgen"
MAX_EVENT_TRACE = 256
MAX_EVENTS_PER_TICK = 10_000
INVENTORY_OUTCOME_EVENT_TYPE = "inventory_outcome"
SITE_ENTER_OUTCOME_EVENT_TYPE = "site_enter_outcome"
INVENTORY_LEDGER_MODULE = "inventory_ledger"
INVENTORY_ALLOWED_REASONS = {"transfer", "drop", "pickup", "consume", "spawn"}
DEFAULT_PLAYER_ENTITY_ID = "scout"
DEFAULT_PLAYER_SUPPLY_PROFILE_ID = "player_default"
HEX_TOPOLOGY_TYPES = {OVERWORLD_HEX_TOPOLOGY, "hex_disk", "hex_rectangle", "hex_axial", "custom"}



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


def _normalize_entity_stats(stats: Any) -> dict[str, Any]:
    if stats is None:
        return {}
    if not isinstance(stats, dict):
        raise ValueError("entity.stats must be an object")
    normalized: dict[str, Any] = {}
    for raw_key, value in stats.items():
        if not isinstance(raw_key, str) or not raw_key:
            raise ValueError("entity.stats keys must be non-empty strings")
        _validate_json_value(value, field_name=f"entity.stats[{raw_key}]")
        normalized[raw_key] = copy.deepcopy(value)
    return dict(sorted(normalized.items()))


def apply_stat_patch(stats: dict[str, Any] | None, patch: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(patch, dict):
        raise ValueError("stat patch must be an object")
    op = patch.get("op")
    key = patch.get("key")
    if op not in {"set", "remove"}:
        raise ValueError("stat patch op must be one of: set, remove")
    if not isinstance(key, str) or not key:
        raise ValueError("stat patch key must be a non-empty string")

    normalized = _normalize_entity_stats(stats)
    updated = copy.deepcopy(normalized)
    if op == "remove":
        updated.pop(key, None)
        return dict(sorted(updated.items()))

    if "value" not in patch:
        raise ValueError("stat patch set operation requires value")
    _validate_json_value(patch["value"], field_name=f"entity.stats[{key}]")
    updated[key] = copy.deepcopy(patch["value"])
    return dict(sorted(updated.items()))


@dataclass
class SimulationTimeState:
    ticks_per_day: int = TICKS_PER_DAY
    epoch_tick: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.ticks_per_day, int) or self.ticks_per_day <= 0:
            raise ValueError("time.ticks_per_day must be an integer > 0")
        if not isinstance(self.epoch_tick, int):
            raise ValueError("time.epoch_tick must be an integer")

    def to_dict(self) -> dict[str, int]:
        return {
            "ticks_per_day": self.ticks_per_day,
            "epoch_tick": self.epoch_tick,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "SimulationTimeState":
        if payload is None:
            return cls()
        if not isinstance(payload, dict):
            raise ValueError("simulation_state.time must be an object")
        return cls(
            ticks_per_day=int(payload.get("ticks_per_day", TICKS_PER_DAY)),
            epoch_tick=int(payload.get("epoch_tick", 0)),
        )


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
    template_id: str | None = None
    source_action_uid: str | None = None
    space_id: str = DEFAULT_OVERWORLD_SPACE_ID
    selected_entity_id: str | None = None
    inventory_container_id: str | None = None
    supply_profile_id: str | None = None
    stats: dict[str, Any] = field(default_factory=dict)

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
    selected_entity_id: str | None = None
    time: SimulationTimeState = field(default_factory=SimulationTimeState)

    @property
    def day(self) -> int:
        return (self.tick - self.time.epoch_tick) // self.time.ticks_per_day


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
        self._supply_profiles = load_supply_profiles_json(DEFAULT_SUPPLY_PROFILES_PATH)

    def add_entity(self, entity: EntityState) -> None:
        entity.stats = _normalize_entity_stats(entity.stats)
        if entity.supply_profile_id is None and entity.entity_id == DEFAULT_PLAYER_ENTITY_ID:
            if DEFAULT_PLAYER_SUPPLY_PROFILE_ID in self._supply_profiles.by_id():
                entity.supply_profile_id = DEFAULT_PLAYER_SUPPLY_PROFILE_ID
        if entity.inventory_container_id is None:
            entity.inventory_container_id = f"inventory:{entity.entity_id}"
            if entity.inventory_container_id not in self.state.world.containers:
                self.state.world.containers[entity.inventory_container_id] = ContainerState(
                    container_id=entity.inventory_container_id,
                    owner_entity_id=entity.entity_id,
                    items={},
                )
        elif entity.inventory_container_id not in self.state.world.containers:
            raise ValueError(
                f"entity '{entity.entity_id}' references missing inventory container '{entity.inventory_container_id}'"
            )
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
        entity = self.state.entities[entity_id]
        if entity.space_id != DEFAULT_OVERWORLD_SPACE_ID:
            return
        if self.state.world.get_hex_record(destination) is None:
            return
        destination_xy = axial_to_world_xy(destination)
        self.set_entity_target_position(entity_id, destination_xy[0], destination_xy[1])

    def set_entity_target_position(self, entity_id: str, x: float, y: float) -> None:
        entity = self.state.entities[entity_id]
        if not self._position_is_within_world(x, y, space_id=entity.space_id):
            return
        entity.target_position = (x, y)

    def set_entity_move_vector(self, entity_id: str, x: float, y: float) -> None:
        move_x, move_y = normalized_vector(x, y)
        entity = self.state.entities[entity_id]
        entity.move_input_x = move_x
        entity.move_input_y = move_y

    def get_entity_stats(self, entity_id: str) -> dict[str, Any]:
        entity = self.state.entities[entity_id]
        return copy.deepcopy(entity.stats)

    def get_entity_stat(self, entity_id: str, key: str, default: Any = None) -> Any:
        if not isinstance(key, str) or not key:
            raise ValueError("entity stat key must be a non-empty string")
        entity = self.state.entities[entity_id]
        return copy.deepcopy(entity.stats.get(key, default))

    def apply_stat_patch(self, stats: dict[str, Any] | None, patch: dict[str, Any]) -> dict[str, Any]:
        return apply_stat_patch(stats=stats, patch=patch)

    def stop_entity(self, entity_id: str) -> None:
        entity = self.state.entities[entity_id]
        entity.move_input_x = 0.0
        entity.move_input_y = 0.0
        entity.target_position = None

    def set_selected_entity(self, selected_entity_id: str | None, *, owner_entity_id: str | None = None) -> None:
        normalized = None if selected_entity_id is None else str(selected_entity_id)
        if owner_entity_id is not None and owner_entity_id in self.state.entities:
            self.state.entities[owner_entity_id].selected_entity_id = normalized
            return
        self.state.selected_entity_id = normalized

    def clear_selected_entity(self, *, owner_entity_id: str | None = None) -> None:
        self.set_selected_entity(None, owner_entity_id=owner_entity_id)

    def selected_entity_id(self, *, owner_entity_id: str | None = None) -> str | None:
        if owner_entity_id is not None and owner_entity_id in self.state.entities:
            return self.state.entities[owner_entity_id].selected_entity_id
        return self.state.selected_entity_id

    def advance_ticks(self, ticks: int) -> None:
        for _ in range(ticks):
            self._tick_once()

    def advance_days(self, days: int) -> None:
        self.advance_ticks(days * self.get_ticks_per_day())

    def get_ticks_per_day(self) -> int:
        return self.state.time.ticks_per_day

    def get_day_index(self) -> int:
        return (self.state.tick - self.state.time.epoch_tick) // self.state.time.ticks_per_day

    def get_tick_in_day(self) -> int:
        return (self.state.tick - self.state.time.epoch_tick) % self.state.time.ticks_per_day

    def get_time_of_day_fraction(self) -> float:
        return self.get_tick_in_day() / self.state.time.ticks_per_day

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
            "time": self.state.time.to_dict(),
            "next_event_counter": self._next_event_counter,
            "rng_state": self.rng_state_payload(),
            "rules_state": dict(sorted(self.state.rules_state.items())),
            "world": self.state.world.to_dict(),
            "entities": [
                {
                    "entity_id": entity.entity_id,
                    "space_id": entity.space_id,
                    "position_x": entity.position_x,
                    "position_y": entity.position_y,
                    "speed_per_tick": entity.speed_per_tick,
                    "move_input_x": entity.move_input_x,
                    "move_input_y": entity.move_input_y,
                    "target_position": list(entity.target_position) if entity.target_position else None,
                    "template_id": entity.template_id,
                    "source_action_uid": entity.source_action_uid,
                    "selected_entity_id": entity.selected_entity_id,
                    "inventory_container_id": entity.inventory_container_id,
                    "supply_profile_id": entity.supply_profile_id,
                    "stats": copy.deepcopy(entity.stats),
                }
                for entity in sorted(self.state.entities.values(), key=lambda current: current.entity_id)
            ],
            "input_log": [command.to_dict() for command in self.input_log],
            "pending_events": [event.to_dict() for event in self.pending_events()],
            "event_trace": copy.deepcopy(self.state.event_trace),
            "selected_entity_id": self.state.selected_entity_id,
        }

    @classmethod
    def from_simulation_payload(cls, payload: dict[str, Any]) -> "Simulation":
        schema_version = int(payload["schema_version"])
        if schema_version != 1:
            raise ValueError(f"unsupported simulation schema_version: {schema_version}")

        sim = cls(world=WorldState.from_dict(payload["world"]), seed=int(payload["seed"]))
        sim.master_seed = int(payload.get("master_seed", payload["seed"]))
        sim.state.tick = int(payload["tick"])
        sim.state.time = SimulationTimeState.from_dict(payload.get("time"))
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
                space_id=str(row.get("space_id", DEFAULT_OVERWORLD_SPACE_ID)),
                position_x=float(row["position_x"]),
                position_y=float(row["position_y"]),
                speed_per_tick=float(row.get("speed_per_tick", 0.15)),
                move_input_x=float(row.get("move_input_x", 0.0)),
                move_input_y=float(row.get("move_input_y", 0.0)),
                target_position=(tuple(row["target_position"]) if row.get("target_position") is not None else None),
                template_id=(str(row["template_id"]) if row.get("template_id") is not None else None),
                source_action_uid=(
                    str(row["source_action_uid"]) if row.get("source_action_uid") is not None else None
                ),
                selected_entity_id=(
                    str(row["selected_entity_id"]) if row.get("selected_entity_id") is not None else None
                ),
                inventory_container_id=(
                    str(row["inventory_container_id"]) if row.get("inventory_container_id") is not None else None
                ),
                supply_profile_id=(str(row["supply_profile_id"]) if row.get("supply_profile_id") is not None else None),
                stats=_normalize_entity_stats(row.get("stats", {})),
            )
            sim.add_entity(entity)

        if payload.get("selected_entity_id") is not None:
            sim.state.selected_entity_id = str(payload["selected_entity_id"])

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
        for command_index, command in enumerate(self._pending_commands.get(tick, [])):
            self._execute_command(command, command_index=command_index)

    def _execute_command(self, command: SimCommand, *, command_index: int) -> None:
        if command.command_type == "set_selected_entity":
            selected_entity_id = command.params.get("selected_entity_id")
            if selected_entity_id is not None and selected_entity_id not in self.state.entities:
                return
            self.set_selected_entity(selected_entity_id, owner_entity_id=command.entity_id)
            return
        if command.command_type == "clear_selected_entity":
            self.clear_selected_entity(owner_entity_id=command.entity_id)
            return
        if command.command_type == "inventory_intent":
            self._execute_inventory_intent(command, command_index=command_index)
            return

        for module in self.rule_modules:
            if module.on_command(self, command, command_index):
                return

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
        elif command.command_type == "transition_space":
            to_location_payload = command.params.get("to_location")
            if not isinstance(to_location_payload, dict):
                return
            to_location = LocationRef.from_dict(to_location_payload)
            self._execute_transition_command(entity_id=entity_id, tick=command.tick, command=command, to_location=to_location)
        elif command.command_type == "enter_site":
            self._execute_enter_site_command(entity_id=entity_id, tick=command.tick, command=command)

    def _append_site_enter_outcome(
        self,
        *,
        tick: int,
        entity_id: str,
        site_id: str,
        outcome: str,
        target_space_id: str | None,
    ) -> None:
        self._append_event_trace_entry(
            {
                "tick": tick,
                "event_id": self._trace_event_id_as_int(f"site-enter:{tick}:{entity_id}:{site_id}:{outcome}"),
                "event_type": SITE_ENTER_OUTCOME_EVENT_TYPE,
                "params": {
                    "tick": tick,
                    "entity_id": entity_id,
                    "site_id": site_id,
                    "target_space_id": target_space_id,
                    "outcome": outcome,
                },
                "module_hooks_called": False,
            }
        )

    def _execute_enter_site_command(self, *, entity_id: str, tick: int, command: SimCommand) -> None:
        site_id = str(command.params.get("site_id", ""))
        site = self.state.world.sites.get(site_id)
        if site is None:
            self._append_site_enter_outcome(
                tick=tick,
                entity_id=entity_id,
                site_id=site_id,
                target_space_id=None,
                outcome="unknown_site",
            )
            return

        entrance = site.entrance
        if not isinstance(entrance, dict):
            self._append_site_enter_outcome(
                tick=tick,
                entity_id=entity_id,
                site_id=site_id,
                target_space_id=None,
                outcome="no_entrance",
            )
            return

        target_space_id = str(entrance.get("target_space_id", ""))
        if target_space_id not in self.state.world.spaces:
            self._append_site_enter_outcome(
                tick=tick,
                entity_id=entity_id,
                site_id=site_id,
                target_space_id=target_space_id,
                outcome="unknown_target_space",
            )
            return

        target_space = self.state.world.spaces[target_space_id]
        spawn = entrance.get("spawn") if isinstance(entrance.get("spawn"), dict) else None
        target_coord = spawn if spawn is not None else target_space.default_spawn_coord()

        transition_command = SimCommand(
            tick=tick,
            entity_id=entity_id,
            command_type="transition_space",
            params={
                "to_location": {
                    "space_id": target_space_id,
                    "topology_type": target_space.topology_type,
                    "coord": target_coord,
                },
                "reason": "enter_site",
                "site_id": site_id,
            },
        )
        self._execute_transition_command(
            entity_id=entity_id,
            tick=tick,
            command=transition_command,
            to_location=LocationRef.from_dict(transition_command.params["to_location"]),
        )
        self._append_site_enter_outcome(
            tick=tick,
            entity_id=entity_id,
            site_id=site_id,
            target_space_id=target_space_id,
            outcome="applied",
        )

    def _inventory_action_uid(self, *, tick: int, command_index: int, explicit_uid: str | None = None) -> str:
        if explicit_uid is not None and explicit_uid:
            return explicit_uid
        return f"{tick}:{command_index}"

    def _inventory_registry_item_ids(self) -> set[str]:
        return set(load_items_json(DEFAULT_ITEMS_PATH).by_id().keys())

    def _inventory_ledger_state(self) -> dict[str, Any]:
        state = self.get_rules_state(INVENTORY_LEDGER_MODULE)
        applied = state.get("applied_action_uids", [])
        if not isinstance(applied, list):
            raise ValueError("inventory_ledger.applied_action_uids must be a list")
        normalized = sorted({str(uid) for uid in applied})
        state["applied_action_uids"] = normalized
        return state

    def _set_inventory_ledger_state(self, state: dict[str, Any]) -> None:
        applied = state.get("applied_action_uids", [])
        state["applied_action_uids"] = sorted({str(uid) for uid in applied})
        self.set_rules_state(INVENTORY_LEDGER_MODULE, state)

    def _append_inventory_outcome(
        self,
        *,
        tick: int,
        action_uid: str,
        outcome: str,
        details: dict[str, Any],
    ) -> None:
        self._append_event_trace_entry(
            {
                "tick": tick,
                "event_id": self._trace_event_id_as_int(f"inventory:{action_uid}:{outcome}"),
                "event_type": INVENTORY_OUTCOME_EVENT_TYPE,
                "params": {
                    "tick": tick,
                    "action_uid": action_uid,
                    "outcome": outcome,
                    "details": details,
                },
                "module_hooks_called": False,
            }
        )

    def _apply_inventory_delta(self, *, container_id: str, item_id: str, delta: int) -> bool:
        container = self.state.world.containers[container_id]
        before = int(container.items.get(item_id, 0))
        after = before + delta
        if after < 0:
            return False
        if after == 0:
            container.items.pop(item_id, None)
        else:
            container.items[item_id] = after
        return True

    def _resolve_drop_container_id(self, *, command: SimCommand) -> str | None:
        if command.entity_id is None or command.entity_id not in self.state.entities:
            return None
        entity = self.state.entities[command.entity_id]
        location = self._entity_location_ref(entity)
        if location.topology_type == OVERWORLD_HEX_TOPOLOGY:
            q = int(location.coord["q"])
            r = int(location.coord["r"])
            return f"world_drop:{entity.space_id}:{q}:{r}"
        coord_parts = ":".join(f"{key}={location.coord[key]}" for key in sorted(location.coord))
        return f"world_drop:{entity.space_id}:{location.topology_type}:{coord_parts}"

    def _execute_inventory_intent(self, command: SimCommand, *, command_index: int) -> None:
        explicit_uid_raw = command.params.get("action_uid")
        explicit_uid = str(explicit_uid_raw) if isinstance(explicit_uid_raw, str) and explicit_uid_raw else None
        action_uid = self._inventory_action_uid(tick=command.tick, command_index=command_index, explicit_uid=explicit_uid)
        ledger_state = self._inventory_ledger_state()
        applied_action_uids = set(ledger_state.get("applied_action_uids", []))

        reason = str(command.params.get("reason", ""))
        item_id = str(command.params.get("item_id", ""))
        quantity_raw = command.params.get("quantity")
        src_container_id = command.params.get("src_container_id")
        dst_container_id = command.params.get("dst_container_id")

        details: dict[str, Any] = {
            "reason": reason,
            "item_id": item_id,
            "src_container_id": src_container_id,
            "dst_container_id": dst_container_id,
            "quantity": quantity_raw,
        }

        if action_uid in applied_action_uids:
            self._append_inventory_outcome(
                tick=command.tick,
                action_uid=action_uid,
                outcome="already_applied",
                details=details,
            )
            return

        if reason not in INVENTORY_ALLOWED_REASONS:
            self._append_inventory_outcome(
                tick=command.tick,
                action_uid=action_uid,
                outcome="unsupported_reason",
                details=details,
            )
            return

        if not isinstance(quantity_raw, int) or quantity_raw <= 0:
            self._append_inventory_outcome(
                tick=command.tick,
                action_uid=action_uid,
                outcome="invalid_quantity",
                details=details,
            )
            return
        quantity = int(quantity_raw)

        if item_id not in self._inventory_registry_item_ids():
            self._append_inventory_outcome(
                tick=command.tick,
                action_uid=action_uid,
                outcome="unknown_item",
                details=details,
            )
            return

        if reason == "drop" and dst_container_id is None:
            dst_container_id = self._resolve_drop_container_id(command=command)
            details["dst_container_id"] = dst_container_id
            if dst_container_id is not None and dst_container_id not in self.state.world.containers:
                location = None
                if command.entity_id is not None and command.entity_id in self.state.entities:
                    entity = self.state.entities[command.entity_id]
                    location = self._entity_location_ref(entity).to_dict()
                self.state.world.containers[dst_container_id] = ContainerState(
                    container_id=dst_container_id,
                    location=location,
                    items={},
                )

        container_ids_to_check = []
        if reason in {"transfer", "drop", "pickup", "consume"}:
            container_ids_to_check.append(src_container_id)
        if reason in {"transfer", "drop", "pickup", "spawn"}:
            container_ids_to_check.append(dst_container_id)
        for container_id in container_ids_to_check:
            if container_id is None or container_id not in self.state.world.containers:
                self._append_inventory_outcome(
                    tick=command.tick,
                    action_uid=action_uid,
                    outcome="unknown_container",
                    details=details,
                )
                return

        if reason in {"transfer", "drop", "pickup", "consume"}:
            if not self._apply_inventory_delta(
                container_id=str(src_container_id),
                item_id=item_id,
                delta=-quantity,
            ):
                self._append_inventory_outcome(
                    tick=command.tick,
                    action_uid=action_uid,
                    outcome="insufficient_quantity",
                    details=details,
                )
                return

        if reason in {"transfer", "drop", "pickup", "spawn"}:
            self._apply_inventory_delta(
                container_id=str(dst_container_id),
                item_id=item_id,
                delta=quantity,
            )

        applied_action_uids.add(action_uid)
        ledger_state["applied_action_uids"] = sorted(applied_action_uids)
        self._set_inventory_ledger_state(ledger_state)

        self._append_inventory_outcome(
            tick=command.tick,
            action_uid=action_uid,
            outcome="applied",
            details=details,
        )

    def _execute_transition_command(
        self,
        *,
        entity_id: str,
        tick: int,
        command: SimCommand,
        to_location: LocationRef,
    ) -> None:
        entity = self.state.entities[entity_id]
        from_location = self._entity_location_ref(entity)
        transition_uid = self._transition_uid(entity_id=entity_id, tick=tick, command=command, to_location=to_location)

        status = "applied"
        target_space = self.state.world.spaces.get(to_location.space_id)
        if target_space is None:
            status = "rejected_unknown_space"
        else:
            if not self._topology_compatible(space_topology=target_space.topology_type, location_topology=to_location.topology_type):
                status = "rejected_topology_mismatch"
            elif not target_space.is_valid_cell(to_location.coord):
                status = "rejected_invalid_coord"
            else:
                next_x, next_y = self._coord_to_world_xy(space=target_space, coord=to_location.coord)
                entity.position_x = next_x
                entity.position_y = next_y
                entity.space_id = to_location.space_id
                entity.target_position = None
                entity.move_input_x = 0.0
                entity.move_input_y = 0.0

        self._append_event_trace_entry(
            {
                "tick": tick,
                "event_id": self._trace_event_id_as_int(f"space-transition:{transition_uid}"),
                "event_type": "space_transition",
                "params": {
                    "entity_id": entity_id,
                    "from_location": from_location.to_dict(),
                    "to_location": to_location.to_dict(),
                    "transition_uid": transition_uid,
                    "status": status,
                    "reason": command.params.get("reason"),
                    "site_id": command.params.get("site_id"),
                },
                "module_hooks_called": False,
            }
        )

    @staticmethod
    def _transition_uid(*, entity_id: str, tick: int, command: SimCommand, to_location: LocationRef) -> str:
        payload = {
            "entity_id": entity_id,
            "tick": tick,
            "command_type": command.command_type,
            "to_location": to_location.to_dict(),
            "reason": command.params.get("reason"),
            "site_id": command.params.get("site_id"),
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        digest = hashlib.sha256(encoded).hexdigest()
        return f"transition-{digest[:16]}"

    def _execute_events_for_tick(self, tick: int) -> None:
        executed_count = 0
        while True:
            events = self._pending_events_by_tick.pop(tick, None)
            if not events:
                return
            for event in events:
                executed_count += 1
                if executed_count > MAX_EVENTS_PER_TICK:
                    raise RuntimeError(
                        f"event execution guard tripped at tick {tick}; exceeded MAX_EVENTS_PER_TICK={MAX_EVENTS_PER_TICK}"
                    )
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
        prior_location = self._entity_location_ref(entity)
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

        if self._position_is_within_world(next_x, next_y, space_id=entity.space_id):
            entity.position_x = next_x
            entity.position_y = next_y
            next_location = self._entity_location_ref(entity)
            if next_location.coord != prior_location.coord or next_location.space_id != prior_location.space_id:
                self.schedule_event_at(
                    tick=self.state.tick + 1,
                    event_type=TRAVEL_STEP_EVENT_TYPE,
                    params={
                        "tick": self.state.tick,
                        "entity_id": entity.entity_id,
                        "location_from": prior_location.to_dict(),
                        "location_to": next_location.to_dict(),
                    },
                )
        elif target is not None and entity.move_input_x == 0.0 and entity.move_input_y == 0.0:
            entity.target_position = None

    def _position_is_within_world(self, x: float, y: float, *, space_id: str = DEFAULT_OVERWORLD_SPACE_ID) -> bool:
        space = self.state.world.spaces.get(space_id)
        if space is None:
            return False
        if space.topology_type in HEX_TOPOLOGY_TYPES:
            return space.is_valid_cell(world_xy_to_axial(x, y).to_dict())
        if space.topology_type == SQUARE_GRID_TOPOLOGY:
            return space.is_valid_cell(world_xy_to_square_grid_cell(x, y))
        return False

    def _entity_location_ref(self, entity: EntityState) -> LocationRef:
        space = self.state.world.spaces.get(entity.space_id)
        if space is None:
            return LocationRef.from_overworld_hex(entity.hex_coord)
        if space.topology_type == SQUARE_GRID_TOPOLOGY:
            return LocationRef(
                space_id=entity.space_id,
                topology_type=SQUARE_GRID_TOPOLOGY,
                coord=world_xy_to_square_grid_cell(entity.position_x, entity.position_y),
            )
        return LocationRef(
            space_id=entity.space_id,
            topology_type=OVERWORLD_HEX_TOPOLOGY,
            coord=entity.hex_coord.to_dict(),
        )

    @staticmethod
    def _coord_to_world_xy(*, space: Any, coord: dict[str, Any]) -> tuple[float, float]:
        if space.topology_type == SQUARE_GRID_TOPOLOGY:
            return square_grid_cell_to_world_xy(int(coord["x"]), int(coord["y"]))
        target_coord = HexCoord.from_dict(coord)
        return axial_to_world_xy(target_coord)

    @staticmethod
    def _topology_compatible(*, space_topology: str, location_topology: str) -> bool:
        if space_topology == location_topology:
            return True
        return space_topology in HEX_TOPOLOGY_TYPES and location_topology == OVERWORLD_HEX_TOPOLOGY

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
