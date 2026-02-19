from __future__ import annotations

import copy
import math
from typing import Any

from hexcrawler.sim.core import SimCommand, SimEvent, Simulation
from hexcrawler.sim.location import LocationRef, OVERWORLD_HEX_TOPOLOGY, SQUARE_GRID_TOPOLOGY
from hexcrawler.sim.rules import RuleModule

INTERACTION_INTENT_COMMAND_TYPE = "interaction_intent"
INTERACTION_EXECUTE_EVENT_TYPE = "interaction_execute"
INTERACTION_OUTCOME_EVENT_TYPE = "interaction_outcome"
MAX_EXECUTED_ACTION_UIDS = 2048


class InteractionExecutionModule(RuleModule):
    name = "interaction"

    _SUPPORTED_TYPES = {"open", "close", "toggle", "inspect", "use", "exit"}
    _SUPPORTED_TARGETS = {"door", "anchor", "interactable"}
    _STATE_EXECUTED_ACTION_UIDS = "executed_action_uids"

    def on_command(self, sim: Simulation, command: SimCommand, command_index: int) -> bool:
        if command.command_type != INTERACTION_INTENT_COMMAND_TYPE:
            return False

        action_uid = f"{command.tick}:{command_index}"
        interaction_type = command.params.get("interaction_type")
        target = command.params.get("target")
        duration_ticks = command.params.get("duration_ticks")

        if command.entity_id is None or command.entity_id not in sim.state.entities:
            self._schedule_outcome(
                sim,
                tick=command.tick,
                entity_id=command.entity_id,
                interaction_type=str(interaction_type) if isinstance(interaction_type, str) else "",
                target=target if isinstance(target, dict) else {},
                action_uid=action_uid,
                outcome="invalid_params",
                details={"reason": "unknown_entity"},
                location=None,
            )
            return True

        if not isinstance(interaction_type, str) or interaction_type not in self._SUPPORTED_TYPES:
            self._schedule_outcome(
                sim,
                tick=command.tick,
                entity_id=command.entity_id,
                interaction_type=str(interaction_type) if isinstance(interaction_type, str) else "",
                target=target if isinstance(target, dict) else {},
                action_uid=action_uid,
                outcome="invalid_params",
                details={"reason": "invalid_interaction_type"},
                location=self._entity_location(sim, entity_id=command.entity_id),
            )
            return True

        if not isinstance(duration_ticks, int) or duration_ticks < 0:
            self._schedule_outcome(
                sim,
                tick=command.tick,
                entity_id=command.entity_id,
                interaction_type=interaction_type,
                target=target if isinstance(target, dict) else {},
                action_uid=action_uid,
                outcome="invalid_params",
                details={"reason": "invalid_duration_ticks"},
                location=self._entity_location(sim, entity_id=command.entity_id),
            )
            return True

        normalized_target = self._normalize_target(target)
        if normalized_target is None:
            self._schedule_outcome(
                sim,
                tick=command.tick,
                entity_id=command.entity_id,
                interaction_type=interaction_type,
                target=target if isinstance(target, dict) else {},
                action_uid=action_uid,
                outcome="invalid_params",
                details={"reason": "invalid_target"},
                location=self._entity_location(sim, entity_id=command.entity_id),
            )
            return True

        sim.schedule_event_at(
            tick=command.tick + duration_ticks,
            event_type=INTERACTION_EXECUTE_EVENT_TYPE,
            params={
                "tick": command.tick,
                "entity_id": command.entity_id,
                "interaction_type": interaction_type,
                "target": normalized_target,
                "action_uid": action_uid,
                "duration_ticks": duration_ticks,
            },
        )
        return True

    def on_event_executed(self, sim: Simulation, event: SimEvent) -> None:
        if event.event_type != INTERACTION_EXECUTE_EVENT_TYPE:
            return

        action_uid = str(event.params.get("action_uid", ""))
        interaction_type = str(event.params.get("interaction_type", ""))
        target = event.params.get("target")
        entity_id_raw = event.params.get("entity_id")
        entity_id = str(entity_id_raw) if isinstance(entity_id_raw, str) else None
        normalized_target = self._normalize_target(target)

        state = self._rules_state(sim)
        executed = list(state[self._STATE_EXECUTED_ACTION_UIDS])

        location = self._entity_location(sim, entity_id=entity_id) if entity_id is not None and entity_id in sim.state.entities else None

        if action_uid in executed:
            self._schedule_outcome(
                sim,
                tick=event.tick,
                entity_id=entity_id,
                interaction_type=interaction_type,
                target=target if isinstance(target, dict) else {},
                action_uid=action_uid,
                outcome="already_applied",
                details={},
                location=location,
            )
            return

        if not action_uid or not normalized_target or interaction_type not in self._SUPPORTED_TYPES:
            executed.add(action_uid)
            state[self._STATE_EXECUTED_ACTION_UIDS] = sorted(uid for uid in executed if uid)
            sim.set_rules_state(self.name, state)
            self._schedule_outcome(
                sim,
                tick=event.tick,
                entity_id=entity_id,
                interaction_type=interaction_type,
                target=target if isinstance(target, dict) else {},
                action_uid=action_uid,
                outcome="invalid_params",
                details={},
                location=location,
            )
            return

        outcome = "unknown_target"
        details: dict[str, Any] = {}

        if entity_id is not None and entity_id in sim.state.entities:
            entity = sim.state.entities[entity_id]
            space = sim.state.world.spaces.get(entity.space_id)
            if space is not None:
                target_kind = normalized_target["kind"]
                target_id = normalized_target["id"]
                if target_kind == "door":
                    door = space.doors.get(target_id)
                    if door is not None:
                        if door.flags.get("locked") or door.flags.get("blocked"):
                            outcome = "blocked"
                        elif interaction_type in {"open", "close", "toggle"}:
                            prior_state = door.state
                            if interaction_type == "open":
                                door.state = "open"
                            elif interaction_type == "close":
                                door.state = "closed"
                            else:
                                door.state = "closed" if door.state == "open" else "open"
                            outcome = "applied"
                            details = {"no_change": prior_state == door.state, "state": door.state}
                        else:
                            outcome = "invalid_params"
                elif target_kind == "interactable":
                    interactable = space.interactables.get(target_id)
                    if interactable is not None:
                        if interaction_type in {"inspect", "use"}:
                            outcome = "applied"
                            details = {"kind": interactable.kind}
                        else:
                            outcome = "invalid_params"
                elif target_kind == "anchor":
                    anchor = space.anchors.get(target_id)
                    if anchor is not None:
                        if interaction_type != "exit":
                            outcome = "invalid_params"
                        elif anchor.target.get("type") == "space":
                            target_space_id = anchor.target.get("space_id")
                            if isinstance(target_space_id, str):
                                destination_space = sim.state.world.spaces.get(target_space_id)
                                if destination_space is not None:
                                    sim.append_command(
                                        SimCommand(
                                            tick=event.tick + 1,
                                            entity_id=entity_id,
                                            command_type="transition_space",
                                            params={
                                                "to_location": {
                                                    "space_id": target_space_id,
                                                    "topology_type": destination_space.topology_type,
                                                    "coord": destination_space.default_spawn_coord(),
                                                },
                                                "reason": "interaction_anchor_exit",
                                            },
                                        )
                                    )
                                    outcome = "applied"
                                else:
                                    outcome = "unknown_target"
                            else:
                                outcome = "invalid_params"
                        elif anchor.target.get("type") == "site":
                            site_id = anchor.target.get("site_id")
                            if not isinstance(site_id, str):
                                outcome = "invalid_params"
                            else:
                                site = sim.state.world.sites.get(site_id)
                                if site is None or site.entrance is None:
                                    outcome = "unknown_target"
                                else:
                                    sim.append_command(
                                        SimCommand(
                                            tick=event.tick + 1,
                                            entity_id=entity_id,
                                            command_type="enter_site",
                                            params={"site_id": site_id},
                                        )
                                    )
                                    outcome = "applied"

        executed.append(action_uid)
        state[self._STATE_EXECUTED_ACTION_UIDS] = _normalize_uid_fifo(executed)
        sim.set_rules_state(self.name, state)

        self._schedule_outcome(
            sim,
            tick=event.tick,
            entity_id=entity_id,
            interaction_type=interaction_type,
            target=normalized_target,
            action_uid=action_uid,
            outcome=outcome,
            details=details,
            location=location,
        )

    def _rules_state(self, sim: Simulation) -> dict[str, Any]:
        state = sim.get_rules_state(self.name)
        executed = state.get(self._STATE_EXECUTED_ACTION_UIDS, [])
        if not isinstance(executed, list):
            raise ValueError("interaction.rules_state.executed_action_uids must be a list")
        return {self._STATE_EXECUTED_ACTION_UIDS: _normalize_uid_fifo(executed)}

    def _normalize_target(self, payload: Any) -> dict[str, str] | None:
        if not isinstance(payload, dict):
            return None
        kind = payload.get("kind")
        record_id = payload.get("id")
        if not isinstance(kind, str) or kind not in self._SUPPORTED_TARGETS:
            return None
        if not isinstance(record_id, str) or not record_id:
            return None
        return {"kind": kind, "id": record_id}

    def _schedule_outcome(
        self,
        sim: Simulation,
        *,
        tick: int,
        entity_id: str | None,
        interaction_type: str,
        target: dict[str, Any],
        action_uid: str,
        outcome: str,
        details: dict[str, Any],
        location: LocationRef | None,
    ) -> None:
        params: dict[str, Any] = {
            "tick": tick,
            "entity_id": entity_id,
            "interaction_type": interaction_type,
            "target": copy.deepcopy(target),
            "action_uid": action_uid,
            "outcome": outcome,
            "details": copy.deepcopy(details),
        }
        if location is not None:
            params["location"] = location.to_dict()
        sim.schedule_event_at(tick=tick, event_type=INTERACTION_OUTCOME_EVENT_TYPE, params=params)

    def _entity_location(self, sim: Simulation, *, entity_id: str) -> LocationRef:
        entity = sim.state.entities[entity_id]
        space = sim.state.world.spaces.get(entity.space_id)
        if space is not None and space.topology_type == SQUARE_GRID_TOPOLOGY:
            return LocationRef(
                space_id=entity.space_id,
                topology_type=SQUARE_GRID_TOPOLOGY,
                coord={"x": math.floor(entity.position_x), "y": math.floor(entity.position_y)},
            )
        return LocationRef(space_id=entity.space_id, topology_type=OVERWORLD_HEX_TOPOLOGY, coord=entity.hex_coord.to_dict())


def _normalize_uid_fifo(values: Any) -> list[str]:
    iterable = values if isinstance(values, list) else list(values) if isinstance(values, set) else []
    ordered: list[str] = []
    seen: set[str] = set()
    for uid in iterable:
        if not isinstance(uid, str) or not uid or uid in seen:
            continue
        seen.add(uid)
        ordered.append(uid)
    if len(ordered) > MAX_EXECUTED_ACTION_UIDS:
        ordered = ordered[-MAX_EXECUTED_ACTION_UIDS:]
    return ordered
