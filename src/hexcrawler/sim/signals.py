from __future__ import annotations

import copy
import heapq
from dataclasses import dataclass
from typing import Any

from hexcrawler.sim.core import SimCommand, SimEvent, Simulation
from hexcrawler.sim.location import LocationRef, OVERWORLD_HEX_TOPOLOGY, SQUARE_GRID_TOPOLOGY
from hexcrawler.sim.rules import RuleModule
from hexcrawler.sim.world import HexCoord, WorldState

EMIT_SIGNAL_INTENT_COMMAND_TYPE = "emit_signal_intent"
PERCEIVE_SIGNAL_INTENT_COMMAND_TYPE = "perceive_signal_intent"
SIGNAL_EMIT_EXECUTE_EVENT_TYPE = "signal_emit_execute"
SIGNAL_PERCEIVE_EXECUTE_EVENT_TYPE = "perceive_signal_execute"
SIGNAL_EMIT_OUTCOME_EVENT_TYPE = "signal_emit_outcome"
SIGNAL_PERCEIVE_OUTCOME_EVENT_TYPE = "signal_perception_outcome"
MAX_SENSITIVITY = 100
SENSITIVITY_BONUS_DIVISOR = 10
MAX_EXECUTED_ACTION_UIDS = 2048


@dataclass(frozen=True)
class SignalRecord:
    signal_id: str
    tick_emitted: int
    space_id: str
    origin: LocationRef
    channel: str
    base_intensity: int
    falloff_model: str
    max_radius: int
    ttl_ticks: int
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "signal_id": self.signal_id,
            "tick_emitted": self.tick_emitted,
            "space_id": self.space_id,
            "origin": self.origin.to_dict(),
            "channel": self.channel,
            "base_intensity": self.base_intensity,
            "falloff_model": self.falloff_model,
            "max_radius": self.max_radius,
            "ttl_ticks": self.ttl_ticks,
            "metadata": copy.deepcopy(self.metadata),
        }


def distance_between_locations(a: LocationRef, b: LocationRef) -> int | None:
    if a.space_id != b.space_id:
        return None
    if a.topology_type != b.topology_type:
        return None

    if a.topology_type == OVERWORLD_HEX_TOPOLOGY:
        try:
            hex_a = HexCoord.from_dict(a.coord)
            hex_b = HexCoord.from_dict(b.coord)
        except (KeyError, TypeError, ValueError):
            return None
        dq = hex_a.q - hex_b.q
        dr = hex_a.r - hex_b.r
        ds = (hex_a.q + hex_a.r) - (hex_b.q + hex_b.r)
        return int((abs(dq) + abs(dr) + abs(ds)) / 2)

    if a.topology_type == SQUARE_GRID_TOPOLOGY:
        try:
            ax = int(a.coord["x"])
            ay = int(a.coord["y"])
            bx = int(b.coord["x"])
            by = int(b.coord["y"])
        except (KeyError, TypeError, ValueError):
            return None
        return abs(ax - bx) + abs(ay - by)

    return None


def _coord_key(topology_type: str, coord: dict[str, Any]) -> tuple[int, int] | None:
    try:
        if topology_type == OVERWORLD_HEX_TOPOLOGY:
            return (int(coord["q"]), int(coord["r"]))
        if topology_type == SQUARE_GRID_TOPOLOGY:
            return (int(coord["x"]), int(coord["y"]))
    except (KeyError, TypeError, ValueError):
        return None
    return None


def _coord_from_key(topology_type: str, key: tuple[int, int]) -> dict[str, int]:
    if topology_type == OVERWORLD_HEX_TOPOLOGY:
        return {"q": int(key[0]), "r": int(key[1])}
    return {"x": int(key[0]), "y": int(key[1])}


def _neighbor_keys(topology_type: str, key: tuple[int, int]) -> list[tuple[int, int]]:
    a, b = key
    if topology_type == OVERWORLD_HEX_TOPOLOGY:
        return [
            (a + 1, b),
            (a + 1, b - 1),
            (a, b - 1),
            (a - 1, b),
            (a - 1, b + 1),
            (a, b + 1),
        ]
    if topology_type == SQUARE_GRID_TOPOLOGY:
        return [
            (a + 1, b),
            (a - 1, b),
            (a, b + 1),
            (a, b - 1),
        ]
    return []


def compute_signal_path_metrics(
    signal: SignalRecord,
    listener: LocationRef,
    *,
    world: WorldState,
    max_steps: int,
) -> dict[str, int] | None:
    if max_steps < 0:
        return None
    if signal.origin.space_id != listener.space_id or signal.origin.topology_type != listener.topology_type:
        return None

    topology_type = signal.origin.topology_type
    origin_key = _coord_key(topology_type, signal.origin.coord)
    listener_key = _coord_key(topology_type, listener.coord)
    if origin_key is None or listener_key is None:
        return None

    queue: list[tuple[int, int, tuple[int, int]]] = [(0, 0, origin_key)]
    best: dict[tuple[int, int], int] = {origin_key: 0}

    while queue:
        total_cost, step_count, current = heapq.heappop(queue)
        if total_cost != best.get(current):
            continue
        if current == listener_key:
            return {
                "occlusion_cost": int(total_cost - step_count),
                "step_count": int(step_count),
                "effective_path_cost": int(total_cost),
            }
        if step_count >= max_steps:
            continue

        current_coord = _coord_from_key(topology_type, current)
        for neighbor in _neighbor_keys(topology_type, current):
            next_step_count = step_count + 1
            if next_step_count > max_steps:
                continue
            neighbor_coord = _coord_from_key(topology_type, neighbor)
            occlusion = world.get_structure_occlusion_value(
                space_id=signal.space_id,
                cell_a=current_coord,
                cell_b=neighbor_coord,
            )
            next_total = next_step_count + occlusion + (total_cost - step_count)
            best_total = best.get(neighbor)
            if best_total is not None and next_total >= best_total:
                continue
            best[neighbor] = next_total
            heapq.heappush(queue, (next_total, next_step_count, neighbor))
    return None


def compute_signal_strength(
    signal: SignalRecord,
    listener: LocationRef,
    current_tick: int,
    *,
    world: WorldState | None = None,
) -> int:
    expires_tick = signal.tick_emitted + signal.ttl_ticks
    if current_tick > expires_tick:
        return 0

    if signal.falloff_model != "linear":
        return 0

    if world is not None:
        metrics = compute_signal_path_metrics(signal, listener, world=world, max_steps=signal.max_radius)
        if metrics is None:
            return 0
        return max(0, signal.base_intensity - int(metrics["effective_path_cost"]))

    distance = distance_between_locations(signal.origin, listener)
    if distance is None or distance > signal.max_radius:
        return 0
    return max(0, signal.base_intensity - distance)


def parse_numeric_stat(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


class SignalPropagationModule(RuleModule):
    name = "signal_propagation"

    _ALLOWED_CHANNELS = {"sound"}

    def _resolve_sensitivity(self, sim: Simulation, entity_id: str, channel: str) -> tuple[int, str, int]:
        entity = sim.state.entities[entity_id]
        stats = entity.stats if isinstance(entity.stats, dict) else {}

        source = "default"
        raw_value: Any = None
        if channel == "sound" and "hearing" in stats:
            source = "hearing"
            raw_value = stats.get("hearing")
        elif "perception" in stats:
            source = "perception"
            raw_value = stats.get("perception")

        numeric = parse_numeric_stat(raw_value)
        if numeric is None:
            sensitivity = 0
        else:
            sensitivity = max(0, min(MAX_SENSITIVITY, int(numeric)))
        bonus = sensitivity // SENSITIVITY_BONUS_DIVISOR
        return sensitivity, source, bonus

    def on_command(self, sim: Simulation, command: SimCommand, command_index: int) -> bool:
        if command.command_type == EMIT_SIGNAL_INTENT_COMMAND_TYPE:
            self._handle_emit_command(sim, command, command_index=command_index)
            return True
        if command.command_type == PERCEIVE_SIGNAL_INTENT_COMMAND_TYPE:
            self._handle_perceive_command(sim, command, command_index=command_index)
            return True
        return False

    def on_event_executed(self, sim: Simulation, event: SimEvent) -> None:
        if event.event_type == SIGNAL_EMIT_EXECUTE_EVENT_TYPE:
            self._handle_emit_execute(sim, event)
            return
        if event.event_type == SIGNAL_PERCEIVE_EXECUTE_EVENT_TYPE:
            self._handle_perceive_execute(sim, event)

    def _handle_emit_command(self, sim: Simulation, command: SimCommand, *, command_index: int) -> None:
        action_uid = f"{command.tick}:{command_index}"
        channel = command.params.get("channel")
        base_intensity = command.params.get("base_intensity")
        max_radius = command.params.get("max_radius")
        ttl_ticks = command.params.get("ttl_ticks")
        duration_ticks = command.params.get("duration_ticks")

        if not isinstance(channel, str) or channel not in self._ALLOWED_CHANNELS:
            self._schedule_emit_outcome(sim, tick=command.tick, action_uid=action_uid, entity_id=command.entity_id, channel=channel, outcome="invalid_params")
            return
        if not self._is_non_negative_int(base_intensity, max_radius, ttl_ticks, duration_ticks):
            self._schedule_emit_outcome(sim, tick=command.tick, action_uid=action_uid, entity_id=command.entity_id, channel=channel, outcome="invalid_params")
            return
        if command.entity_id is None or command.entity_id not in sim.state.entities:
            self._schedule_emit_outcome(sim, tick=command.tick, action_uid=action_uid, entity_id=command.entity_id, channel=channel, outcome="unknown_entity")
            return

        origin = self._entity_location(sim, command.entity_id)
        sim.schedule_event_at(
            tick=command.tick + int(duration_ticks),
            event_type=SIGNAL_EMIT_EXECUTE_EVENT_TYPE,
            params={
                "action_uid": action_uid,
                "entity_id": command.entity_id,
                "channel": channel,
                "base_intensity": int(base_intensity),
                "max_radius": int(max_radius),
                "ttl_ticks": int(ttl_ticks),
                "origin": origin.to_dict(),
                "metadata": copy.deepcopy(command.params.get("metadata", {})),
                "falloff_model": "linear",
            },
        )

    def _handle_perceive_command(self, sim: Simulation, command: SimCommand, *, command_index: int) -> None:
        action_uid = f"{command.tick}:{command_index}"
        channel = command.params.get("channel")
        radius = command.params.get("radius")
        duration_ticks = command.params.get("duration_ticks")

        if not isinstance(channel, str) or channel not in self._ALLOWED_CHANNELS:
            self._schedule_perceive_outcome(sim, tick=command.tick, action_uid=action_uid, entity_id=command.entity_id, channel=channel, radius=radius, outcome="invalid_params", hits=[])
            return
        if not self._is_non_negative_int(radius, duration_ticks):
            self._schedule_perceive_outcome(sim, tick=command.tick, action_uid=action_uid, entity_id=command.entity_id, channel=channel, radius=radius, outcome="invalid_params", hits=[])
            return
        if command.entity_id is None or command.entity_id not in sim.state.entities:
            self._schedule_perceive_outcome(sim, tick=command.tick, action_uid=action_uid, entity_id=command.entity_id, channel=channel, radius=radius, outcome="unknown_entity", hits=[])
            return

        sim.schedule_event_at(
            tick=command.tick + int(duration_ticks),
            event_type=SIGNAL_PERCEIVE_EXECUTE_EVENT_TYPE,
            params={
                "action_uid": action_uid,
                "entity_id": command.entity_id,
                "channel": channel,
                "radius": int(radius),
            },
        )

    def _handle_emit_execute(self, sim: Simulation, event: SimEvent) -> None:
        state = self._rules_state(sim, "signal_emission")
        action_uid = str(event.params.get("action_uid", ""))
        if action_uid in state["executed_action_uids"]:
            self._schedule_emit_outcome(sim, tick=event.tick, action_uid=action_uid, entity_id=event.params.get("entity_id"), channel=event.params.get("channel"), outcome="already_applied")
            return

        channel = event.params.get("channel")
        if (
            not action_uid
            or not isinstance(channel, str)
            or channel not in self._ALLOWED_CHANNELS
            or not self._is_non_negative_int(event.params.get("base_intensity"), event.params.get("max_radius"), event.params.get("ttl_ticks"))
            or not isinstance(event.params.get("origin"), dict)
        ):
            self._mark_executed(sim, "signal_emission", action_uid)
            self._schedule_emit_outcome(sim, tick=event.tick, action_uid=action_uid, entity_id=event.params.get("entity_id"), channel=channel, outcome="invalid_params")
            return

        entity_id = event.params.get("entity_id")
        if not isinstance(entity_id, str) or entity_id not in sim.state.entities:
            self._mark_executed(sim, "signal_emission", action_uid)
            self._schedule_emit_outcome(sim, tick=event.tick, action_uid=action_uid, entity_id=entity_id, channel=channel, outcome="unknown_entity")
            return

        origin = LocationRef.from_dict(dict(event.params["origin"]))
        signal = SignalRecord(
            signal_id=action_uid,
            tick_emitted=event.tick,
            space_id=origin.space_id,
            origin=origin,
            channel=channel,
            base_intensity=int(event.params["base_intensity"]),
            falloff_model="linear",
            max_radius=int(event.params["max_radius"]),
            ttl_ticks=int(event.params["ttl_ticks"]),
            metadata=dict(event.params.get("metadata", {})),
        )
        sim.state.world.append_signal_record(signal.to_dict())
        self._mark_executed(sim, "signal_emission", action_uid)
        self._schedule_emit_outcome(sim, tick=event.tick, action_uid=action_uid, entity_id=entity_id, channel=channel, outcome="applied")

    def _handle_perceive_execute(self, sim: Simulation, event: SimEvent) -> None:
        state = self._rules_state(sim, "signal_perception")
        action_uid = str(event.params.get("action_uid", ""))
        if action_uid in state["executed_action_uids"]:
            self._schedule_perceive_outcome(sim, tick=event.tick, action_uid=action_uid, entity_id=event.params.get("entity_id"), channel=event.params.get("channel"), radius=event.params.get("radius"), outcome="already_applied", hits=[])
            return

        entity_id = event.params.get("entity_id")
        channel = event.params.get("channel")
        radius = event.params.get("radius")
        if not action_uid or not isinstance(channel, str) or channel not in self._ALLOWED_CHANNELS or not self._is_non_negative_int(radius):
            self._mark_executed(sim, "signal_perception", action_uid)
            self._schedule_perceive_outcome(sim, tick=event.tick, action_uid=action_uid, entity_id=entity_id, channel=channel, radius=radius, outcome="invalid_params", hits=[])
            return

        if not isinstance(entity_id, str) or entity_id not in sim.state.entities:
            self._mark_executed(sim, "signal_perception", action_uid)
            self._schedule_perceive_outcome(sim, tick=event.tick, action_uid=action_uid, entity_id=entity_id, channel=channel, radius=radius, outcome="unknown_entity", hits=[])
            return

        listener = self._entity_location(sim, entity_id)
        sensitivity, sensitivity_source, bonus = self._resolve_sensitivity(sim, entity_id=entity_id, channel=channel)
        hits: list[dict[str, int | str]] = []
        for record in sim.state.world.signals:
            signal = self._signal_from_dict(record)
            if signal is None or signal.channel != channel or signal.space_id != listener.space_id:
                continue
            metrics = compute_signal_path_metrics(
                signal,
                listener,
                world=sim.state.world,
                max_steps=min(signal.max_radius, int(radius)),
            )
            if metrics is None:
                continue
            effective_path_cost = int(metrics["effective_path_cost"])
            if effective_path_cost > int(radius):
                continue
            strength = compute_signal_strength(signal, listener, event.tick, world=sim.state.world) + bonus
            if strength <= 0:
                continue
            hits.append(
                {
                    "signal_id": signal.signal_id,
                    "distance": int(metrics["step_count"]),
                    "step_count": int(metrics["step_count"]),
                    "occlusion_cost": int(metrics["occlusion_cost"]),
                    "effective_path_cost": effective_path_cost,
                    "computed_strength": strength,
                    "age_ticks": event.tick - signal.tick_emitted,
                }
            )

        hits.sort(key=lambda entry: (int(entry["effective_path_cost"]), int(entry["step_count"]), str(entry["signal_id"])))
        self._mark_executed(sim, "signal_perception", action_uid)
        self._schedule_perceive_outcome(
            sim,
            tick=event.tick,
            action_uid=action_uid,
            entity_id=entity_id,
            channel=channel,
            radius=radius,
            outcome="completed",
            hits=hits,
            sensitivity=sensitivity,
            sensitivity_source=sensitivity_source,
            bonus=bonus,
        )

    def _rules_state(self, sim: Simulation, key: str) -> dict[str, Any]:
        root = sim.get_rules_state(self.name)
        state = root.get(key, {})
        if not isinstance(state, dict):
            raise ValueError(f"{self.name}.{key} must be an object")
        executed = state.get("executed_action_uids", [])
        if not isinstance(executed, list):
            raise ValueError(f"{self.name}.{key}.executed_action_uids must be a list")
        normalized = _normalize_uid_fifo(executed)
        state["executed_action_uids"] = normalized
        root[key] = state
        sim.set_rules_state(self.name, root)
        return state

    def _mark_executed(self, sim: Simulation, key: str, action_uid: str) -> None:
        if not action_uid:
            return
        root = sim.get_rules_state(self.name)
        bucket = root.get(key, {})
        if not isinstance(bucket, dict):
            bucket = {}
        executed = bucket.get("executed_action_uids", [])
        if not isinstance(executed, list):
            executed = []
        deduped = _normalize_uid_fifo([*executed, action_uid])
        bucket["executed_action_uids"] = deduped
        root[key] = bucket
        sim.set_rules_state(self.name, root)

    def _schedule_emit_outcome(self, sim: Simulation, *, tick: int, action_uid: str, entity_id: Any, channel: Any, outcome: str) -> None:
        sim.schedule_event_at(
            tick=tick,
            event_type=SIGNAL_EMIT_OUTCOME_EVENT_TYPE,
            params={
                "tick": tick,
                "entity_id": entity_id,
                "action_uid": action_uid,
                "channel": str(channel) if isinstance(channel, str) else "",
                "outcome": outcome,
            },
        )

    def _schedule_perceive_outcome(
        self,
        sim: Simulation,
        *,
        tick: int,
        action_uid: str,
        entity_id: Any,
        channel: Any,
        radius: Any,
        outcome: str,
        hits: list[dict[str, Any]],
        sensitivity: int = 0,
        sensitivity_source: str = "default",
        bonus: int = 0,
    ) -> None:
        sim.schedule_event_at(
            tick=tick,
            event_type=SIGNAL_PERCEIVE_OUTCOME_EVENT_TYPE,
            params={
                "tick": tick,
                "entity_id": entity_id,
                "action_uid": action_uid,
                "channel": str(channel) if isinstance(channel, str) else "",
                "radius": int(radius) if isinstance(radius, int) and radius >= 0 else 0,
                "outcome": outcome,
                "hits": copy.deepcopy(hits),
                "sensitivity": int(sensitivity),
                "sensitivity_source": sensitivity_source if isinstance(sensitivity_source, str) else "default",
                "bonus": int(bonus),
            },
        )

    def _entity_location(self, sim: Simulation, entity_id: str) -> LocationRef:
        entity = sim.state.entities[entity_id]
        space = sim.state.world.spaces.get(entity.space_id)
        if space is not None and space.topology_type == SQUARE_GRID_TOPOLOGY:
            return LocationRef(
                space_id=entity.space_id,
                topology_type=SQUARE_GRID_TOPOLOGY,
                coord={"x": int(entity.position_x), "y": int(entity.position_y)},
            )
        return LocationRef(space_id=entity.space_id, topology_type=OVERWORLD_HEX_TOPOLOGY, coord=entity.hex_coord.to_dict())

    def _signal_from_dict(self, payload: dict[str, Any]) -> SignalRecord | None:
        try:
            return SignalRecord(
                signal_id=str(payload["signal_id"]),
                tick_emitted=int(payload["tick_emitted"]),
                space_id=str(payload["space_id"]),
                origin=LocationRef.from_dict(dict(payload["origin"])),
                channel=str(payload["channel"]),
                base_intensity=int(payload["base_intensity"]),
                falloff_model=str(payload["falloff_model"]),
                max_radius=int(payload["max_radius"]),
                ttl_ticks=int(payload["ttl_ticks"]),
                metadata=dict(payload.get("metadata", {})),
            )
        except (KeyError, TypeError, ValueError):
            return None

    def _is_non_negative_int(self, *values: Any) -> bool:
        return all(isinstance(value, int) and value >= 0 for value in values)


def _normalize_uid_fifo(values: Any) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    if not isinstance(values, list):
        return []
    for raw in values:
        if not isinstance(raw, str) or not raw or raw in seen:
            continue
        seen.add(raw)
        ordered.append(raw)
    if len(ordered) > MAX_EXECUTED_ACTION_UIDS:
        ordered = ordered[-MAX_EXECUTED_ACTION_UIDS:]
    return ordered
