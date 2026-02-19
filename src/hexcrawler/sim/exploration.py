from __future__ import annotations

import copy
import math
from typing import Any

from hexcrawler.sim.core import SimCommand, SimEvent, Simulation
from hexcrawler.sim.location import LocationRef, OVERWORLD_HEX_TOPOLOGY, SQUARE_GRID_TOPOLOGY
from hexcrawler.sim.rules import RuleModule

EXPLORE_INTENT_COMMAND_TYPE = "explore_intent"
EXPLORE_EXECUTE_EVENT_TYPE = "explore_execute"
EXPLORATION_OUTCOME_EVENT_TYPE = "exploration_outcome"


class ExplorationExecutionModule(RuleModule):
    name = "exploration"

    _SUPPORTED_ACTIONS = {"search", "listen", "rest"}
    _STATE_SCHEDULED_ACTION_UIDS = "scheduled_action_uids"
    _STATE_COMPLETED_ACTION_UIDS = "completed_action_uids"

    def on_command(self, sim: Simulation, command: SimCommand, command_index: int) -> bool:
        if command.command_type != EXPLORE_INTENT_COMMAND_TYPE:
            return False

        action_uid = f"{command.tick}:{command_index}"
        state = self._rules_state(sim)
        scheduled = set(state[self._STATE_SCHEDULED_ACTION_UIDS])
        completed = set(state[self._STATE_COMPLETED_ACTION_UIDS])

        action = command.params.get("action")
        duration_ticks = command.params.get("duration_ticks")

        if not isinstance(action, str) or action not in self._SUPPORTED_ACTIONS:
            self._schedule_outcome(
                sim,
                tick=command.tick,
                entity_id=command.entity_id,
                action=action if isinstance(action, str) else "",
                action_uid=action_uid,
                outcome="invalid_action",
                location=None,
            )
            return True

        if not isinstance(duration_ticks, int) or duration_ticks <= 0:
            self._schedule_outcome(
                sim,
                tick=command.tick,
                entity_id=command.entity_id,
                action=action,
                action_uid=action_uid,
                outcome="invalid_duration_ticks",
                location=None,
            )
            return True

        if command.entity_id is None or command.entity_id not in sim.state.entities:
            self._schedule_outcome(
                sim,
                tick=command.tick,
                entity_id=command.entity_id,
                action=action,
                action_uid=action_uid,
                outcome="unknown_entity",
                location=None,
            )
            return True

        if action_uid in scheduled or action_uid in completed:
            self._schedule_outcome(
                sim,
                tick=command.tick,
                entity_id=command.entity_id,
                action=action,
                action_uid=action_uid,
                outcome="already_scheduled",
                location=self._entity_location(sim, entity_id=command.entity_id),
            )
            return True

        sim.schedule_event_at(
            tick=command.tick + duration_ticks,
            event_type=EXPLORE_EXECUTE_EVENT_TYPE,
            params={
                "entity_id": command.entity_id,
                "action": action,
                "action_uid": action_uid,
            },
        )
        scheduled.add(action_uid)
        state[self._STATE_SCHEDULED_ACTION_UIDS] = sorted(scheduled)
        sim.set_rules_state(self.name, state)
        return True

    def on_event_executed(self, sim: Simulation, event: SimEvent) -> None:
        if event.event_type != EXPLORE_EXECUTE_EVENT_TYPE:
            return

        action_uid = str(event.params.get("action_uid", ""))
        if not action_uid:
            raise ValueError("explore_execute action_uid must be a non-empty string")

        state = self._rules_state(sim)
        scheduled = set(state[self._STATE_SCHEDULED_ACTION_UIDS])
        completed = set(state[self._STATE_COMPLETED_ACTION_UIDS])
        if action_uid in completed:
            return

        entity_id_raw = event.params.get("entity_id")
        entity_id = str(entity_id_raw) if isinstance(entity_id_raw, str) else None
        action = str(event.params.get("action", ""))
        location = self._entity_location(sim, entity_id=entity_id) if entity_id is not None else None

        self._schedule_outcome(
            sim,
            tick=event.tick,
            entity_id=entity_id,
            action=action,
            action_uid=action_uid,
            outcome="completed",
            location=location,
        )

        scheduled.discard(action_uid)
        completed.add(action_uid)
        state[self._STATE_SCHEDULED_ACTION_UIDS] = sorted(scheduled)
        state[self._STATE_COMPLETED_ACTION_UIDS] = sorted(completed)
        sim.set_rules_state(self.name, state)

    def _rules_state(self, sim: Simulation) -> dict[str, Any]:
        state = sim.get_rules_state(self.name)
        scheduled = state.get(self._STATE_SCHEDULED_ACTION_UIDS, [])
        completed = state.get(self._STATE_COMPLETED_ACTION_UIDS, [])
        if not isinstance(scheduled, list):
            raise ValueError("exploration.rules_state.scheduled_action_uids must be a list")
        if not isinstance(completed, list):
            raise ValueError("exploration.rules_state.completed_action_uids must be a list")
        normalized_scheduled = sorted({str(uid) for uid in scheduled if isinstance(uid, str) and uid})
        normalized_completed = sorted({str(uid) for uid in completed if isinstance(uid, str) and uid})
        return {
            self._STATE_SCHEDULED_ACTION_UIDS: normalized_scheduled,
            self._STATE_COMPLETED_ACTION_UIDS: normalized_completed,
        }

    def _schedule_outcome(
        self,
        sim: Simulation,
        *,
        tick: int,
        entity_id: str | None,
        action: str,
        action_uid: str,
        outcome: str,
        location: LocationRef | None,
    ) -> None:
        params: dict[str, Any] = {
            "tick": tick,
            "entity_id": entity_id,
            "action": action,
            "action_uid": action_uid,
            "outcome": outcome,
        }
        if location is not None:
            params["location"] = location.to_dict()
        sim.schedule_event_at(
            tick=tick,
            event_type=EXPLORATION_OUTCOME_EVENT_TYPE,
            params=copy.deepcopy(params),
        )

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
