from __future__ import annotations

import copy
import math
from typing import Any

from hexcrawler.sim.core import SimCommand, SimEvent, Simulation
from hexcrawler.sim.location import LocationRef, OVERWORLD_HEX_TOPOLOGY, SQUARE_GRID_TOPOLOGY
from hexcrawler.sim.rules import RuleModule
from hexcrawler.sim.wounds import recover_one_light_wound

EXPLORE_INTENT_COMMAND_TYPE = "explore_intent"
EXPLORE_EXECUTE_EVENT_TYPE = "explore_execute"
EXPLORATION_OUTCOME_EVENT_TYPE = "exploration_outcome"
RECOVERY_EXECUTE_EVENT_TYPE = "recovery_execute"
SAFE_RECOVERY_INTENT_COMMAND_TYPE = "safe_recovery_intent"
TURN_IN_REWARD_TOKEN_INTENT_COMMAND_TYPE = "turn_in_reward_token_intent"
RECOVERY_OUTCOME_EVENT_TYPE = "recovery_outcome"
REWARD_TURN_IN_OUTCOME_EVENT_TYPE = "reward_turn_in_outcome"

SAFE_SITE_TYPES = {"town"}
SAFE_SITE_TAG = "safe"
MAX_RECOVERY_ACTION_UIDS = 2048
REWARD_TOKEN_ITEM_ID = "proof_token"
REWARD_TURN_IN_BENEFIT_ITEM_ID = "rations"
REWARD_TURN_IN_BENEFIT_QUANTITY = 1


class ExplorationExecutionModule(RuleModule):
    name = "exploration"

    _SUPPORTED_ACTIONS = {"search", "listen", "rest"}
    _CAMPAIGN_RECOVERY_DURATION_TICKS = 60
    _STATE_RECOVERY_SCHEDULED_ACTION_UIDS = "recovery_scheduled_action_uids"
    _STATE_RECOVERY_COMPLETED_ACTION_UIDS = "recovery_completed_action_uids"
    _STATE_SCHEDULED_ACTION_UIDS = "scheduled_action_uids"
    _STATE_COMPLETED_ACTION_UIDS = "completed_action_uids"

    def on_command(self, sim: Simulation, command: SimCommand, command_index: int) -> bool:
        if command.command_type == TURN_IN_REWARD_TOKEN_INTENT_COMMAND_TYPE:
            self._handle_reward_turn_in_intent(sim, command=command, command_index=command_index)
            return True

        if command.command_type == SAFE_RECOVERY_INTENT_COMMAND_TYPE:
            action_uid = f"recovery:{command.tick}:{command_index}"
            recovery_state = self._recovery_rules_state(sim)
            scheduled = list(recovery_state[self._STATE_RECOVERY_SCHEDULED_ACTION_UIDS])
            completed = list(recovery_state[self._STATE_RECOVERY_COMPLETED_ACTION_UIDS])
            scheduled_set = set(scheduled)
            completed_set = set(completed)

            if command.entity_id is None or command.entity_id not in sim.state.entities:
                self._schedule_recovery_outcome(
                    sim,
                    tick=command.tick,
                    entity_id=command.entity_id,
                    action_uid=action_uid,
                    outcome="rejected",
                    reason="unknown_entity",
                    location=None,
                )
                return True

            if action_uid in scheduled_set or action_uid in completed_set:
                self._schedule_recovery_outcome(
                    sim,
                    tick=command.tick,
                    entity_id=command.entity_id,
                    action_uid=action_uid,
                    outcome="rejected",
                    reason="already_scheduled",
                    location=self._entity_location(sim, entity_id=command.entity_id),
                )
                return True

            location = self._entity_location(sim, entity_id=command.entity_id)
            space = sim.state.world.spaces.get(location.space_id)
            if space is None or space.role != "campaign":
                self._schedule_recovery_outcome(
                    sim,
                    tick=command.tick,
                    entity_id=command.entity_id,
                    action_uid=action_uid,
                    outcome="rejected",
                    reason="campaign_space_required",
                    location=location,
                )
                return True

            is_safe_site, site_id, site_type = self._is_safe_recovery_site(sim, location=location)
            if not is_safe_site:
                self._schedule_recovery_outcome(
                    sim,
                    tick=command.tick,
                    entity_id=command.entity_id,
                    action_uid=action_uid,
                    outcome="rejected",
                    reason="safe_site_required",
                    location=location,
                    details={"site_type": site_type},
                )
                return True

            entity = sim.state.entities[command.entity_id]
            if not any(isinstance(w, dict) and w.get("severity") == 1 for w in entity.wounds):
                self._schedule_recovery_outcome(
                    sim,
                    tick=command.tick,
                    entity_id=command.entity_id,
                    action_uid=action_uid,
                    outcome="rejected",
                    reason="no_recoverable_wound",
                    location=location,
                    site_id=site_id,
                )
                return True

            sim.schedule_event_at(
                tick=command.tick + self._CAMPAIGN_RECOVERY_DURATION_TICKS,
                event_type=RECOVERY_EXECUTE_EVENT_TYPE,
                params={
                    "entity_id": command.entity_id,
                    "action_uid": action_uid,
                    "site_id": site_id,
                },
            )
            scheduled.append(action_uid)
            recovery_state[self._STATE_RECOVERY_SCHEDULED_ACTION_UIDS] = _normalize_recovery_uid_fifo(scheduled)
            sim.set_rules_state(self.name, {**sim.get_rules_state(self.name), **recovery_state})
            self._schedule_recovery_outcome(
                sim,
                tick=command.tick,
                entity_id=command.entity_id,
                action_uid=action_uid,
                outcome="scheduled",
                reason="accepted",
                location=location,
                site_id=site_id,
            )
            return True

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
        sim.set_rules_state(self.name, {**sim.get_rules_state(self.name), **state})
        return True

    def on_event_executed(self, sim: Simulation, event: SimEvent) -> None:
        if event.event_type == RECOVERY_EXECUTE_EVENT_TYPE:
            action_uid = str(event.params.get("action_uid", ""))
            if not action_uid:
                raise ValueError("recovery_execute action_uid must be a non-empty string")

            recovery_state = self._recovery_rules_state(sim)
            scheduled = list(recovery_state[self._STATE_RECOVERY_SCHEDULED_ACTION_UIDS])
            completed = list(recovery_state[self._STATE_RECOVERY_COMPLETED_ACTION_UIDS])
            completed_set = set(completed)
            if action_uid in completed_set:
                return

            entity_id_raw = event.params.get("entity_id")
            entity_id = str(entity_id_raw) if isinstance(entity_id_raw, str) else None
            location = self._entity_location(sim, entity_id=entity_id) if entity_id is not None and entity_id in sim.state.entities else None
            site_id = str(event.params.get("site_id")) if event.params.get("site_id") is not None else None

            if entity_id is None or entity_id not in sim.state.entities:
                self._schedule_recovery_outcome(
                    sim,
                    tick=event.tick,
                    entity_id=entity_id,
                    action_uid=action_uid,
                    outcome="rejected",
                    reason="unknown_entity",
                    location=location,
                    site_id=site_id,
                )
            else:
                entity = sim.state.entities[entity_id]
                updated_wounds, recovered = recover_one_light_wound(entity.wounds)
                entity.wounds = updated_wounds
                if recovered is None:
                    self._schedule_recovery_outcome(
                        sim,
                        tick=event.tick,
                        entity_id=entity_id,
                        action_uid=action_uid,
                        outcome="completed",
                        reason="no_recoverable_wound",
                        location=location,
                        site_id=site_id,
                    )
                else:
                    self._schedule_recovery_outcome(
                        sim,
                        tick=event.tick,
                        entity_id=entity_id,
                        action_uid=action_uid,
                        outcome="completed",
                        reason="light_wound_recovered",
                        location=location,
                        site_id=site_id,
                        details={"recovered_wound": recovered},
                    )

            scheduled = [uid for uid in scheduled if uid != action_uid]
            completed.append(action_uid)
            recovery_state[self._STATE_RECOVERY_SCHEDULED_ACTION_UIDS] = _normalize_recovery_uid_fifo(scheduled)
            recovery_state[self._STATE_RECOVERY_COMPLETED_ACTION_UIDS] = _normalize_recovery_uid_fifo(completed)
            sim.set_rules_state(self.name, {**sim.get_rules_state(self.name), **recovery_state})
            return

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
        sim.set_rules_state(self.name, {**sim.get_rules_state(self.name), **state})


    def _handle_reward_turn_in_intent(self, sim: Simulation, *, command: SimCommand, command_index: int) -> None:
        action_uid = f"reward_turn_in:{command.tick}:{command_index}"
        if command.entity_id is None or command.entity_id not in sim.state.entities:
            self._schedule_reward_turn_in_outcome(
                sim,
                tick=command.tick,
                entity_id=command.entity_id,
                action_uid=action_uid,
                applied=False,
                reason="unknown_entity",
                details={},
            )
            return

        location = self._entity_location(sim, entity_id=command.entity_id)
        space = sim.state.world.spaces.get(location.space_id)
        if space is None or space.role != "campaign":
            self._schedule_reward_turn_in_outcome(
                sim,
                tick=command.tick,
                entity_id=command.entity_id,
                action_uid=action_uid,
                applied=False,
                reason="campaign_space_required",
                location=location,
                details={},
            )
            return

        is_safe_site, site_id, _ = self._is_safe_recovery_site(sim, location=location)
        if not is_safe_site:
            self._schedule_reward_turn_in_outcome(
                sim,
                tick=command.tick,
                entity_id=command.entity_id,
                action_uid=action_uid,
                applied=False,
                reason="safe_site_required",
                location=location,
                details={},
            )
            return

        entity = sim.state.entities[command.entity_id]
        container_id = entity.inventory_container_id
        if container_id is None or container_id not in sim.state.world.containers:
            self._schedule_reward_turn_in_outcome(
                sim,
                tick=command.tick,
                entity_id=command.entity_id,
                action_uid=action_uid,
                applied=False,
                reason="no_inventory_container",
                location=location,
                site_id=site_id,
                details={},
            )
            return

        consume_uid = f"{action_uid}:consume"
        sim._execute_inventory_intent(
            SimCommand(
                tick=command.tick,
                entity_id=command.entity_id,
                command_type="inventory_intent",
                params={
                    "src_container_id": container_id,
                    "dst_container_id": None,
                    "item_id": REWARD_TOKEN_ITEM_ID,
                    "quantity": 1,
                    "reason": "consume",
                    "action_uid": consume_uid,
                },
            ),
            command_index=0,
        )
        consume_outcome = self._inventory_outcome_for_action_uid(sim=sim, action_uid=consume_uid)
        if consume_outcome != "applied":
            reason = "token_required" if consume_outcome == "insufficient_quantity" else "token_consume_rejected"
            self._schedule_reward_turn_in_outcome(
                sim,
                tick=command.tick,
                entity_id=command.entity_id,
                action_uid=action_uid,
                applied=False,
                reason=reason,
                location=location,
                site_id=site_id,
                details={"consume_outcome": consume_outcome},
            )
            return

        grant_uid = f"{action_uid}:grant"
        sim._execute_inventory_intent(
            SimCommand(
                tick=command.tick,
                entity_id=command.entity_id,
                command_type="inventory_intent",
                params={
                    "src_container_id": None,
                    "dst_container_id": container_id,
                    "item_id": REWARD_TURN_IN_BENEFIT_ITEM_ID,
                    "quantity": REWARD_TURN_IN_BENEFIT_QUANTITY,
                    "reason": "spawn",
                    "action_uid": grant_uid,
                },
            ),
            command_index=0,
        )
        grant_outcome = self._inventory_outcome_for_action_uid(sim=sim, action_uid=grant_uid)
        if grant_outcome != "applied":
            refund_uid = f"{action_uid}:refund"
            sim._execute_inventory_intent(
                SimCommand(
                    tick=command.tick,
                    entity_id=command.entity_id,
                    command_type="inventory_intent",
                    params={
                        "src_container_id": None,
                        "dst_container_id": container_id,
                        "item_id": REWARD_TOKEN_ITEM_ID,
                        "quantity": 1,
                        "reason": "spawn",
                        "action_uid": refund_uid,
                    },
                ),
                command_index=0,
            )
            refund_outcome = self._inventory_outcome_for_action_uid(sim=sim, action_uid=refund_uid)
            self._schedule_reward_turn_in_outcome(
                sim,
                tick=command.tick,
                entity_id=command.entity_id,
                action_uid=action_uid,
                applied=False,
                reason="benefit_grant_rejected",
                location=location,
                site_id=site_id,
                details={"grant_outcome": grant_outcome, "refund_outcome": refund_outcome},
            )
            return

        self._schedule_reward_turn_in_outcome(
            sim,
            tick=command.tick,
            entity_id=command.entity_id,
            action_uid=action_uid,
            applied=True,
            reason="reward_turned_in",
            location=location,
            site_id=site_id,
            details={
                "consumed_item_id": REWARD_TOKEN_ITEM_ID,
                "granted_item_id": REWARD_TURN_IN_BENEFIT_ITEM_ID,
                "granted_quantity": REWARD_TURN_IN_BENEFIT_QUANTITY,
            },
        )

    @staticmethod
    def _inventory_outcome_for_action_uid(*, sim: Simulation, action_uid: str) -> str:
        for entry in reversed(sim.state.event_trace):
            if entry.get("event_type") != "inventory_outcome":
                continue
            params = entry.get("params")
            if not isinstance(params, dict) or params.get("action_uid") != action_uid:
                continue
            outcome = params.get("outcome")
            if isinstance(outcome, str):
                return outcome
        return "missing_outcome"

    def _schedule_reward_turn_in_outcome(
        self,
        sim: Simulation,
        *,
        tick: int,
        entity_id: str | None,
        action_uid: str,
        applied: bool,
        reason: str,
        location: LocationRef | None = None,
        site_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        params: dict[str, Any] = {
            "tick": tick,
            "entity_id": entity_id,
            "action_uid": action_uid,
            "applied": bool(applied),
            "reason": reason,
        }
        if location is not None:
            params["location"] = location.to_dict()
        if site_id is not None:
            params["site_id"] = site_id
        if details is not None:
            params["details"] = copy.deepcopy(details)
        sim.schedule_event_at(
            tick=tick,
            event_type=REWARD_TURN_IN_OUTCOME_EVENT_TYPE,
            params=params,
        )

    def _recovery_rules_state(self, sim: Simulation) -> dict[str, list[str]]:
        state = sim.get_rules_state(self.name)
        scheduled = _normalize_recovery_uid_fifo(state.get(self._STATE_RECOVERY_SCHEDULED_ACTION_UIDS, []))
        completed = _normalize_recovery_uid_fifo(state.get(self._STATE_RECOVERY_COMPLETED_ACTION_UIDS, []))
        return {
            self._STATE_RECOVERY_SCHEDULED_ACTION_UIDS: scheduled,
            self._STATE_RECOVERY_COMPLETED_ACTION_UIDS: completed,
        }

    def _is_safe_recovery_site(self, sim: Simulation, *, location: LocationRef) -> tuple[bool, str | None, str | None]:
        for site in sim.state.world.sites.values():
            site_location = site.location
            if (
                site_location.get("space_id") == location.space_id
                and site_location.get("coord") == location.coord
            ):
                safe = site.site_type in SAFE_SITE_TYPES or SAFE_SITE_TAG in site.tags
                return safe, site.site_id, site.site_type
        return False, None, None

    def _schedule_recovery_outcome(
        self,
        sim: Simulation,
        *,
        tick: int,
        entity_id: str | None,
        action_uid: str,
        outcome: str,
        reason: str,
        location: LocationRef | None,
        site_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        params: dict[str, Any] = {
            "tick": tick,
            "entity_id": entity_id,
            "action_uid": action_uid,
            "outcome": outcome,
            "reason": reason,
        }
        if site_id is not None:
            params["site_id"] = site_id
        if location is not None:
            params["location"] = location.to_dict()
        if details is not None:
            params["details"] = copy.deepcopy(details)
        sim.schedule_event_at(
            tick=tick,
            event_type=RECOVERY_OUTCOME_EVENT_TYPE,
            params=params,
        )

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


def _normalize_recovery_uid_fifo(values: Any) -> list[str]:
    if not isinstance(values, list):
        raise ValueError("recovery action uid state must be a list")
    iterable = values

    ordered: list[str] = []
    seen: set[str] = set()
    for uid in iterable:
        if not isinstance(uid, str) or not uid or uid in seen:
            continue
        seen.add(uid)
        ordered.append(uid)
    if len(ordered) > MAX_RECOVERY_ACTION_UIDS:
        ordered = ordered[-MAX_RECOVERY_ACTION_UIDS:]
    return ordered
