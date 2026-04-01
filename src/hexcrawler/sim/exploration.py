from __future__ import annotations

import copy
import math
from typing import Any

from hexcrawler.sim.core import EntityState, SimCommand, SimEvent, Simulation
from hexcrawler.sim.campaign_danger import DEFAULT_DANGER_ENTITY_ID
from hexcrawler.sim.greybridge_layout import compile_greybridge_overlay
from hexcrawler.sim.location import LocationRef, OVERWORLD_HEX_TOPOLOGY, SQUARE_GRID_TOPOLOGY
from hexcrawler.sim.rules import RuleModule
from hexcrawler.sim.wounds import is_incapacitated_from_wounds, recover_one_light_wound

EXPLORE_INTENT_COMMAND_TYPE = "explore_intent"
EXPLORE_EXECUTE_EVENT_TYPE = "explore_execute"
EXPLORATION_OUTCOME_EVENT_TYPE = "exploration_outcome"
RECOVERY_EXECUTE_EVENT_TYPE = "recovery_execute"
SAFE_RECOVERY_INTENT_COMMAND_TYPE = "safe_recovery_intent"
TURN_IN_REWARD_TOKEN_INTENT_COMMAND_TYPE = "turn_in_reward_token_intent"
ENTER_SAFE_HUB_INTENT_COMMAND_TYPE = "enter_safe_hub_intent"
EXIT_SAFE_HUB_INTENT_COMMAND_TYPE = "exit_safe_hub_intent"
LOOT_LOCAL_PROOF_INTENT_COMMAND_TYPE = "loot_local_proof_intent"
RECOVERY_OUTCOME_EVENT_TYPE = "recovery_outcome"
REWARD_TURN_IN_OUTCOME_EVENT_TYPE = "reward_turn_in_outcome"
SAFE_HUB_OUTCOME_EVENT_TYPE = "safe_hub_outcome"
LOCAL_ENCOUNTER_REWARD_EVENT_TYPE = "local_encounter_reward"

SAFE_SITE_TYPES = {"town"}
SAFE_SITE_TAG = "safe"
MAX_RECOVERY_ACTION_UIDS = 2048
REWARD_TOKEN_ITEM_ID = "proof_token"
REWARD_TURN_IN_BENEFIT_ITEM_ID = "rations"
REWARD_TURN_IN_BENEFIT_QUANTITY = 1
GREYBRIDGE_SITE_ID = "home_greybridge"
GREYBRIDGE_SAFE_HUB_SPACE_ID = "safe_hub:greybridge"
GREYBRIDGE_PATROL_TEMPLATE_ID = "campaign_danger_patrol"
GREYBRIDGE_PATROL_RESPAWN_EVENT_TYPE = "greybridge_patrol_respawn"
GREYBRIDGE_PATROL_SPAWN_X = -2.60
GREYBRIDGE_PATROL_SPAWN_Y = 1.90
GREYBRIDGE_SAFE_HUB_GATE_ID = "town_gate_exit"


class ExplorationExecutionModule(RuleModule):
    name = "exploration"

    _SUPPORTED_ACTIONS = {"search", "listen", "rest"}
    _CAMPAIGN_RECOVERY_DURATION_TICKS = 60
    _STATE_RECOVERY_SCHEDULED_ACTION_UIDS = "recovery_scheduled_action_uids"
    _STATE_RECOVERY_COMPLETED_ACTION_UIDS = "recovery_completed_action_uids"
    _STATE_SCHEDULED_ACTION_UIDS = "scheduled_action_uids"
    _STATE_COMPLETED_ACTION_UIDS = "completed_action_uids"

    def on_command(self, sim: Simulation, command: SimCommand, command_index: int) -> bool:
        if command.command_type == ENTER_SAFE_HUB_INTENT_COMMAND_TYPE:
            self._handle_enter_safe_hub_intent(sim, command=command, command_index=command_index)
            return True

        if command.command_type == EXIT_SAFE_HUB_INTENT_COMMAND_TYPE:
            self._handle_exit_safe_hub_intent(sim, command=command, command_index=command_index)
            return True

        if command.command_type == LOOT_LOCAL_PROOF_INTENT_COMMAND_TYPE:
            self._handle_loot_local_proof_intent(sim, command=command, command_index=command_index)
            return True

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
            allowed_recovery, site_id, site_type, recovery_reason = self._is_valid_recovery_context(
                sim=sim,
                entity=sim.state.entities[command.entity_id],
                location=location,
            )
            if not allowed_recovery:
                self._schedule_recovery_outcome(
                    sim,
                    tick=command.tick,
                    entity_id=command.entity_id,
                    action_uid=action_uid,
                    outcome="rejected",
                    reason=recovery_reason,
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
                details={
                    "duration_ticks": self._CAMPAIGN_RECOVERY_DURATION_TICKS,
                    "ration_cost": 0,
                    "rations_purpose": "Rations support expedition pressure; recovery here consumes time, not rations.",
                    "rations_before": self._rations_for_entity(entity=sim.state.entities[command.entity_id], sim=sim),
                    "wound_severity_before": _wound_severity_total(sim.state.entities[command.entity_id].wounds),
                    "wound_count_before": len(sim.state.entities[command.entity_id].wounds),
                },
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
        if event.event_type == GREYBRIDGE_PATROL_RESPAWN_EVENT_TYPE:
            self._handle_greybridge_patrol_respawn(sim, event=event)
            return

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
                before_wounds = copy.deepcopy(entity.wounds)
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
                        details={
                            "wound_severity_before": _wound_severity_total(before_wounds),
                            "wound_severity_after": _wound_severity_total(updated_wounds),
                            "wound_count_before": len(before_wounds),
                            "wound_count_after": len(updated_wounds),
                            "time_advanced_ticks": self._CAMPAIGN_RECOVERY_DURATION_TICKS,
                            "ration_cost": 0,
                            "rations_before": self._rations_for_entity(entity=entity, sim=sim),
                            "rations_after": self._rations_for_entity(entity=entity, sim=sim),
                        },
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
                        details={
                            "recovered_wound": recovered,
                            "wound_severity_before": _wound_severity_total(before_wounds),
                            "wound_severity_after": _wound_severity_total(updated_wounds),
                            "wound_count_before": len(before_wounds),
                            "wound_count_after": len(updated_wounds),
                            "time_advanced_ticks": self._CAMPAIGN_RECOVERY_DURATION_TICKS,
                            "ration_cost": 0,
                            "rations_before": self._rations_for_entity(entity=entity, sim=sim),
                            "rations_after": self._rations_for_entity(entity=entity, sim=sim),
                        },
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

    def _handle_enter_safe_hub_intent(self, sim: Simulation, *, command: SimCommand, command_index: int) -> None:
        action_uid = f"safe_hub_enter:{command.tick}:{command_index}"
        site_id = str(command.params.get("site_id", GREYBRIDGE_SITE_ID))
        entity = sim.state.entities.get(command.entity_id or "")
        if entity is None:
            self._schedule_safe_hub_outcome(
                sim, tick=command.tick, entity_id=command.entity_id, action_uid=action_uid, applied=False, reason="unknown_entity"
            )
            return
        location = self._entity_location(sim, entity_id=entity.entity_id)
        space = sim.state.world.spaces.get(location.space_id)
        if space is None or space.role != "campaign":
            self._schedule_safe_hub_outcome(
                sim, tick=command.tick, entity_id=entity.entity_id, action_uid=action_uid, applied=False, reason="campaign_space_required"
            )
            return
        is_safe_site, resolved_site_id, _ = self._is_safe_recovery_site(sim, location=location)
        if not is_safe_site or resolved_site_id != site_id:
            self._schedule_safe_hub_outcome(
                sim, tick=command.tick, entity_id=entity.entity_id, action_uid=action_uid, applied=False, reason="safe_site_required"
            )
            return
        if site_id != GREYBRIDGE_SITE_ID:
            self._schedule_safe_hub_outcome(
                sim, tick=command.tick, entity_id=entity.entity_id, action_uid=action_uid, applied=False, reason="unsupported_safe_hub_site"
            )
            return

        safe_hub = sim.state.world.spaces.get(GREYBRIDGE_SAFE_HUB_SPACE_ID)
        if safe_hub is None:
            from hexcrawler.sim.world import AnchorRecord, InteractableRecord, SpaceState

            compiled_overlay = compile_greybridge_overlay()
            blocked_cells = [{"x": int(x), "y": int(y)} for x, y in compiled_overlay["blocked_cells"]]
            safe_hub = SpaceState(
                space_id=GREYBRIDGE_SAFE_HUB_SPACE_ID,
                topology_type=SQUARE_GRID_TOPOLOGY,
                role="local",
                topology_params={
                    "width": 14,
                    "height": 10,
                    "origin": {"x": 0, "y": 0},
                    "blocked_cells": blocked_cells,
                },
            )
            safe_hub.anchors = {
                "entry": AnchorRecord(
                    anchor_id="entry",
                    space_id=GREYBRIDGE_SAFE_HUB_SPACE_ID,
                    coord={"x": 2, "y": 5},
                    kind="transition",
                    target={"type": "space", "space_id": GREYBRIDGE_SAFE_HUB_SPACE_ID},
                ),
                "exit_to_campaign": AnchorRecord(
                    anchor_id="exit_to_campaign",
                    space_id=GREYBRIDGE_SAFE_HUB_SPACE_ID,
                    coord={"x": 1, "y": 5},
                    kind="exit",
                    target={"type": "site", "site_id": GREYBRIDGE_SITE_ID},
                ),
            }
            safe_hub.interactables = {
                "watch_hall": InteractableRecord(
                    interactable_id="watch_hall",
                    space_id=GREYBRIDGE_SAFE_HUB_SPACE_ID,
                    coord={"x": 10, "y": 3},
                    kind="quartermaster",
                    state={"building": "watch_hall"},
                    metadata={"label": "Watch Hall / Quartermaster"},
                ),
                "inn_infirmary": InteractableRecord(
                    interactable_id="inn_infirmary",
                    space_id=GREYBRIDGE_SAFE_HUB_SPACE_ID,
                    coord={"x": 10, "y": 7},
                    kind="infirmary",
                    state={"building": "inn_infirmary"},
                    metadata={"label": "Inn / Infirmary"},
                ),
                GREYBRIDGE_SAFE_HUB_GATE_ID: InteractableRecord(
                    interactable_id=GREYBRIDGE_SAFE_HUB_GATE_ID,
                    space_id=GREYBRIDGE_SAFE_HUB_SPACE_ID,
                    coord={"x": 1, "y": 5},
                    kind="gate",
                    state={"building": "town_gate"},
                    metadata={"label": "Greybridge Gate / Exit"},
                ),
            }
            sim.state.world.spaces[GREYBRIDGE_SAFE_HUB_SPACE_ID] = safe_hub

        state = sim.get_rules_state(self.name)
        active = state.get("safe_hub_active_by_entity", {})
        if not isinstance(active, dict):
            active = {}
        active[str(entity.entity_id)] = {
            "site_id": site_id,
            "origin_space_id": location.space_id,
            "origin_position": {"x": float(entity.position_x), "y": float(entity.position_y)},
        }
        state["safe_hub_active_by_entity"] = {str(k): v for k, v in sorted(active.items())}
        sim.set_rules_state(self.name, state)

        entity.space_id = GREYBRIDGE_SAFE_HUB_SPACE_ID
        entity.position_x = 2.5
        entity.position_y = 5.5
        self._schedule_safe_hub_outcome(
            sim, tick=command.tick, entity_id=entity.entity_id, action_uid=action_uid, applied=True, reason="entered_safe_hub", details={"site_id": site_id}
        )

    def _handle_exit_safe_hub_intent(self, sim: Simulation, *, command: SimCommand, command_index: int) -> None:
        action_uid = f"safe_hub_exit:{command.tick}:{command_index}"
        entity = sim.state.entities.get(command.entity_id or "")
        if entity is None:
            self._schedule_safe_hub_outcome(
                sim, tick=command.tick, entity_id=command.entity_id, action_uid=action_uid, applied=False, reason="unknown_entity"
            )
            return
        state = sim.get_rules_state(self.name)
        active = state.get("safe_hub_active_by_entity", {})
        context = active.get(entity.entity_id) if isinstance(active, dict) else None
        if entity.space_id != GREYBRIDGE_SAFE_HUB_SPACE_ID:
            self._schedule_safe_hub_outcome(
                sim, tick=command.tick, entity_id=entity.entity_id, action_uid=action_uid, applied=False, reason="not_in_safe_hub"
            )
            return
        if not isinstance(context, dict):
            fallback_origin = self._resolve_safe_hub_origin_fallback(sim=sim)
            if fallback_origin is None:
                self._schedule_safe_hub_outcome(
                    sim, tick=command.tick, entity_id=entity.entity_id, action_uid=action_uid, applied=False, reason="missing_return_context"
                )
                return
            origin_space_id, origin_position = fallback_origin
            outcome_reason = "exited_safe_hub_fallback_origin"
        else:
            origin_space_id = str(context.get("origin_space_id", "overworld"))
            origin_position = context.get("origin_position", {"x": 0.0, "y": 0.0})
            outcome_reason = "exited_safe_hub"
        entity.space_id = origin_space_id
        entity.position_x = float(origin_position.get("x", 0.0))
        entity.position_y = float(origin_position.get("y", 0.0))
        trimmed = {str(k): v for k, v in sorted(active.items()) if k != entity.entity_id}
        state["safe_hub_active_by_entity"] = trimmed
        sim.set_rules_state(self.name, state)
        self._schedule_safe_hub_outcome(
            sim, tick=command.tick, entity_id=entity.entity_id, action_uid=action_uid, applied=True, reason=outcome_reason
        )

    def _handle_loot_local_proof_intent(self, sim: Simulation, *, command: SimCommand, command_index: int) -> None:
        action_uid = f"local_loot:{command.tick}:{command_index}"
        entity = sim.state.entities.get(command.entity_id or "")
        reason = "resolved"
        details: dict[str, Any] = {}
        applied = False
        if entity is None:
            reason = "unknown_entity"
        else:
            space = sim.state.world.spaces.get(entity.space_id)
            if space is None or space.role != "local":
                reason = "local_space_required"
            else:
                container_id = entity.inventory_container_id
                if container_id is None or container_id not in sim.state.world.containers:
                    reason = "no_inventory_container"
                else:
                    hostile = self._nearest_lootable_hostile(sim, entity=entity)
                    if hostile is None:
                        reason = "no_lootable_proof"
                    else:
                        stats = dict(hostile.stats) if isinstance(hostile.stats, dict) else {}
                        stats["proof_looted"] = True
                        hostile.stats = stats
                        sim._execute_inventory_intent(
                            SimCommand(
                                tick=command.tick,
                                entity_id=entity.entity_id,
                                command_type="inventory_intent",
                                params={
                                    "src_container_id": None,
                                    "dst_container_id": container_id,
                                    "item_id": REWARD_TOKEN_ITEM_ID,
                                    "quantity": 1,
                                    "reason": "spawn",
                                    "action_uid": f"{action_uid}:grant",
                                },
                            ),
                            command_index=0,
                        )
                        outcome = self._inventory_outcome_for_action_uid(sim=sim, action_uid=f"{action_uid}:grant")
                        applied = outcome == "applied"
                        reason = "token_looted" if applied else "inventory_rejected"
                        details = {"hostile_id": hostile.entity_id, "inventory_outcome": outcome}

        sim.schedule_event_at(
            tick=command.tick,
            event_type=LOCAL_ENCOUNTER_REWARD_EVENT_TYPE,
            params={
                "tick": int(command.tick),
                "action_uid": action_uid,
                "entity_id": command.entity_id,
                "local_space_id": entity.space_id if entity is not None else None,
                "applied": bool(applied),
                "reason": reason,
                "details": copy.deepcopy(details),
            },
        )


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

        entity = sim.state.entities[command.entity_id]
        location = self._entity_location(sim, entity_id=command.entity_id)
        at_turn_in, site_id, reason = self._is_valid_turn_in_context(sim=sim, entity=entity, location=location)
        if not at_turn_in:
            self._schedule_reward_turn_in_outcome(
                sim,
                tick=command.tick,
                entity_id=command.entity_id,
                action_uid=action_uid,
                applied=False,
                reason=reason,
                location=location,
                details={},
            )
            return

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
                "next_patrol_reason": "Old Stair route filters another band after report.",
            },
        )
        sim.schedule_event_at(
            tick=command.tick + 1,
            event_type=GREYBRIDGE_PATROL_RESPAWN_EVENT_TYPE,
            params={"tick": int(command.tick), "site_id": site_id, "reason": "token_turn_in"},
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

    @staticmethod
    def _nearest_lootable_hostile(sim: Simulation, *, entity: EntityState) -> EntityState | None:
        best: tuple[float, str, EntityState] | None = None
        for candidate in sim.state.entities.values():
            if candidate.space_id != entity.space_id or candidate.entity_id == entity.entity_id:
                continue
            if str(candidate.template_id or "") != "encounter_hostile_v1":
                continue
            if not isinstance(candidate.stats, dict):
                candidate.stats = {}
            if bool(candidate.stats.get("proof_looted", False)):
                continue
            if not is_incapacitated_from_wounds(candidate.wounds, threshold=3):
                continue
            distance = math.dist((entity.position_x, entity.position_y), (candidate.position_x, candidate.position_y))
            if distance > 1.8:
                continue
            row = (distance, candidate.entity_id, candidate)
            if best is None or (row[0], row[1]) < (best[0], best[1]):
                best = row
        return best[2] if best is not None else None

    def _schedule_safe_hub_outcome(
        self,
        sim: Simulation,
        *,
        tick: int,
        entity_id: str | None,
        action_uid: str,
        applied: bool,
        reason: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "tick": int(tick),
            "entity_id": entity_id,
            "action_uid": action_uid,
            "applied": bool(applied),
            "reason": reason,
        }
        if details is not None:
            payload["details"] = copy.deepcopy(details)
        sim.schedule_event_at(tick=tick, event_type=SAFE_HUB_OUTCOME_EVENT_TYPE, params=payload)

    def _handle_greybridge_patrol_respawn(self, sim: Simulation, *, event: SimEvent) -> None:
        existing = sorted(
            entity_id for entity_id, entity in sim.state.entities.items() if str(entity.template_id or "") == GREYBRIDGE_PATROL_TEMPLATE_ID
        )
        for extra_id in existing[1:]:
            sim.state.entities.pop(extra_id, None)
        if existing:
            return
        next_id = DEFAULT_DANGER_ENTITY_ID
        sim.add_entity(
            EntityState(
                entity_id=next_id,
                position_x=GREYBRIDGE_PATROL_SPAWN_X,
                position_y=GREYBRIDGE_PATROL_SPAWN_Y,
                speed_per_tick=0.14,
                template_id=GREYBRIDGE_PATROL_TEMPLATE_ID,
                stats={"faction_id": "hostile", "role": "patrol", "spawn_reason": "old_stair_replacement"},
            )
        )

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

    def _is_valid_recovery_context(
        self,
        *,
        sim: Simulation,
        entity: EntityState,
        location: LocationRef,
    ) -> tuple[bool, str | None, str | None, str]:
        space = sim.state.world.spaces.get(location.space_id)
        if space is None:
            return False, None, None, "invalid_space"
        if space.role == "campaign":
            is_safe_site, site_id, site_type = self._is_safe_recovery_site(sim, location=location)
            if not is_safe_site:
                return False, None, site_type, "safe_site_required"
            return True, site_id, site_type, "accepted"
        if (
            space.role == "local"
            and space.space_id == GREYBRIDGE_SAFE_HUB_SPACE_ID
            and self._is_near_interactable(space, entity=entity, interactable_id="inn_infirmary")
        ):
            return True, GREYBRIDGE_SITE_ID, "town", "accepted"
        return False, None, None, "recovery_building_required"

    def _is_valid_turn_in_context(
        self,
        *,
        sim: Simulation,
        entity: EntityState,
        location: LocationRef,
    ) -> tuple[bool, str | None, str]:
        space = sim.state.world.spaces.get(location.space_id)
        if space is None:
            return False, None, "invalid_space"
        if space.role == "local" and space.space_id == GREYBRIDGE_SAFE_HUB_SPACE_ID:
            if self._is_near_interactable(space, entity=entity, interactable_id="watch_hall"):
                return True, GREYBRIDGE_SITE_ID, "accepted"
            return False, None, "turn_in_building_required"
        return False, None, "greybridge_building_required"

    @staticmethod
    def _is_near_interactable(space: Any, *, entity: EntityState, interactable_id: str) -> bool:
        interactables = getattr(space, "interactables", {})
        if not isinstance(interactables, dict):
            return False
        row = interactables.get(interactable_id)
        if row is None:
            return False
        coord = getattr(row, "coord", {})
        if not isinstance(coord, dict):
            return False
        return math.dist((entity.position_x, entity.position_y), (float(coord.get("x", 0.0)) + 0.5, float(coord.get("y", 0.0)) + 0.5)) <= 1.8

    @staticmethod
    def _resolve_safe_hub_origin_fallback(sim: Simulation) -> tuple[str, dict[str, float]] | None:
        site = sim.state.world.sites.get(GREYBRIDGE_SITE_ID)
        if site is None:
            return None
        location = site.location if isinstance(site.location, dict) else {}
        origin_space_id = location.get("space_id")
        coord = location.get("coord")
        if not isinstance(origin_space_id, str) or not origin_space_id or not isinstance(coord, dict):
            return None
        if "x" in coord and "y" in coord:
            return origin_space_id, {"x": float(coord["x"]) + 0.5, "y": float(coord["y"]) + 0.5}
        if "q" in coord and "r" in coord:
            from hexcrawler.sim.movement import axial_to_world_xy
            from hexcrawler.sim.world import HexCoord

            world_x, world_y = axial_to_world_xy(HexCoord(q=int(coord["q"]), r=int(coord["r"])))
            return origin_space_id, {"x": float(world_x), "y": float(world_y)}
        return None

    @staticmethod
    def _rations_for_entity(*, entity: EntityState, sim: Simulation) -> int:
        container_id = entity.inventory_container_id
        if container_id is None:
            return 0
        container = sim.state.world.containers.get(container_id)
        if container is None:
            return 0
        rations = container.items.get("rations", 0)
        return int(rations) if isinstance(rations, int) and rations > 0 else 0

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


def _wound_severity_total(wounds: Any) -> int:
    if not isinstance(wounds, list):
        return 0
    total = 0
    for wound in wounds:
        if isinstance(wound, dict) and isinstance(wound.get("severity"), int):
            total += int(wound["severity"])
    return total
