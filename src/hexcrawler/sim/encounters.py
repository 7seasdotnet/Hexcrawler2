from __future__ import annotations

import copy
import hashlib
import json
import math
from typing import Any

from hexcrawler.content.encounters import EncounterTable
from hexcrawler.content.local_arenas import DEFAULT_LOCAL_ARENAS_PATH, LocalArenaTemplate, load_local_arena_templates_json
from hexcrawler.sim.core import DEFAULT_PLAYER_ENTITY_ID, EntityState, TRAVEL_STEP_EVENT_TYPE, SimCommand, SimEvent, Simulation
from hexcrawler.sim.groups import GROUP_MOVE_ARRIVED_EVENT_TYPE
from hexcrawler.sim.location import LocationRef, OVERWORLD_HEX_TOPOLOGY, SQUARE_GRID_TOPOLOGY
from hexcrawler.sim.movement import axial_to_world_xy, square_grid_cell_to_world_xy
from hexcrawler.sim.periodic import PeriodicScheduler
from hexcrawler.sim.rules import RuleModule
from hexcrawler.sim.signals import distance_between_locations
from hexcrawler.sim.world import CAMPAIGN_SPACE_ROLE, LOCAL_SPACE_ROLE, MAX_CLAIM_OPPORTUNITIES, RUMOR_KINDS, AnchorRecord, DoorRecord, HexCoord, InteractableRecord, RumorRecord, SpaceState

ENCOUNTER_CHECK_EVENT_TYPE = "encounter_check"
ENCOUNTER_ROLL_EVENT_TYPE = "encounter_roll"
ENCOUNTER_RESULT_STUB_EVENT_TYPE = "encounter_result_stub"
ENCOUNTER_RESOLVE_REQUEST_EVENT_TYPE = "encounter_resolve_request"
ENCOUNTER_SELECTION_STUB_EVENT_TYPE = "encounter_selection_stub"
ENCOUNTER_ACTION_STUB_EVENT_TYPE = "encounter_action_stub"
ENCOUNTER_ACTION_EXECUTE_EVENT_TYPE = "encounter_action_execute"
ENCOUNTER_ACTION_OUTCOME_EVENT_TYPE = "encounter_action_outcome"
LOCAL_ENCOUNTER_REQUEST_EVENT_TYPE = "local_encounter_request"
LOCAL_ENCOUNTER_BEGIN_EVENT_TYPE = "local_encounter_begin"
END_LOCAL_ENCOUNTER_INTENT = "end_local_encounter_intent"
END_LOCAL_ENCOUNTER_OUTCOME_EVENT_TYPE = "end_local_encounter_outcome"
LOCAL_ENCOUNTER_END_EVENT_TYPE = "local_encounter_end"
LOCAL_ENCOUNTER_RETURN_EVENT_TYPE = "local_encounter_return"
LOCAL_ENCOUNTER_REWARD_EVENT_TYPE = "local_encounter_reward"
SITE_STATE_TICK_EVENT_TYPE = "site_state_tick"
SITE_EFFECT_SCHEDULED_EVENT_TYPE = "site_effect_scheduled"
SITE_EFFECT_CONSUMED_EVENT_TYPE = "site_effect_consumed"
SITE_EFFECT_CONSUMPTION_REJECTED_EVENT_TYPE = "site_effect_consumption_rejected"
LOCAL_ARENA_TEMPLATE_APPLIED_EVENT_TYPE = "local_arena_template_applied"
LOCAL_ENCOUNTER_ENEMY_ENTRY_ANCHOR_ID = "enemy_entry"
SPAWN_ENTITY_ID_PREFIX = "spawn"
ENCOUNTER_CHECK_INTERVAL = 10
ENCOUNTER_CONTEXT_GLOBAL = "global"
ENCOUNTER_TRIGGER_IDLE = "idle"
ENCOUNTER_TRIGGER_TRAVEL = "travel"
ENCOUNTER_CHANCE_PERCENT = 20
ENCOUNTER_COOLDOWN_TICKS = 30
RUMOR_PROPAGATION_TASK_NAME = "rumor_pipeline:propagate"
RUMOR_PROPAGATION_INTERVAL_TICKS = 50
RUMOR_HOP_CAP = 4
RUMOR_TTL_TICKS = 200
LOCAL_ENCOUNTER_INSTANCE_LEDGER_MAX = 64
LOCAL_ENCOUNTER_END_LEDGER_MAX = 64
MAX_ACTIVE_LOCAL_ENCOUNTERS = 8
SITE_CHECK_INTERVAL_TICKS = 120
STALE_TICKS = 600
MAX_SITE_CHECKS_PER_TICK = 8
MAX_SITE_STATE_TAGS = 8
MAX_PENDING_EFFECTS_PER_SITE = 8
REINHABITATION_PENDING_EFFECT_TYPE = "reinhabitation_pending"
FORTIFICATION_PENDING_EFFECT_TYPE = "fortification_pending"
STALE_POLICY_EFFECT_SOURCE = "stale_policy"
REHAB_POLICY_REPLACE = "replace"
REHAB_POLICY_ADD = "add"
REHAB_POLICY_ALLOWED = {REHAB_POLICY_REPLACE, REHAB_POLICY_ADD}
INVALID_REHAB_POLICY_DIAGNOSTIC_MAX_LEN = 128
EFFECT_PRIORITY_MIN = -1000
EFFECT_PRIORITY_MAX = 1000
INVALID_EFFECT_PRIORITY_DIAGNOSTIC_MAX_LEN = 128
CLAIM_SITE_INTENT = "claim_site_intent"
CLAIM_SITE_FROM_OPPORTUNITY_INTENT = "claim_site_from_opportunity_intent"
SITE_CLAIM_OUTCOME_EVENT_TYPE = "site_claim_outcome"
GROUP_ARRIVED_AT_SITE_EVENT_TYPE = "group_arrived_at_site"
CLAIM_OPPORTUNITY_CREATED_EVENT_TYPE = "claim_opportunity_created"
CLAIM_OPPORTUNITY_CONSUMED_EVENT_TYPE = "claim_opportunity_consumed"
LIST_RUMORS_INTENT = "list_rumors_intent"
LIST_RUMORS_OUTCOME_KIND = "list_rumors_outcome"
SELECT_RUMORS_INTENT = "select_rumors_intent"
SELECT_RUMORS_OUTCOME_KIND = "select_rumors_outcome"
RUMOR_SELECTION_DECISION_EVENT_TYPE = "rumor_selection_decision"
RUMOR_DECAY_TASK_NAME = "rumor_decay:tick"
RUMOR_DECAY_INTERVAL_TICKS = 1
MAX_RUMOR_DECAY_PROCESSED_PER_TICK = 64
RUMOR_DECAY_TICK_EVENT_TYPE = "rumor_decay_tick"
RUMOR_SELECTION_DEFAULT_SCOPE = CAMPAIGN_SPACE_ROLE
RUMOR_SELECTION_DEFAULT_K = 10
RUMOR_SELECTION_MIN_K = 1
RUMOR_SELECTION_MAX_K = 50
RUMOR_SELECTION_MAX_SEED_TAG_LEN = 64
RUMOR_SELECTION_DEFAULT_SEED_TAG = "default"
RUMOR_SELECTION_RECENCY_HALFLIFE_TICKS = 1000
RUMOR_SELECTION_KIND_BASE_POINTS = {
    "group_arrival": 100,
    "claim_opportunity": 200,
    "site_claim": 300,
}
MAX_CLAIM_SITES_PROCESSED_PER_ARRIVAL = 32
SITE_ECOLOGY_TASK_NAME = "site_ecology:tick"
SITE_ECOLOGY_INTERVAL_DAYS = 1
SITE_ECOLOGY_MAX_PROCESSED_PER_TICK = 64
SITE_GROWTH_LEDGER_MAX = 256
MAX_SITE_ECOLOGY_DECISIONS = 256
SITE_ECOLOGY_SCHEDULED_EFFECT_EVENT_TYPE = "site_ecology_scheduled_effect"
SITE_ECOLOGY_TICK_EVENT_TYPE = "site_ecology_tick"
SITE_ECOLOGY_DECISION_EVENT_TYPE = "site_ecology_decision"
SITE_ECOLOGY_REINFORCE_CHANCE_PERCENT = 35
SITE_ECOLOGY_FORTIFY_CHANCE_PERCENT = 55
SITE_ECOLOGY_D20_SIZE = 20
SITE_ECOLOGY_CONFIG_MAX_RULES = 16
SITE_ECOLOGY_CONFIG_MAX_STEPS_PER_TICK_HARD_CAP = 8
SITE_ECOLOGY_CONFIG_ALLOWED_KINDS = {"chance_marker"}
SITE_ECOLOGY_CONFIG_ALLOWED_MARKER_TYPES = {
    REINHABITATION_PENDING_EFFECT_TYPE,
    FORTIFICATION_PENDING_EFFECT_TYPE,
}
LOCAL_ENCOUNTER_EXIT_PIN_DISTANCE = 1
LOCAL_ENCOUNTER_HOSTILE_TEMPLATE_ID = "encounter_hostile_v1"
LOCAL_REWARD_TOKEN_ITEM_ID = "proof_token"
LOCAL_REWARD_TOKEN_QUANTITY = 1
LOCAL_REWARD_INCAPACITATE_SEVERITY = 3



class EncounterSelectionModule(RuleModule):
    """Phase 4H deterministic encounter table-selection seam.

    Intentionally side-effect free: this module emits descriptive selection stubs
    and does not mutate world state, spawn entities, or schedule combat.
    """

    name = "encounter_selection"
    _RNG_STREAM_NAME = "encounter_selection"

    def __init__(self, table: EncounterTable) -> None:
        self._table = table

    def on_event_executed(self, sim: Simulation, event: SimEvent) -> None:
        if event.event_type != ENCOUNTER_RESOLVE_REQUEST_EVENT_TYPE:
            return
        offer_required = bool(event.params.get("offer_required", False))
        offer_accepted = bool(event.params.get("offer_accepted", False))
        if offer_required and not offer_accepted:
            return

        selected_entry = self._select_entry(sim)
        sim.schedule_event_at(
            tick=event.tick + 1,
            event_type=ENCOUNTER_SELECTION_STUB_EVENT_TYPE,
            params={
                "tick": int(event.params.get("tick", event.tick)),
                "context": event.params["context"],
                "trigger": event.params["trigger"],
                "location": dict(event.params["location"]),
                "roll": int(event.params["roll"]),
                "category": str(event.params["category"]),
                "table_id": self._table.table_id,
                "entry_id": selected_entry.entry_id,
                "entry_payload": copy.deepcopy(selected_entry.payload),
                "entry_tags": list(selected_entry.tags),
            },
        )

    def _select_entry(self, sim: Simulation):
        total_weight = sum(entry.weight for entry in self._table.entries)
        rng = sim.rng_stream(self._RNG_STREAM_NAME)
        draw = rng.randrange(total_weight)
        cumulative = 0
        for entry in self._table.entries:
            cumulative += entry.weight
            if draw < cumulative:
                return entry
        raise RuntimeError("encounter selection failed despite non-empty weighted table")


class EncounterActionModule(RuleModule):
    """Phase 4I declarative encounter action grammar seam.

    Intentionally side-effect free: this module emits descriptive action-intent
    stubs only and does not mutate world state or execute outcomes.
    """

    name = "encounter_action"

    def on_event_executed(self, sim: Simulation, event: SimEvent) -> None:
        if event.event_type != ENCOUNTER_SELECTION_STUB_EVENT_TYPE:
            return

        params = copy.deepcopy(event.params)
        entry_payload = params.get("entry_payload")
        actions = self._actions_for_selection(params.get("entry_id"), entry_payload)
        params["actions"] = actions

        sim.schedule_event_at(
            tick=event.tick + 1,
            event_type=ENCOUNTER_ACTION_STUB_EVENT_TYPE,
            params=params,
        )

    def _actions_for_selection(self, entry_id: Any, entry_payload: Any) -> list[dict[str, Any]]:
        if not isinstance(entry_payload, dict):
            raise ValueError("encounter_selection_stub entry_payload must be an object")

        payload_actions = entry_payload.get("actions")
        if payload_actions is None:
            action_template_id = entry_payload.get("signal_id", entry_id)
            if not isinstance(action_template_id, str) or not action_template_id:
                raise ValueError("encounter action fallback template_id must be a non-empty string")
            actions = [
                {
                    "action_type": "signal_intent",
                    "template_id": action_template_id,
                    "params": {"source": ENCOUNTER_SELECTION_STUB_EVENT_TYPE},
                }
            ]
        else:
            if not isinstance(payload_actions, list):
                raise ValueError("encounter action payload field actions must be a list when present")
            actions = payload_actions

        return self._normalize_actions(actions)

    def _normalize_actions(self, actions: list[Any]) -> list[dict[str, Any]]:
        normalized_actions: list[dict[str, Any]] = []
        for index, action in enumerate(actions):
            if not isinstance(action, dict):
                raise ValueError(f"encounter action intent at actions[{index}] must be an object")

            action_type = action.get("action_type")
            template_id = action.get("template_id", action.get("action_id"))
            if not isinstance(action_type, str) or not action_type:
                raise ValueError(f"encounter action intent at actions[{index}] must contain non-empty action_type")
            if not isinstance(template_id, str) or not template_id:
                raise ValueError(f"encounter action intent at actions[{index}] must contain non-empty template_id")

            params = action.get("params", {})
            if not isinstance(params, dict):
                raise ValueError(f"encounter action intent at actions[{index}] field params must be an object")

            normalized_action: dict[str, Any] = {
                "action_type": action_type,
                "template_id": template_id,
                "params": self._normalize_json_value(params, field_name=f"actions[{index}].params"),
            }

            for key in sorted(action):
                if key in normalized_action or key == "action_id":
                    continue
                normalized_action[key] = self._normalize_json_value(action[key], field_name=f"actions[{index}].{key}")

            normalized_actions.append(normalized_action)

        return normalized_actions

    def _normalize_json_value(self, value: Any, *, field_name: str) -> Any:
        if value is None or isinstance(value, (bool, int, float, str)):
            return value
        if isinstance(value, list):
            return [self._normalize_json_value(item, field_name=field_name) for item in value]
        if isinstance(value, dict):
            normalized: dict[str, Any] = {}
            for key in sorted(value):
                if not isinstance(key, str):
                    raise ValueError(f"{field_name} keys must be strings")
                normalized[key] = self._normalize_json_value(value[key], field_name=field_name)
            return normalized
        raise ValueError(f"{field_name} must contain only JSON-serializable values")


class LocalEncounterRequestModule(RuleModule):
    """Phase 6B seam: campaign encounter requests local tactical resolution."""

    name = "local_encounter_request"

    def on_event_executed(self, sim: Simulation, event: SimEvent) -> None:
        if event.event_type != ENCOUNTER_RESOLVE_REQUEST_EVENT_TYPE:
            return
        offer_required = bool(event.params.get("offer_required", False))
        offer_accepted = bool(event.params.get("offer_accepted", False))
        if offer_required and not offer_accepted:
            return

        from_location_payload = event.params.get("location")
        if not isinstance(from_location_payload, dict):
            return
        from_location = LocationRef.from_dict(from_location_payload)
        from_space = sim.state.world.spaces.get(from_location.space_id)
        if from_space is None or from_space.role != CAMPAIGN_SPACE_ROLE:
            return

        suggested_local_template_id = self._optional_string(event.params.get("suggested_local_template_id"))
        site_key = self._site_key(
            origin_space_id=from_location.space_id,
            origin_coord=copy.deepcopy(from_location.coord),
            template_id=suggested_local_template_id,
            encounter_entry_id=self._optional_string(event.params.get("entry_id")),
        )

        sim.schedule_event_at(
            tick=event.tick + 1,
            event_type=LOCAL_ENCOUNTER_REQUEST_EVENT_TYPE,
            params={
                "tick": int(event.params.get("tick", event.tick)),
                "from_space_id": from_location.space_id,
                "from_location": from_location.to_dict(),
                "context": self._optional_string(event.params.get("context")),
                "trigger": self._optional_string(event.params.get("trigger")),
                "location": copy.deepcopy(event.params.get("location")),
                "roll": self._optional_int(event.params.get("roll")),
                "category": self._optional_string(event.params.get("category")),
                "table_id": self._optional_string(event.params.get("table_id")),
                "entry_id": self._optional_string(event.params.get("entry_id")),
                "encounter": {
                    "table_id": self._optional_string(event.params.get("table_id")),
                    "entry_id": self._optional_string(event.params.get("entry_id")),
                    "category": self._optional_string(event.params.get("category")),
                    "roll": self._optional_int(event.params.get("roll")),
                },
                "suggested_local_template_id": suggested_local_template_id,
                "site_key": site_key,
                "tags": self._normalized_tags(event.params.get("tags")),
            },
        )

    @staticmethod
    def _optional_string(value: Any) -> str | None:
        if value is None:
            return None
        return str(value)

    @staticmethod
    def _optional_int(value: Any) -> int | None:
        if value is None:
            return None
        return int(value)

    @staticmethod
    def _normalized_tags(value: Any) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("local_encounter_request tags must be a list when present")
        return [str(tag) for tag in value]

    @staticmethod
    def _site_key(
        *,
        origin_space_id: str,
        origin_coord: dict[str, Any],
        template_id: str | None,
        encounter_entry_id: str | None,
    ) -> dict[str, Any]:
        resolved_template_id = template_id if isinstance(template_id, str) and template_id else "__default__"
        key = {
            "origin_space_id": origin_space_id,
            "origin_coord": copy.deepcopy(origin_coord),
            "template_id": resolved_template_id,
        }
        if isinstance(encounter_entry_id, str) and encounter_entry_id:
            key["encounter_entry_id"] = encounter_entry_id
        return key


class LocalEncounterInstanceModule(RuleModule):
    """Phase 6C bridge: deterministic local encounter instancing and structural template application.

    Applies to both space roles:
    - campaign role emits `local_encounter_request` upstream.
    - local role is used for deterministic tactical instance creation/reuse here.
    """

    name = "local_encounter_instance"
    _STATE_PROCESSED_REQUEST_IDS = "processed_request_ids"
    _STATE_ACTIVE_BY_LOCAL_SPACE = "active_by_local_space"
    _STATE_PROCESSED_END_ACTION_UIDS = "processed_end_action_uids"
    _STATE_APPLIED_TEMPLATE_BY_LOCAL_SPACE = "applied_template_by_local_space"
    _STATE_RETURN_IN_PROGRESS_BY_LOCAL_SPACE = "return_in_progress_by_local_space"
    _STATE_SITE_KEY_BY_LOCAL_SPACE = "site_key_by_local_space"
    _STATE_SITE_STATE_BY_KEY = "site_state_by_key"
    _SITE_EFFECT_REQUIRED_KEYS = ("effect_type", "created_tick", "source")

    def __init__(self, local_arenas_path: str = DEFAULT_LOCAL_ARENAS_PATH) -> None:
        self._template_by_id: dict[str, LocalArenaTemplate] = {}
        self._default_template_id: str | None = None
        self._load_failure_reason: str | None = None
        try:
            registry = load_local_arena_templates_json(local_arenas_path)
            self._template_by_id = registry.by_id()
            self._default_template_id = registry.default_template_id
        except Exception:
            self._load_failure_reason = "invalid_template_payload"

    def on_simulation_start(self, sim: Simulation) -> None:
        sim.set_rules_state(self.name, self._rules_state(sim))

    def on_tick_start(self, sim: Simulation, tick: int) -> None:
        self._process_site_state_ticks(sim, tick=tick)

    def on_command(self, sim: Simulation, command: SimCommand, command_index: int) -> bool:
        if command.command_type != END_LOCAL_ENCOUNTER_INTENT:
            return False

        action_uid = f"{command.tick}:{command_index}"
        state = self._rules_state(sim)
        processed_end_action_uids = set(state[self._STATE_PROCESSED_END_ACTION_UIDS])
        entity_id_raw = command.params.get("entity_id")
        entity_id = str(entity_id_raw) if isinstance(entity_id_raw, str) else None
        tags = command.params.get("tags", [])
        if not isinstance(tags, list):
            tags = []
        normalized_tags = [str(tag) for tag in tags]

        reason = "resolved"
        applied = False
        local_space_id: str | None = None
        active_context: dict[str, Any] | None = None

        if action_uid in processed_end_action_uids:
            reason = "already_processed"
        elif entity_id is None or entity_id not in sim.state.entities:
            reason = "invalid_entity"
        else:
            entity = sim.state.entities[entity_id]
            space = sim.state.world.spaces.get(entity.space_id)
            if space is None or space.role != LOCAL_SPACE_ROLE:
                reason = "not_in_local_space"
            else:
                local_space_id = entity.space_id
                active_context = state[self._STATE_ACTIVE_BY_LOCAL_SPACE].get(local_space_id)
                if active_context is None:
                    reason = "no_active_local_encounter"
                elif not bool(active_context.get("is_active", True)):
                    reason = "no_active_local_encounter"
                elif state[self._STATE_RETURN_IN_PROGRESS_BY_LOCAL_SPACE].get(local_space_id, False):
                    reason = "already_returning"
                elif not self._is_at_local_return_exit(sim=sim, entity_id=entity_id, active_context=active_context):
                    reason = "not_at_return_exit"
                elif self._is_exit_pinned_by_hostile(sim=sim, entity_id=entity_id):
                    reason = "hostile_adjacent"
                else:
                    origin_location = copy.deepcopy(active_context.get("origin_location"))
                    return_in_progress_by_local_space = dict(state[self._STATE_RETURN_IN_PROGRESS_BY_LOCAL_SPACE])
                    return_in_progress_by_local_space[local_space_id] = True
                    state[self._STATE_RETURN_IN_PROGRESS_BY_LOCAL_SPACE] = {
                        space_id: bool(return_in_progress_by_local_space[space_id])
                        for space_id in sorted(return_in_progress_by_local_space)
                        if bool(return_in_progress_by_local_space[space_id])
                    }
                    sim.set_rules_state(self.name, state)
                    sim.schedule_event_at(
                        tick=command.tick + 1,
                        event_type=LOCAL_ENCOUNTER_END_EVENT_TYPE,
                        params={
                            "tick": int(command.tick),
                            "action_uid": action_uid,
                            "entity_id": entity_id,
                            "local_space_id": local_space_id,
                            "request_event_id": str(active_context["request_event_id"]),
                            "from_space_id": str(active_context["from_space_id"]),
                            "origin_space_id": str(active_context.get("origin_space_id", active_context["from_space_id"])),
                            "origin_location": origin_location,
                            "origin_position": copy.deepcopy(active_context.get("origin_position")),
                            "from_location": copy.deepcopy(active_context["from_location"]),
                            "site_key": copy.deepcopy(active_context.get("site_key")),
                            "tags": list(normalized_tags),
                        },
                    )
                    applied = True

        sim.schedule_event_at(
            tick=command.tick,
            event_type=END_LOCAL_ENCOUNTER_OUTCOME_EVENT_TYPE,
            params={
                "tick": int(command.tick),
                "intent": END_LOCAL_ENCOUNTER_INTENT,
                "action_uid": action_uid,
                "entity_id": entity_id,
                "local_space_id": local_space_id,
                "applied": applied,
                "reason": reason,
                "tags": list(normalized_tags),
            },
        )
        return True

    def on_event_executed(self, sim: Simulation, event: SimEvent) -> None:
        if event.event_type == LOCAL_ENCOUNTER_REQUEST_EVENT_TYPE:
            self._on_local_encounter_request(sim, event)
            return
        if event.event_type != LOCAL_ENCOUNTER_END_EVENT_TYPE:
            return
        self._on_local_encounter_end(sim, event)

    def _on_local_encounter_request(self, sim: Simulation, event: SimEvent) -> None:
        state = self._rules_state(sim)
        processed_ids = list(state[self._STATE_PROCESSED_REQUEST_IDS])
        request_id = str(event.event_id)
        if request_id in processed_ids:
            return

        normalized_site_key = self._normalize_site_key_payload(event.params.get("site_key"))
        if normalized_site_key is None:
            sim.schedule_event_at(
                tick=event.tick,
                event_type=LOCAL_ENCOUNTER_BEGIN_EVENT_TYPE,
                params={
                    "request_event_id": request_id,
                    "from_space_id": str(event.params.get("from_space_id", "")),
                    "to_space_id": None,
                    "entity_id": None,
                    "from_location": copy.deepcopy(event.params.get("from_location")),
                    "to_spawn_coord": None,
                    "transition_applied": False,
                    "reason": "invalid_site_key",
                    "site_key": copy.deepcopy(event.params.get("site_key")),
                },
            )
            processed_ids.append(request_id)
            state[self._STATE_PROCESSED_REQUEST_IDS] = processed_ids[-LOCAL_ENCOUNTER_INSTANCE_LEDGER_MAX:]
            sim.set_rules_state(self.name, state)
            return

        active_by_local_space = dict(state[self._STATE_ACTIVE_BY_LOCAL_SPACE])
        site_key_by_local_space = dict(state[self._STATE_SITE_KEY_BY_LOCAL_SPACE])
        site_state_by_key = dict(state[self._STATE_SITE_STATE_BY_KEY])
        local_space_id = self._local_space_id_for_site_key(site_key_by_local_space, normalized_site_key)
        if local_space_id is None and len([ctx for ctx in active_by_local_space.values() if bool(ctx.get("is_active", True))]) >= MAX_ACTIVE_LOCAL_ENCOUNTERS:
            sim.schedule_event_at(
                tick=event.tick,
                event_type=LOCAL_ENCOUNTER_BEGIN_EVENT_TYPE,
                params={
                    "request_event_id": request_id,
                    "from_space_id": str(event.params.get("from_space_id", "")),
                    "to_space_id": None,
                    "entity_id": None,
                    "from_location": copy.deepcopy(event.params.get("from_location")),
                    "to_spawn_coord": None,
                    "transition_applied": False,
                    "reason": "active_local_encounter_cap_reached",
                    "site_key": copy.deepcopy(normalized_site_key),
                },
            )
            processed_ids.append(request_id)
            state[self._STATE_PROCESSED_REQUEST_IDS] = processed_ids[-LOCAL_ENCOUNTER_INSTANCE_LEDGER_MAX:]
            sim.set_rules_state(self.name, state)
            return

        from_space_id = str(event.params.get("from_space_id", ""))
        reused_existing = local_space_id is not None
        if local_space_id is None:
            local_space_id = f"local_encounter:{request_id}"
        local_space = sim.state.world.spaces.get(local_space_id)
        if reused_existing and local_space is None:
            sim.schedule_event_at(
                tick=event.tick,
                event_type=LOCAL_ENCOUNTER_BEGIN_EVENT_TYPE,
                params={
                    "request_event_id": request_id,
                    "from_space_id": from_space_id,
                    "to_space_id": None,
                    "entity_id": None,
                    "from_location": copy.deepcopy(event.params.get("from_location")),
                    "to_spawn_coord": None,
                    "transition_applied": False,
                    "reason": "invalid_reuse_state_missing_space",
                    "site_key": copy.deepcopy(normalized_site_key),
                },
            )
            processed_ids.append(request_id)
            state[self._STATE_PROCESSED_REQUEST_IDS] = processed_ids[-LOCAL_ENCOUNTER_INSTANCE_LEDGER_MAX:]
            sim.set_rules_state(self.name, state)
            return
        if local_space is None:
            local_space = SpaceState(
                space_id=local_space_id,
                topology_type=SQUARE_GRID_TOPOLOGY,
                role=LOCAL_SPACE_ROLE,
                topology_params={
                    "width": 10,
                    "height": 10,
                    "origin": {"x": 0, "y": 0},
                },
            )
            sim.state.world.spaces[local_space_id] = local_space

        if reused_existing:
            consumption_result = self._consume_pending_site_effect_for_entry(
                site_key=normalized_site_key,
                site_state_by_key=site_state_by_key,
            )
        else:
            consumption_result = {"status": "none"}

        template_id, selection_reason = self._select_template(event.params)
        applied_template_map = dict(state[self._STATE_APPLIED_TEMPLATE_BY_LOCAL_SPACE])
        template_applied, template_reason = self._apply_template(
            local_space=local_space,
            local_space_id=local_space_id,
            template_id=template_id,
            applied_template_map=applied_template_map,
            selection_reason=selection_reason,
        )
        if template_applied:
            applied_template_map[local_space_id] = template_id

        request_event_id = str(event.event_id)
        entity_id = self._select_entity_id(sim=sim, from_space_id=from_space_id)
        transition_applied = False
        placement_reason = "resolved"
        resolved_spawn_coord, placement_rule = self._resolve_entry_placement(local_space)
        participant_spawn_records: list[dict[str, Any]] = []
        participant_entities: list[EntityState] = []
        participant_remove_ids: list[str] = []
        participant_reason = "resolved"
        from_location_payload = event.params.get("from_location")
        origin_position: dict[str, float] | None = None
        transition_plan: dict[str, Any] | None = None
        to_spawn_coord: dict[str, int] | None = None
        if entity_id is not None and resolved_spawn_coord is not None:
            entity = sim.state.entities[entity_id]
            origin_position = {"x": float(entity.position_x), "y": float(entity.position_y)}
            from_location_payload = sim._entity_location_ref(entity).to_dict()
            spawn_entity_id = f"encounter_participant:{request_event_id}:0"
            participant_coord, participant_placement_rule = self._resolve_participant_placement(
                local_space=local_space,
                occupied_coords=(resolved_spawn_coord,),
            )
            if spawn_entity_id in sim.state.entities:
                participant_reason = "local_encounter_participant_id_conflict"
            elif participant_coord is None:
                participant_reason = "local_encounter_participant_placement_failed"
            else:
                try:
                    next_x, next_y = sim._coord_to_world_xy(space=local_space, coord=resolved_spawn_coord)
                    spawn_x, spawn_y = sim._coord_to_world_xy(space=local_space, coord=participant_coord)
                except (KeyError, TypeError, ValueError):
                    participant_reason = "local_encounter_participant_placement_failed"
                else:
                    if reused_existing and spawn_entity_id in sim.state.entities:
                        participant_reason = "local_encounter_participant_id_conflict"
                        to_spawn_coord = copy.deepcopy(resolved_spawn_coord)
                    elif reused_existing:
                        existing_participant_ids = self._hostile_participant_ids_for_space(
                            sim=sim,
                            local_space_id=local_space.space_id,
                        )
                        if consumption_result["status"] == "rejected":
                            participant_reason = str(consumption_result.get("reason", "site_effect_rejected"))
                        elif consumption_result["status"] == "consumed":
                            consumed_effect_type = str(consumption_result.get("effect_type", ""))
                            if consumed_effect_type == REINHABITATION_PENDING_EFFECT_TYPE:
                                rehab_policy = str(consumption_result.get("rehab_policy", REHAB_POLICY_REPLACE))
                                if rehab_policy == REHAB_POLICY_REPLACE:
                                    replacement = self._apply_reinhabitation_replace(
                                        sim=sim,
                                        local_space=local_space,
                                        site_key=normalized_site_key,
                                        generation=int(consumption_result["generation_after"]),
                                        occupied_coords=(resolved_spawn_coord,),
                                    )
                                    if replacement is None:
                                        participant_reason = "reinhabitation_replace_failed"
                                        consumption_result = {"status": "rejected", "reason": "participant_replace_failed"}
                                    else:
                                        participant_spawn_records = replacement["spawn_records"]
                                        participant_entities = replacement["spawn_entities"]
                                        participant_remove_ids = replacement["remove_ids"]
                                elif rehab_policy == REHAB_POLICY_ADD:
                                    replacement = self._apply_reinhabitation_add(
                                        sim=sim,
                                        local_space=local_space,
                                        site_key=normalized_site_key,
                                        generation=int(consumption_result["generation_after"]),
                                        occupied_coords=(resolved_spawn_coord,),
                                    )
                                    if replacement is None:
                                        participant_reason = "reinhabitation_add_failed"
                                        consumption_result = {"status": "rejected", "reason": "participant_add_failed"}
                                    else:
                                        participant_spawn_records = replacement["spawn_records"]
                                        participant_entities = replacement["spawn_entities"]
                                        participant_remove_ids = replacement["remove_ids"]
                                else:
                                    participant_reason = "invalid_rehab_policy"
                                    consumption_result = {"status": "rejected", "reason": "invalid_rehab_policy"}
                            elif consumed_effect_type == FORTIFICATION_PENDING_EFFECT_TYPE:
                                participant_spawn_records = [
                                    {
                                        "entity_id": participant_id,
                                        "coord": copy.deepcopy(sim._entity_location_ref(sim.state.entities[participant_id]).coord),
                                        "placement_rule": "reuse_existing",
                                    }
                                    for participant_id in existing_participant_ids
                                ]
                            else:
                                participant_reason = "unsupported_site_effect_type"
                                consumption_result = {"status": "rejected", "reason": "unsupported_site_effect_type"}
                        else:
                            participant_spawn_records = [
                                {
                                    "entity_id": participant_id,
                                    "coord": copy.deepcopy(sim._entity_location_ref(sim.state.entities[participant_id]).coord),
                                    "placement_rule": "reuse_existing",
                                }
                                for participant_id in existing_participant_ids
                            ]
                        if participant_reason == "resolved":
                            transition_plan = {
                                "actor_space_id": local_space.space_id,
                                "actor_position": {"x": next_x, "y": next_y},
                                "to_spawn_coord": copy.deepcopy(resolved_spawn_coord),
                            }
                    else:
                        participant_entities.append(
                            EntityState(
                                entity_id=spawn_entity_id,
                                position_x=spawn_x,
                                position_y=spawn_y,
                                space_id=local_space.space_id,
                                template_id="encounter_hostile_v1",
                                source_action_uid=self._optional_non_empty_string(event.params.get("action_uid")),
                            )
                        )
                        participant_spawn_records.append(
                            {
                                "entity_id": spawn_entity_id,
                                "coord": copy.deepcopy(participant_coord),
                                "placement_rule": participant_placement_rule,
                            }
                        )
                        transition_plan = {
                            "actor_space_id": local_space.space_id,
                            "actor_position": {"x": next_x, "y": next_y},
                            "to_spawn_coord": copy.deepcopy(resolved_spawn_coord),
                        }

        elif resolved_spawn_coord is None:
            placement_reason = "local_encounter_entry_placement_failed"
            to_spawn_coord = None
        else:
            to_spawn_coord = copy.deepcopy(resolved_spawn_coord)

        if placement_reason == "resolved" and participant_reason != "resolved":
            placement_reason = participant_reason
            transition_applied = False
            participant_spawn_records = []
            participant_entities = []
            participant_remove_ids = []
            transition_plan = None

        if placement_reason == "resolved" and transition_plan is not None and entity_id is not None:
            entity = sim.state.entities[entity_id]
            sim.stop_entity(entity_id)
            entity.space_id = transition_plan["actor_space_id"]
            entity.position_x = float(transition_plan["actor_position"]["x"])
            entity.position_y = float(transition_plan["actor_position"]["y"])
            to_spawn_coord = copy.deepcopy(transition_plan["to_spawn_coord"])
            if reused_existing and consumption_result["status"] == "consumed":
                for participant_id in participant_remove_ids:
                    sim.state.entities.pop(participant_id, None)
                site_state_by_key = consumption_result["site_state_by_key"]
            transition_applied = True
        elif placement_reason == "resolved" and to_spawn_coord is None:
            to_spawn_coord = copy.deepcopy(resolved_spawn_coord)

        if transition_applied:
            for participant in participant_entities:
                sim.add_entity(participant)

        sim.schedule_event_at(
            tick=event.tick,
            event_type=LOCAL_ARENA_TEMPLATE_APPLIED_EVENT_TYPE,
            params={
                "tick": int(event.tick),
                "request_event_id": request_id,
                "local_space_id": local_space_id,
                "template_id": template_id,
                "applied": template_applied,
                "reason": template_reason,
            },
        )

        if consumption_result["status"] == "consumed":
            sim.schedule_event_at(
                tick=event.tick,
                event_type=SITE_EFFECT_CONSUMED_EVENT_TYPE,
                params={
                    "site_key": copy.deepcopy(normalized_site_key),
                    "effect_type": str(consumption_result.get("effect_type", "")),
                    "source": "entry_policy",
                    "generation_after": int(consumption_result["generation_after"]),
                    "rehab_policy": str(consumption_result.get("rehab_policy", REHAB_POLICY_REPLACE)),
                    "fortified": bool(consumption_result.get("fortified", False)),
                    "index": int(consumption_result.get("index", 0)),
                    "priority": int(consumption_result.get("priority", 0)),
                    "tick": int(event.tick),
                },
            )
            self._emit_site_effect_diagnostics(
                sim=sim,
                tick=int(event.tick),
                site_key=normalized_site_key,
                diagnostics=consumption_result.get("diagnostics", []),
            )
        elif consumption_result["status"] == "none":
            self._emit_site_effect_diagnostics(
                sim=sim,
                tick=int(event.tick),
                site_key=normalized_site_key,
                diagnostics=consumption_result.get("diagnostics", []),
            )
        elif consumption_result["status"] == "rejected":
            rejection_params = {
                "site_key": copy.deepcopy(normalized_site_key),
                "source": "entry_policy",
                "reason": str(consumption_result["reason"]),
                "tick": int(event.tick),
            }
            invalid_rehab_policy_value = consumption_result.get("invalid_rehab_policy_value")
            if isinstance(invalid_rehab_policy_value, str):
                rejection_params["invalid_rehab_policy_value"] = invalid_rehab_policy_value
            index = consumption_result.get("index")
            if isinstance(index, int):
                rejection_params["index"] = int(index)
            priority = consumption_result.get("priority")
            if isinstance(priority, int):
                rejection_params["priority"] = int(priority)
            effect_type = consumption_result.get("effect_type")
            if isinstance(effect_type, str) and effect_type:
                rejection_params["effect_type"] = effect_type
            invalid_priority_value = consumption_result.get("invalid_priority_value")
            if isinstance(invalid_priority_value, str):
                rejection_params["invalid_priority_value"] = invalid_priority_value
            sim.schedule_event_at(
                tick=event.tick,
                event_type=SITE_EFFECT_CONSUMPTION_REJECTED_EVENT_TYPE,
                params=rejection_params,
            )

        sim.schedule_event_at(
            tick=event.tick,
            event_type=LOCAL_ENCOUNTER_BEGIN_EVENT_TYPE,
            params={
                "request_event_id": request_id,
                "from_space_id": from_space_id,
                "to_space_id": local_space_id,
                "entity_id": entity_id,
                "from_location": copy.deepcopy(from_location_payload),
                "to_spawn_coord": copy.deepcopy(to_spawn_coord),
                "transition_applied": transition_applied,
                "applied": transition_applied,
                "reason": placement_reason,
                "tick": int(event.tick),
                "action_uid": self._optional_non_empty_string(event.params.get("action_uid")),
                "space_id": from_space_id,
                "template_id": template_id,
                "template_selection_reason": selection_reason,
                "placement_rule": placement_rule,
                "return_exit_coord": copy.deepcopy(to_spawn_coord),
                "spawned_entities": copy.deepcopy(participant_spawn_records),
                "reuse": reused_existing,
                "site_key": copy.deepcopy(normalized_site_key),
                "encounter_context_passthrough": self._encounter_passthrough_blob(event.params),
            },
        )

        if transition_applied and entity_id is not None and isinstance(from_location_payload, dict):
            origin_location = self._normalize_origin_location_payload(
                origin_space_id=from_space_id,
                origin_location_payload=from_location_payload,
                legacy_coord=from_location_payload.get("coord"),
            )
            if origin_location is None:
                origin_location = sim._entity_location_ref(sim.state.entities[entity_id]).to_dict()
            active_by_local_space[local_space_id] = {
                "request_event_id": request_id,
                "entity_id": entity_id,
                "from_space_id": from_space_id,
                "origin_space_id": from_space_id,
                "from_location": copy.deepcopy(from_location_payload),
                "origin_location": copy.deepcopy(origin_location),
                "origin_position": copy.deepcopy(origin_position),
                "encounter_return_context": {
                    "origin_space_id": from_space_id,
                    "origin_location": copy.deepcopy(origin_location),
                    "origin_position": copy.deepcopy(origin_position),
                },
                "return_spawn_coord": copy.deepcopy(from_location_payload.get("coord", {})),
                "return_exit_coord": copy.deepcopy(to_spawn_coord),
                "encounter_participant_entity_ids": [
                    str(row.get("entity_id"))
                    for row in participant_spawn_records
                    if isinstance(row, dict) and isinstance(row.get("entity_id"), str) and row.get("entity_id")
                ],
                "started_tick": int(event.tick),
                "site_key": copy.deepcopy(normalized_site_key),
                "is_active": True,
                "last_active_tick": int(event.tick),
            }
            site_key_by_local_space[local_space_id] = copy.deepcopy(normalized_site_key)
            site_state_by_key = self._upsert_site_state(
                site_state_by_key=site_state_by_key,
                site_key=normalized_site_key,
                status="active",
                last_active_tick=int(event.tick),
                next_check_tick=int(event.tick) + SITE_CHECK_INTERVAL_TICKS,
            )

        ordered_space_ids = sorted(active_by_local_space.keys())
        state[self._STATE_ACTIVE_BY_LOCAL_SPACE] = {
            space_id: active_by_local_space[space_id] for space_id in ordered_space_ids[-MAX_ACTIVE_LOCAL_ENCOUNTERS:]
        }
        state[self._STATE_APPLIED_TEMPLATE_BY_LOCAL_SPACE] = {
            space_id: applied_template_map[space_id] for space_id in sorted(applied_template_map)
        }
        state[self._STATE_SITE_KEY_BY_LOCAL_SPACE] = {
            space_id: copy.deepcopy(site_key_by_local_space[space_id])
            for space_id in sorted(site_key_by_local_space)
            if isinstance(space_id, str) and space_id and isinstance(site_key_by_local_space[space_id], dict)
        }
        state[self._STATE_SITE_STATE_BY_KEY] = dict(sorted(site_state_by_key.items()))
        processed_ids.append(request_id)
        state[self._STATE_PROCESSED_REQUEST_IDS] = processed_ids[-LOCAL_ENCOUNTER_INSTANCE_LEDGER_MAX:]
        sim.set_rules_state(self.name, state)

    def _select_template(self, params: dict[str, Any]) -> tuple[str, str]:
        suggested = params.get("suggested_local_template_id")
        suggested_id = str(suggested) if isinstance(suggested, str) and suggested else None
        if suggested_id is not None and suggested_id in self._template_by_id:
            return suggested_id, "suggested"
        if self._default_template_id and self._default_template_id in self._template_by_id:
            if suggested_id is not None:
                return self._default_template_id, "unknown_template"
            return self._default_template_id, "default"
        if self._load_failure_reason is not None:
            return "__fallback_minimal__", self._load_failure_reason
        return "__fallback_minimal__", "missing_default"

    def _apply_template(
        self,
        *,
        local_space: SpaceState,
        local_space_id: str,
        template_id: str,
        applied_template_map: dict[str, str],
        selection_reason: str,
    ) -> tuple[bool, str]:
        if applied_template_map.get(local_space_id) == template_id:
            return False, "already_applied"
        if template_id == "__fallback_minimal__":
            self._apply_minimal_fallback(local_space)
            return True, selection_reason
        template = self._template_by_id.get(template_id)
        if template is None:
            self._apply_minimal_fallback(local_space)
            return True, "unknown_template"
        self._apply_structural_template(local_space=local_space, template=template)
        return True, "applied"

    def _apply_structural_template(self, *, local_space: SpaceState, template: LocalArenaTemplate) -> None:
        local_space.topology_type = template.topology_type
        local_space.role = LOCAL_SPACE_ROLE
        local_space.topology_params = copy.deepcopy(dict(template.topology_params))
        local_space.anchors = {}
        for anchor in template.anchors:
            anchor_id = str(anchor["anchor_id"])
            metadata = copy.deepcopy(dict(anchor.get("metadata", {})))
            metadata["tags"] = list(anchor.get("tags", []))
            local_space.anchors[anchor_id] = AnchorRecord(
                anchor_id=anchor_id,
                space_id=local_space.space_id,
                coord=copy.deepcopy(dict(anchor["coord"])),
                kind="transition",
                target={"type": "space", "space_id": local_space.space_id},
                metadata=metadata,
            )

        local_space.doors = {}
        for row in template.doors:
            payload = dict(row)
            door_id = str(payload.get("door_id", ""))
            if not door_id:
                continue
            payload["door_id"] = door_id
            payload["space_id"] = local_space.space_id
            local_space.doors[door_id] = DoorRecord.from_dict(payload)

        local_space.interactables = {}
        for row in template.interactables:
            payload = dict(row)
            interactable_id = str(payload.get("interactable_id", ""))
            if not interactable_id:
                continue
            payload["interactable_id"] = interactable_id
            payload["space_id"] = local_space.space_id
            local_space.interactables[interactable_id] = InteractableRecord.from_dict(payload)

    def _apply_minimal_fallback(self, local_space: SpaceState) -> None:
        local_space.topology_type = SQUARE_GRID_TOPOLOGY
        local_space.role = LOCAL_SPACE_ROLE
        local_space.topology_params = {"width": 8, "height": 8, "origin": {"x": 0, "y": 0}}
        local_space.doors = {}
        local_space.interactables = {}
        local_space.anchors = {
            "entry": AnchorRecord(
                anchor_id="entry",
                space_id=local_space.space_id,
                coord={"x": 0, "y": 0},
                kind="transition",
                target={"type": "space", "space_id": local_space.space_id},
                metadata={"tags": ["entry"], "fallback": True},
            )
        }


    @staticmethod
    def _resolve_entry_placement(local_space: SpaceState) -> tuple[dict[str, int] | None, str]:
        entry = local_space.anchors.get("entry")
        if entry is not None and local_space.is_valid_cell(entry.coord):
            return copy.deepcopy(entry.coord), "entry_anchor"

        fallback = local_space.default_spawn_coord()
        if local_space.is_valid_cell(fallback):
            return copy.deepcopy(fallback), "default_spawn"

        return None, "unresolved"

    @staticmethod
    def _resolve_participant_placement(
        *, local_space: SpaceState, occupied_coords: tuple[dict[str, int], ...]
    ) -> tuple[dict[str, int] | None, str]:
        enemy_anchor = local_space.anchors.get(LOCAL_ENCOUNTER_ENEMY_ENTRY_ANCHOR_ID)
        if enemy_anchor is not None and local_space.is_valid_cell(enemy_anchor.coord):
            if all(enemy_anchor.coord != occupied for occupied in occupied_coords):
                return copy.deepcopy(enemy_anchor.coord), "enemy_entry_anchor"

        cells = local_space.iter_cells()
        for coord in reversed(cells):
            if not local_space.is_valid_cell(coord):
                continue
            if any(coord == occupied for occupied in occupied_coords):
                continue
            return copy.deepcopy(coord), "enemy_fallback_last_cell"
        return None, "unresolved"

    @staticmethod
    def _optional_non_empty_string(value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        normalized = value.strip()
        if not normalized:
            return None
        return normalized

    def _encounter_passthrough_blob(self, params: dict[str, Any]) -> dict[str, Any]:
        blob = {
            "tick": params.get("tick"),
            "context": params.get("context"),
            "trigger": params.get("trigger"),
            "location": params.get("location"),
            "roll": params.get("roll"),
            "category": params.get("category"),
            "table_id": params.get("table_id"),
            "entry_id": params.get("entry_id"),
            "tags": params.get("tags"),
        }
        return json.loads(json.dumps(blob, sort_keys=True))

    def _on_local_encounter_end(self, sim: Simulation, event: SimEvent) -> None:
        state = self._rules_state(sim)
        action_uid = str(event.params.get("action_uid", ""))
        if not action_uid:
            raise ValueError("local_encounter_end action_uid must be a non-empty string")

        processed = list(state[self._STATE_PROCESSED_END_ACTION_UIDS])
        if action_uid in processed:
            return

        local_space_id = str(event.params.get("local_space_id", ""))
        active_by_local_space = dict(state[self._STATE_ACTIVE_BY_LOCAL_SPACE])
        return_in_progress_by_local_space = dict(state[self._STATE_RETURN_IN_PROGRESS_BY_LOCAL_SPACE])
        site_state_by_key = dict(state[self._STATE_SITE_STATE_BY_KEY])
        context = active_by_local_space.get(local_space_id)
        entity_id = str(event.params.get("entity_id", "")) if isinstance(event.params.get("entity_id"), str) else None
        applied = False
        reason = "resolved"
        to_space_id = None
        to_coord = None
        restore_mode = "derived_coord_fallback"
        actor_space_id_before = None
        actor_space_id_after = None
        origin_space_id = str(event.params.get("origin_space_id", "")) if isinstance(event.params.get("origin_space_id"), str) else None

        if entity_id is not None and entity_id in sim.state.entities:
            actor_space_id_before = str(sim.state.entities[entity_id].space_id)

        if context is None:
            reason = "no_active_local_encounter"
        elif entity_id is None or entity_id not in sim.state.entities:
            reason = "invalid_entity"
        else:
            return_context = context.get("encounter_return_context") if isinstance(context.get("encounter_return_context"), dict) else None
            if return_context is None:
                fallback_space_id = str(context.get("origin_space_id", context["from_space_id"]))
                normalized_origin = self._normalize_origin_location_payload(
                    origin_space_id=fallback_space_id,
                    origin_location_payload=context.get("origin_location"),
                    legacy_coord=context.get("return_spawn_coord"),
                )
                exact_origin_position = self._normalize_origin_position_payload(
                    origin_position_payload=context.get("origin_position"),
                )
            else:
                fallback_space_id = str(return_context.get("origin_space_id", context.get("origin_space_id", context["from_space_id"])))
                normalized_origin = self._normalize_origin_location_payload(
                    origin_space_id=fallback_space_id,
                    origin_location_payload=return_context.get("origin_location"),
                    legacy_coord=None,
                )
                exact_origin_position = self._normalize_origin_position_payload(
                    origin_position_payload=return_context.get("origin_position"),
                )

            to_space_id = str(normalized_origin.get("space_id", fallback_space_id)) if normalized_origin is not None else fallback_space_id
            to_space = sim.state.world.spaces.get(to_space_id)
            if to_space is None:
                reason = "invalid_from_space"
            elif normalized_origin is None:
                reason = "invalid_origin_location_for_space"
            elif not sim._topology_compatible(
                space_topology=to_space.topology_type,
                location_topology=str(normalized_origin["topology_type"]),
            ):
                reason = "invalid_origin_location_for_space"
            else:
                to_coord = copy.deepcopy(normalized_origin["coord"])
                try:
                    next_x, next_y = sim._coord_to_world_xy(space=to_space, coord=to_coord)
                except (KeyError, TypeError, ValueError):
                    reason = "invalid_origin_location_for_space"
                else:
                    entity = sim.state.entities[entity_id]
                    if exact_origin_position is None:
                        exact_origin_position = self._normalize_origin_position_payload(
                            origin_position_payload=context.get("origin_position"),
                        )
                    if (
                        exact_origin_position is not None
                        and sim._position_is_within_world(
                            exact_origin_position["x"],
                            exact_origin_position["y"],
                            space_id=to_space_id,
                        )
                    ):
                        entity.space_id = to_space_id
                        entity.position_x = float(exact_origin_position["x"])
                        entity.position_y = float(exact_origin_position["y"])
                        restore_mode = "exact_position"
                    else:
                        entity.space_id = to_space_id
                        entity.position_x = next_x
                        entity.position_y = next_y
                        restore_mode = "derived_coord_fallback"
                    to_coord = copy.deepcopy(sim._entity_location_ref(entity).coord)
                    applied = True
                    actor_space_id_after = str(entity.space_id)

        if actor_space_id_after is None:
            actor_space_id_after = actor_space_id_before

        if context is not None:
            preserved_context = copy.deepcopy(context)
            preserved_context["is_active"] = False
            preserved_context["last_active_tick"] = int(event.tick)
            active_by_local_space[local_space_id] = preserved_context
            normalized_site_key = self._normalize_site_key_payload(preserved_context.get("site_key"))
            if normalized_site_key is not None:
                site_state_by_key = self._upsert_site_state(
                    site_state_by_key=site_state_by_key,
                    site_key=normalized_site_key,
                    status="inactive",
                    last_active_tick=int(event.tick),
                    next_check_tick=int(event.tick) + SITE_CHECK_INTERVAL_TICKS,
                )
        if local_space_id in return_in_progress_by_local_space:
            del return_in_progress_by_local_space[local_space_id]

        processed.append(action_uid)
        state[self._STATE_ACTIVE_BY_LOCAL_SPACE] = active_by_local_space
        state[self._STATE_PROCESSED_END_ACTION_UIDS] = processed[-LOCAL_ENCOUNTER_END_LEDGER_MAX:]
        state[self._STATE_RETURN_IN_PROGRESS_BY_LOCAL_SPACE] = {
            space_id: bool(return_in_progress_by_local_space[space_id])
            for space_id in sorted(return_in_progress_by_local_space)
            if bool(return_in_progress_by_local_space[space_id])
        }
        state[self._STATE_SITE_STATE_BY_KEY] = dict(sorted(site_state_by_key.items()))
        sim.set_rules_state(self.name, state)

        reward_outcome = self._grant_local_reward_token(
            sim=sim,
            tick=event.tick,
            action_uid=action_uid,
            entity_id=entity_id,
            local_space_id=local_space_id,
            encounter_participant_entity_ids=context.get("encounter_participant_entity_ids", []) if isinstance(context, dict) else [],
            return_applied=applied,
        )

        sim.schedule_event_at(
            tick=event.tick,
            event_type=LOCAL_ENCOUNTER_RETURN_EVENT_TYPE,
            params={
                "tick": int(event.tick),
                "action_uid": action_uid,
                "entity_id": entity_id,
                "actor_id": entity_id,
                "request_event_id": str(event.params.get("request_event_id", "")),
                "local_space_id": local_space_id,
                "origin_space_id": origin_space_id,
                "site_key": copy.deepcopy(event.params.get("site_key")),
                "from_space_id": local_space_id,
                "to_space_id": to_space_id,
                "actor_space_id_before": actor_space_id_before,
                "actor_space_id_after": actor_space_id_after,
                "from_location": copy.deepcopy(event.params.get("from_location")),
                "to_coord": to_coord,
                "restore_mode": restore_mode,
                "applied": applied,
                "reason": reason,
                "space_persisted": True,
                "tags": [str(tag) for tag in event.params.get("tags", [])] if isinstance(event.params.get("tags"), list) else [],
            },
        )
        sim.schedule_event_at(
            tick=event.tick,
            event_type=LOCAL_ENCOUNTER_REWARD_EVENT_TYPE,
            params={
                "tick": int(event.tick),
                "action_uid": action_uid,
                "entity_id": entity_id,
                "local_space_id": local_space_id,
                "applied": bool(reward_outcome["applied"]),
                "reason": str(reward_outcome["reason"]),
                "details": copy.deepcopy(reward_outcome.get("details", {})),
            },
        )

    def _grant_local_reward_token(
        self,
        *,
        sim: Simulation,
        tick: int,
        action_uid: str,
        entity_id: str | None,
        local_space_id: str,
        encounter_participant_entity_ids: list[Any],
        return_applied: bool,
    ) -> dict[str, Any]:
        if not return_applied:
            return {"applied": False, "reason": "return_not_applied", "details": {}}
        if entity_id is None or entity_id not in sim.state.entities:
            return {"applied": False, "reason": "invalid_entity", "details": {}}

        incapacitated_count = self._count_incapacitated_hostiles(
            sim=sim,
            local_space_id=local_space_id,
            encounter_participant_entity_ids=encounter_participant_entity_ids,
        )
        if incapacitated_count <= 0:
            return {
                "applied": False,
                "reason": "no_incapacitated_hostile",
                "details": {"incapacitated_hostiles": 0},
            }

        entity = sim.state.entities[entity_id]
        container_id = entity.inventory_container_id
        if container_id is None or container_id not in sim.state.world.containers:
            return {
                "applied": False,
                "reason": "no_inventory_container",
                "details": {"incapacitated_hostiles": incapacitated_count},
            }

        reward_action_uid = f"local_reward_token:{action_uid}"
        sim._execute_inventory_intent(
            SimCommand(
                tick=tick,
                entity_id=entity_id,
                command_type="inventory_intent",
                params={
                    "src_container_id": None,
                    "dst_container_id": container_id,
                    "item_id": LOCAL_REWARD_TOKEN_ITEM_ID,
                    "quantity": LOCAL_REWARD_TOKEN_QUANTITY,
                    "reason": "spawn",
                    "action_uid": reward_action_uid,
                },
            ),
            command_index=0,
        )

        inventory_outcome = self._inventory_outcome_for_action_uid(sim=sim, action_uid=reward_action_uid)
        if inventory_outcome == "applied":
            return {
                "applied": True,
                "reason": "token_granted",
                "details": {
                    "item_id": LOCAL_REWARD_TOKEN_ITEM_ID,
                    "quantity": LOCAL_REWARD_TOKEN_QUANTITY,
                    "incapacitated_hostiles": incapacitated_count,
                },
            }
        if inventory_outcome == "already_applied":
            return {
                "applied": False,
                "reason": "already_processed",
                "details": {"incapacitated_hostiles": incapacitated_count},
            }
        return {
            "applied": False,
            "reason": "inventory_rejected",
            "details": {
                "inventory_outcome": inventory_outcome,
                "incapacitated_hostiles": incapacitated_count,
            },
        }

    @staticmethod
    def _inventory_outcome_for_action_uid(*, sim: Simulation, action_uid: str) -> str:
        for entry in reversed(sim.state.event_trace):
            if entry.get("event_type") != "inventory_outcome":
                continue
            params = entry.get("params")
            if not isinstance(params, dict):
                continue
            if params.get("action_uid") != action_uid:
                continue
            outcome = params.get("outcome")
            if isinstance(outcome, str):
                return outcome
        return "missing_outcome"

    @staticmethod
    def _count_incapacitated_hostiles(
        *,
        sim: Simulation,
        local_space_id: str,
        encounter_participant_entity_ids: list[Any],
    ) -> int:
        participant_ids = {
            str(entity_id)
            for entity_id in encounter_participant_entity_ids
            if isinstance(entity_id, str) and entity_id
        }
        if not participant_ids:
            return 0

        count = 0
        for participant_id in sorted(participant_ids):
            entity = sim.state.entities.get(participant_id)
            if entity is None:
                continue
            if entity.space_id != local_space_id:
                continue
            if entity.template_id != LOCAL_ENCOUNTER_HOSTILE_TEMPLATE_ID:
                continue
            if LocalEncounterInstanceModule._is_incapacitated(entity.wounds):
                count += 1
        return count

    @staticmethod
    def _is_incapacitated(wounds: list[dict[str, Any]]) -> bool:
        severity_total = 0
        for wound in wounds:
            if not isinstance(wound, dict):
                continue
            severity = wound.get("severity")
            if isinstance(severity, int) and severity > 0:
                severity_total += severity
        return severity_total >= LOCAL_REWARD_INCAPACITATE_SEVERITY

    def _rules_state(self, sim: Simulation) -> dict[str, Any]:
        state = sim.get_rules_state(self.name)
        raw_processed = state.get(self._STATE_PROCESSED_REQUEST_IDS, [])
        raw_processed_end = state.get(self._STATE_PROCESSED_END_ACTION_UIDS, [])
        raw_active_by_local_space = state.get(self._STATE_ACTIVE_BY_LOCAL_SPACE, {})
        raw_applied_template_by_local_space = state.get(self._STATE_APPLIED_TEMPLATE_BY_LOCAL_SPACE, {})
        raw_return_in_progress_by_local_space = state.get(self._STATE_RETURN_IN_PROGRESS_BY_LOCAL_SPACE, {})
        raw_site_key_by_local_space = state.get(self._STATE_SITE_KEY_BY_LOCAL_SPACE, {})
        raw_site_state_by_key = state.get(self._STATE_SITE_STATE_BY_KEY, {})
        if not isinstance(raw_processed, list):
            raise ValueError("local_encounter_instance.processed_request_ids must be a list")
        if not isinstance(raw_processed_end, list):
            raise ValueError("local_encounter_instance.processed_end_action_uids must be a list")
        if not isinstance(raw_active_by_local_space, dict):
            raise ValueError("local_encounter_instance.active_by_local_space must be an object")
        if not isinstance(raw_applied_template_by_local_space, dict):
            raise ValueError("local_encounter_instance.applied_template_by_local_space must be an object")
        if not isinstance(raw_return_in_progress_by_local_space, dict):
            raise ValueError("local_encounter_instance.return_in_progress_by_local_space must be an object")
        if not isinstance(raw_site_key_by_local_space, dict):
            raise ValueError("local_encounter_instance.site_key_by_local_space must be an object")
        if not isinstance(raw_site_state_by_key, dict):
            raise ValueError("local_encounter_instance.site_state_by_key must be an object")
        normalized = [str(value) for value in raw_processed if str(value)]
        normalized_processed_end = [str(value) for value in raw_processed_end if str(value)]
        normalized_active_by_local_space: dict[str, dict[str, Any]] = {}
        for local_space_id, context in raw_active_by_local_space.items():
            if not isinstance(local_space_id, str) or not local_space_id:
                continue
            if not isinstance(context, dict):
                continue
            if not isinstance(context.get("request_event_id"), str):
                continue
            if not isinstance(context.get("entity_id"), str):
                continue
            if not isinstance(context.get("from_space_id"), str):
                continue
            from_location = context.get("from_location")
            return_spawn_coord = context.get("return_spawn_coord")
            origin_space_id = context.get("origin_space_id", context.get("from_space_id"))
            origin_location = self._normalize_origin_location_payload(
                origin_space_id=str(origin_space_id) if isinstance(origin_space_id, str) else "",
                origin_location_payload=context.get("origin_location", from_location),
                legacy_coord=return_spawn_coord,
            )
            origin_position = self._normalize_origin_position_payload(context.get("origin_position"))
            raw_return_context = context.get("encounter_return_context")
            if isinstance(raw_return_context, dict):
                return_context_space_id = str(raw_return_context.get("origin_space_id", origin_space_id))
                return_context_location = self._normalize_origin_location_payload(
                    origin_space_id=return_context_space_id,
                    origin_location_payload=raw_return_context.get("origin_location"),
                    legacy_coord=None,
                )
                return_context_position = self._normalize_origin_position_payload(raw_return_context.get("origin_position"))
            else:
                return_context_space_id = str(origin_space_id)
                return_context_location = copy.deepcopy(origin_location)
                return_context_position = copy.deepcopy(origin_position)

            if return_context_location is None:
                return_context_location = copy.deepcopy(origin_location)
                return_context_space_id = str(origin_space_id)

            return_exit_coord = self._normalize_local_square_coord_payload(context.get("return_exit_coord"))
            if return_exit_coord is None:
                entity_id = context.get("entity_id")
                if isinstance(entity_id, str) and entity_id in sim.state.entities:
                    entity = sim.state.entities[entity_id]
                    if entity.space_id == local_space_id:
                        return_exit_coord = self._normalize_local_square_coord_payload(sim._entity_location_ref(entity).coord)
            if not isinstance(from_location, dict) or not isinstance(return_spawn_coord, dict):
                continue
            if not isinstance(origin_space_id, str) or not origin_space_id:
                continue
            if origin_location is None:
                fallback_origin = context.get("origin_location", from_location)
                if not isinstance(fallback_origin, dict):
                    fallback_origin = {"coord": copy.deepcopy(return_spawn_coord)}
                origin_location = copy.deepcopy(fallback_origin)
                origin_location.setdefault("space_id", origin_space_id)
            normalized_active_by_local_space[local_space_id] = {
                "request_event_id": str(context["request_event_id"]),
                "entity_id": str(context["entity_id"]),
                "from_space_id": str(context["from_space_id"]),
                "origin_space_id": origin_space_id,
                "from_location": copy.deepcopy(from_location),
                "origin_location": copy.deepcopy(origin_location),
                "origin_position": copy.deepcopy(origin_position),
                "encounter_return_context": {
                    "origin_space_id": return_context_space_id,
                    "origin_location": copy.deepcopy(return_context_location),
                    "origin_position": copy.deepcopy(return_context_position),
                },
                "return_spawn_coord": copy.deepcopy(return_spawn_coord),
                "return_exit_coord": copy.deepcopy(return_exit_coord),
                "encounter_participant_entity_ids": [
                    str(entity_id)
                    for entity_id in context.get("encounter_participant_entity_ids", [])
                    if isinstance(entity_id, str) and entity_id
                ],
                "started_tick": int(context.get("started_tick", 0)),
                "site_key": self._normalize_site_key_payload(context.get("site_key")),
                "is_active": bool(context.get("is_active", True)),
                "last_active_tick": int(context.get("last_active_tick", context.get("started_tick", 0))),
            }
        state[self._STATE_PROCESSED_REQUEST_IDS] = normalized[-LOCAL_ENCOUNTER_INSTANCE_LEDGER_MAX:]
        state[self._STATE_PROCESSED_END_ACTION_UIDS] = normalized_processed_end[-LOCAL_ENCOUNTER_END_LEDGER_MAX:]
        ordered_space_ids = sorted(normalized_active_by_local_space.keys())
        state[self._STATE_ACTIVE_BY_LOCAL_SPACE] = {
            space_id: normalized_active_by_local_space[space_id] for space_id in ordered_space_ids[-MAX_ACTIVE_LOCAL_ENCOUNTERS:]
        }
        state[self._STATE_APPLIED_TEMPLATE_BY_LOCAL_SPACE] = {
            str(space_id): str(template_id)
            for space_id, template_id in sorted(raw_applied_template_by_local_space.items())
            if isinstance(space_id, str) and space_id and isinstance(template_id, str) and template_id
        }
        state[self._STATE_RETURN_IN_PROGRESS_BY_LOCAL_SPACE] = {
            str(space_id): bool(in_progress)
            for space_id, in_progress in sorted(raw_return_in_progress_by_local_space.items())
            if isinstance(space_id, str) and space_id and bool(in_progress)
        }
        normalized_site_key_by_local_space: dict[str, dict[str, Any]] = {}
        for space_id, site_key in sorted(raw_site_key_by_local_space.items()):
            if not isinstance(space_id, str) or not space_id:
                continue
            normalized_site_key = self._normalize_site_key_payload(site_key)
            if normalized_site_key is None:
                continue
            normalized_site_key_by_local_space[space_id] = normalized_site_key
        for space_id, context in state[self._STATE_ACTIVE_BY_LOCAL_SPACE].items():
            normalized_site_key = self._normalize_site_key_payload(context.get("site_key"))
            if normalized_site_key is None:
                continue
            normalized_site_key_by_local_space[space_id] = normalized_site_key
        state[self._STATE_SITE_KEY_BY_LOCAL_SPACE] = normalized_site_key_by_local_space
        normalized_site_state_by_key: dict[str, dict[str, Any]] = {}
        for site_key_json, site_state in sorted(raw_site_state_by_key.items()):
            normalized_site_state = self._normalize_site_state_payload(site_state)
            if normalized_site_state is None:
                if isinstance(site_state, dict) and "ecology_config" in site_state:
                    raise ValueError("local_encounter_instance.site_state_by_key ecology_config must be valid")
                if isinstance(site_state, dict) and "ecology_decisions" in site_state:
                    raise ValueError("local_encounter_instance.site_state_by_key ecology_decisions must be valid")
                continue
            normalized_site_state_by_key[site_key_json] = normalized_site_state
        for context in state[self._STATE_ACTIVE_BY_LOCAL_SPACE].values():
            normalized_site_key = self._normalize_site_key_payload(context.get("site_key"))
            if normalized_site_key is None:
                continue
            site_key_json = self._site_key_json(normalized_site_key)
            existing = normalized_site_state_by_key.get(site_key_json)
            last_active_tick = int(context.get("last_active_tick", context.get("started_tick", 0)))
            default_status = "active" if bool(context.get("is_active", True)) else "inactive"
            if existing is None:
                normalized_site_state_by_key[site_key_json] = {
                    "site_key": copy.deepcopy(normalized_site_key),
                    "status": default_status,
                    "last_active_tick": last_active_tick,
                    "next_check_tick": last_active_tick + SITE_CHECK_INTERVAL_TICKS,
                    "tags": ["stale"] if default_status == "stale" else [],
                    "pending_effects": [],
                    "fortified": False,
                    "rehab_generation": 0,
                    "rehab_policy": REHAB_POLICY_REPLACE,
                    "claimed_by_group_id": None,
                    "claimed_tick": None,
                    "growth_applied_steps": [],
                    "ecology_decisions": {"order": [], "by_key": {}},
                }
                continue
            existing["site_key"] = copy.deepcopy(normalized_site_key)
            existing["last_active_tick"] = max(int(existing.get("last_active_tick", 0)), last_active_tick)
            if bool(context.get("is_active", True)):
                existing["status"] = "active"
                existing["next_check_tick"] = max(
                    int(existing.get("next_check_tick", 0)),
                    last_active_tick + SITE_CHECK_INTERVAL_TICKS,
                )
            elif str(existing.get("status", "inactive")) == "active":
                existing["status"] = "inactive"
            existing["tags"] = self._normalize_tags(existing.get("tags", []))
            existing["pending_effects"] = self._normalize_pending_effects(existing.get("pending_effects", []))
            normalized_decisions = self._normalize_ecology_decisions(existing.get("ecology_decisions"))
            if normalized_decisions is None:
                raise ValueError("local_encounter_instance.site_state_by_key ecology_decisions entry is invalid")
            existing["ecology_decisions"] = normalized_decisions
        state[self._STATE_SITE_STATE_BY_KEY] = dict(sorted(normalized_site_state_by_key.items()))
        return state

    def _process_site_state_ticks(self, sim: Simulation, *, tick: int) -> None:
        state = self._rules_state(sim)
        site_state_by_key = dict(state[self._STATE_SITE_STATE_BY_KEY])
        eligible = [
            site_key_json
            for site_key_json, site_state in sorted(site_state_by_key.items())
            if int(site_state.get("next_check_tick", 0)) <= int(tick)
        ]
        if not eligible:
            return

        processed_count = 0
        for site_key_json in eligible:
            if processed_count >= MAX_SITE_CHECKS_PER_TICK:
                break
            site_state = copy.deepcopy(site_state_by_key[site_key_json])
            prior_status = str(site_state.get("status", "inactive"))
            if prior_status not in {"active", "inactive", "stale"}:
                prior_status = "inactive"
            last_active_tick = int(site_state.get("last_active_tick", 0))
            age = int(tick) - last_active_tick
            is_stale = age >= STALE_TICKS
            new_status = prior_status
            if prior_status != "active":
                new_status = "stale" if is_stale else "inactive"

            tags = self._normalize_tags(site_state.get("tags", []))
            if new_status == "stale":
                tags = self._normalize_tags([*tags, "stale"])

            pending_effects = self._normalize_pending_effects(site_state.get("pending_effects", []))
            scheduled_effect: dict[str, Any] | None = None
            if prior_status != "stale" and new_status == "stale":
                pending_effects, scheduled_effect = self._schedule_site_effect_once(
                    pending_effects=pending_effects,
                    effect_type=REINHABITATION_PENDING_EFFECT_TYPE,
                    created_tick=int(tick),
                    source=STALE_POLICY_EFFECT_SOURCE,
                )

            next_check_tick = int(tick) + SITE_CHECK_INTERVAL_TICKS
            site_state["status"] = new_status
            site_state["last_active_tick"] = last_active_tick
            site_state["next_check_tick"] = next_check_tick
            site_state["tags"] = tags
            site_state["pending_effects"] = pending_effects
            site_state_by_key[site_key_json] = site_state
            processed_count += 1

            if scheduled_effect is not None:
                sim.schedule_event_at(
                    tick=tick,
                    event_type=SITE_EFFECT_SCHEDULED_EVENT_TYPE,
                    params={
                        "site_key": copy.deepcopy(site_state["site_key"]),
                        "tick": int(tick),
                        "effect_type": str(scheduled_effect["effect_type"]),
                        "source": str(scheduled_effect["source"]),
                        "created_tick": int(scheduled_effect["created_tick"]),
                    },
                )

            sim.schedule_event_at(
                tick=tick,
                event_type=SITE_STATE_TICK_EVENT_TYPE,
                params={
                    "site_key": copy.deepcopy(site_state["site_key"]),
                    "tick": int(tick),
                    "prior_status": prior_status,
                    "new_status": new_status,
                    "is_stale": is_stale,
                    "last_active_tick": last_active_tick,
                    "next_check_tick": next_check_tick,
                },
            )

        state[self._STATE_SITE_STATE_BY_KEY] = dict(sorted(site_state_by_key.items()))
        sim.set_rules_state(self.name, state)

    def _upsert_site_state(
        self,
        *,
        site_state_by_key: dict[str, dict[str, Any]],
        site_key: dict[str, Any],
        status: str,
        last_active_tick: int,
        next_check_tick: int,
    ) -> dict[str, dict[str, Any]]:
        site_key_json = self._site_key_json(site_key)
        existing = site_state_by_key.get(site_key_json)
        tags: list[str] = []
        if isinstance(existing, dict):
            tags = self._normalize_tags(existing.get("tags", []))
        if status == "stale":
            tags = self._normalize_tags([*tags, "stale"])
        pending_effects: list[Any] = []
        if isinstance(existing, dict):
            pending_effects = self._normalize_pending_effects(existing.get("pending_effects", []))
        rehab_generation = 0
        if isinstance(existing, dict):
            rehab_generation = max(0, int(existing.get("rehab_generation", 0)))
        site_state_by_key[site_key_json] = {
            "site_key": copy.deepcopy(site_key),
            "status": status,
            "last_active_tick": int(last_active_tick),
            "next_check_tick": int(next_check_tick),
            "tags": tags,
            "pending_effects": pending_effects,
            "rehab_generation": rehab_generation,
            "fortified": bool(existing.get("fortified", False)) if isinstance(existing, dict) else False,
            "rehab_policy": (
                REHAB_POLICY_REPLACE
                if not isinstance(existing, dict) or existing.get("rehab_policy") is None
                else copy.deepcopy(existing.get("rehab_policy"))
            ),
            "claimed_by_group_id": (
                str(existing.get("claimed_by_group_id"))
                if isinstance(existing, dict) and existing.get("claimed_by_group_id") is not None
                else None
            ),
            "claimed_tick": (
                int(existing.get("claimed_tick", 0))
                if isinstance(existing, dict) and existing.get("claimed_by_group_id") is not None
                else None
            ),
            "growth_applied_steps": (
                self._normalize_growth_applied_steps(existing.get("growth_applied_steps", []))
                if isinstance(existing, dict)
                else []
            ),
            "ecology_decisions": (
                self._normalize_ecology_decisions(existing.get("ecology_decisions"))
                if isinstance(existing, dict)
                else {"order": [], "by_key": {}}
            ),
        }
        if isinstance(existing, dict) and existing.get("ecology_config") is not None:
            normalized_ecology_config = self._normalize_ecology_config(existing.get("ecology_config"))
            if normalized_ecology_config is not None:
                site_state_by_key[site_key_json]["ecology_config"] = normalized_ecology_config
        return site_state_by_key

    def _normalize_site_state_payload(self, payload: Any) -> dict[str, Any] | None:
        if not isinstance(payload, dict):
            return None
        site_key = self._normalize_site_key_payload(payload.get("site_key"))
        if site_key is None:
            return None
        status = str(payload.get("status", "inactive"))
        if status not in {"active", "inactive", "stale"}:
            status = "inactive"
        last_active_tick = max(0, int(payload.get("last_active_tick", 0)))
        next_check_tick = max(0, int(payload.get("next_check_tick", 0)))
        tags = self._normalize_tags(payload.get("tags", []))
        if status == "stale":
            tags = self._normalize_tags([*tags, "stale"])
        pending_effects = self._normalize_pending_effects(payload.get("pending_effects", []))
        rehab_generation = max(0, int(payload.get("rehab_generation", 0)))
        rehab_policy_raw = payload.get("rehab_policy")
        rehab_policy = self._normalize_rehab_policy(rehab_policy_raw)
        if rehab_policy is None:
            rehab_policy = copy.deepcopy(rehab_policy_raw)
        claimed_by_group_id_raw = payload.get("claimed_by_group_id")
        claimed_by_group_id = None
        claimed_tick: int | None = None
        if claimed_by_group_id_raw is not None:
            if not isinstance(claimed_by_group_id_raw, str) or not claimed_by_group_id_raw:
                return None
            claimed_by_group_id = claimed_by_group_id_raw
            claimed_tick_raw = payload.get("claimed_tick")
            if isinstance(claimed_tick_raw, bool) or not isinstance(claimed_tick_raw, int):
                return None
            claimed_tick = max(0, int(claimed_tick_raw))
        growth_applied_steps = self._normalize_growth_applied_steps(payload.get("growth_applied_steps", []))
        ecology_decisions = self._normalize_ecology_decisions(payload.get("ecology_decisions"))
        if ecology_decisions is None:
            return None
        ecology_config = self._normalize_ecology_config(payload.get("ecology_config")) if "ecology_config" in payload else None
        if "ecology_config" in payload and ecology_config is None:
            return None
        normalized_payload = {
            "site_key": copy.deepcopy(site_key),
            "status": status,
            "last_active_tick": last_active_tick,
            "next_check_tick": next_check_tick,
            "tags": tags,
            "pending_effects": pending_effects,
            "rehab_generation": rehab_generation,
            "fortified": bool(payload.get("fortified", False)),
            "rehab_policy": rehab_policy,
            "claimed_by_group_id": claimed_by_group_id,
            "claimed_tick": claimed_tick,
            "growth_applied_steps": growth_applied_steps,
            "ecology_decisions": ecology_decisions,
        }
        if ecology_config is not None:
            normalized_payload["ecology_config"] = ecology_config
        return normalized_payload

    @staticmethod
    def _normalize_ecology_config(payload: Any) -> dict[str, Any] | None:
        if not isinstance(payload, dict):
            return None
        allowed_top_fields = {"enabled", "tick_interval", "max_steps_per_tick", "rules"}
        if set(payload.keys()) - allowed_top_fields:
            return None

        enabled = payload.get("enabled", True)
        if not isinstance(enabled, bool):
            return None
        tick_interval = payload.get("tick_interval", SITE_ECOLOGY_INTERVAL_DAYS)
        if isinstance(tick_interval, bool) or not isinstance(tick_interval, int) or tick_interval < 1:
            return None
        max_steps = payload.get("max_steps_per_tick", SITE_ECOLOGY_CONFIG_MAX_STEPS_PER_TICK_HARD_CAP)
        if (
            isinstance(max_steps, bool)
            or not isinstance(max_steps, int)
            or max_steps < 1
            or max_steps > SITE_ECOLOGY_CONFIG_MAX_STEPS_PER_TICK_HARD_CAP
        ):
            return None
        rules_raw = payload.get("rules", [])
        if not isinstance(rules_raw, list) or len(rules_raw) > SITE_ECOLOGY_CONFIG_MAX_RULES:
            return None

        normalized_rules: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for raw_rule in rules_raw:
            if not isinstance(raw_rule, dict):
                return None
            allowed_rule_fields = {"id", "kind", "marker_type", "chance_percent", "priority", "d20_payload"}
            if set(raw_rule.keys()) - allowed_rule_fields:
                return None
            if not {"id", "kind", "marker_type", "chance_percent"}.issubset(set(raw_rule.keys())):
                return None

            rule_id = raw_rule.get("id")
            kind = raw_rule.get("kind")
            marker_type = raw_rule.get("marker_type")
            chance_percent = raw_rule.get("chance_percent")
            if not isinstance(rule_id, str) or not rule_id:
                return None
            if rule_id in seen_ids:
                return None
            seen_ids.add(rule_id)
            if kind not in SITE_ECOLOGY_CONFIG_ALLOWED_KINDS:
                return None
            if marker_type not in SITE_ECOLOGY_CONFIG_ALLOWED_MARKER_TYPES:
                return None
            if isinstance(chance_percent, bool) or not isinstance(chance_percent, int) or chance_percent < 0 or chance_percent > 100:
                return None

            normalized_rule = {
                "id": rule_id,
                "kind": str(kind),
                "marker_type": str(marker_type),
                "chance_percent": int(chance_percent),
                "d20_payload": bool(raw_rule.get("d20_payload", False)),
            }
            if "priority" in raw_rule:
                priority = raw_rule["priority"]
                if isinstance(priority, bool) or not isinstance(priority, int) or priority < EFFECT_PRIORITY_MIN or priority > EFFECT_PRIORITY_MAX:
                    return None
                normalized_rule["priority"] = int(priority)
            normalized_rules.append(normalized_rule)

        normalized_rules.sort(key=lambda item: str(item["id"]))
        return {
            "enabled": enabled,
            "tick_interval": int(tick_interval),
            "max_steps_per_tick": int(max_steps),
            "rules": normalized_rules,
        }

    def _consume_pending_site_effect_for_entry(
        self,
        *,
        site_key: dict[str, Any],
        site_state_by_key: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        site_key_json = self._site_key_json(site_key)
        existing = site_state_by_key.get(site_key_json)
        if not isinstance(existing, dict):
            return {"status": "rejected", "reason": "missing_site_state"}
        pending_effects = existing.get("pending_effects")
        if not isinstance(pending_effects, list):
            return {"status": "rejected", "reason": "invalid_pending_effects_schema"}

        normalized_site_state = self._normalize_site_state_payload(existing)
        if normalized_site_state is None:
            invalid_rehab_policy_value = self._bounded_invalid_rehab_policy_value(existing.get("rehab_policy"))
            if invalid_rehab_policy_value is not None:
                return {
                    "status": "rejected",
                    "reason": "invalid_rehab_policy",
                    "invalid_rehab_policy_value": invalid_rehab_policy_value,
                }
            return {"status": "rejected", "reason": "invalid_site_state_payload"}

        handlers = self._site_effect_entry_handlers()
        consumed_index: int | None = None
        consumed_result: dict[str, Any] | None = None
        diagnostics: list[dict[str, Any]] = []
        candidate_order: list[dict[str, Any]] = []
        for idx, raw_effect in enumerate(existing["pending_effects"]):
            priority_resolution = self._resolve_effect_priority(raw_effect)
            candidate_order.append(
                {
                    "index": int(idx),
                    "raw_effect": raw_effect,
                    "priority_resolution": priority_resolution,
                    "sort_priority": int(priority_resolution.get("sort_priority", 0)),
                }
            )
        candidate_order.sort(key=lambda item: (-item["sort_priority"], item["index"]))

        # Deterministic ordering contract (Phase 6D-M9): iterate pending effects by
        # descending resolved priority (default 0), tie-break by ascending index.
        # Malformed markers reject atomically, unsupported markers are skip-only
        # diagnostics, and consume/apply at most one supported marker.
        for candidate in candidate_order:
            idx = int(candidate["index"])
            raw_effect = candidate["raw_effect"]
            priority_resolution = candidate["priority_resolution"]
            priority = int(priority_resolution.get("priority", 0))
            effect = self._normalize_pending_effect_payload(raw_effect)
            if effect is None:
                return {
                    "status": "rejected",
                    "reason": "malformed_pending_effect_marker",
                    "index": int(idx),
                    "priority": int(priority),
                }
            if not bool(priority_resolution.get("valid", False)):
                return {
                    "status": "rejected",
                    "reason": "invalid_effect_priority",
                    "index": int(idx),
                    "priority": int(priority),
                    "effect_type": str(effect.get("effect_type", "")),
                    "invalid_priority_value": priority_resolution.get("invalid_priority_value"),
                }
            effect_type = str(effect.get("effect_type", ""))
            handler = handlers.get(effect_type)
            if handler is None:
                diagnostics.append(
                    {
                        "reason": "unsupported_site_effect_type",
                        "effect_type": effect_type,
                        "index": int(idx),
                        "priority": int(priority),
                    }
                )
                continue
            consumed_index = idx
            consumed_result = handler(site_state=normalized_site_state)
            if consumed_result.get("status") == "rejected":
                return {
                    "status": "rejected",
                    "reason": str(consumed_result.get("reason", "site_effect_rejected")),
                    "invalid_rehab_policy_value": consumed_result.get("invalid_rehab_policy_value"),
                    "index": int(idx),
                    "priority": int(priority),
                    "effect_type": effect_type,
                }
            break
        if consumed_index is None or consumed_result is None:
            return {"status": "none", "diagnostics": diagnostics}

        updated_effects = list(normalized_site_state["pending_effects"])
        del updated_effects[consumed_index]
        normalized_site_state["pending_effects"] = updated_effects
        normalized_site_state["rehab_generation"] = int(consumed_result["generation_after"])
        normalized_site_state["fortified"] = bool(consumed_result.get("fortified", normalized_site_state.get("fortified", False)))
        updated_state_by_key = dict(site_state_by_key)
        updated_state_by_key[site_key_json] = normalized_site_state
        return {
            "status": "consumed",
            "effect_type": str(consumed_result.get("effect_type", "")),
            "generation_after": int(consumed_result["generation_after"]),
            "rehab_policy": str(consumed_result.get("rehab_policy", REHAB_POLICY_REPLACE)),
            "fortified": bool(consumed_result.get("fortified", False)),
            "index": int(consumed_index),
            "priority": int(self._resolve_effect_priority(existing["pending_effects"][consumed_index]).get("priority", 0)),
            "diagnostics": diagnostics,
            "site_state_by_key": updated_state_by_key,
        }

    def _emit_site_effect_diagnostics(
        self,
        *,
        sim: Simulation,
        tick: int,
        site_key: dict[str, Any],
        diagnostics: list[Any],
    ) -> None:
        for diagnostic in diagnostics:
            if not isinstance(diagnostic, dict):
                continue
            reason = diagnostic.get("reason")
            if not isinstance(reason, str) or not reason:
                continue
            rejection_params = {
                "site_key": copy.deepcopy(site_key),
                "source": "entry_policy",
                "reason": reason,
                "tick": int(tick),
            }
            effect_type = diagnostic.get("effect_type")
            if isinstance(effect_type, str) and effect_type:
                rejection_params["effect_type"] = effect_type
            if isinstance(diagnostic.get("index"), int):
                rejection_params["index"] = int(diagnostic["index"])
            if isinstance(diagnostic.get("priority"), int):
                rejection_params["priority"] = int(diagnostic["priority"])
            invalid_priority_value = diagnostic.get("invalid_priority_value")
            if isinstance(invalid_priority_value, str):
                rejection_params["invalid_priority_value"] = invalid_priority_value
            sim.schedule_event_at(
                tick=int(tick),
                event_type=SITE_EFFECT_CONSUMPTION_REJECTED_EVENT_TYPE,
                params=rejection_params,
            )

    @staticmethod
    def _bounded_invalid_priority_value(value: Any) -> str:
        value_type = type(value).__name__
        try:
            rendered_value = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        except (TypeError, ValueError):
            rendered_value = "<non_json_serializable>"
        rendered = f"{value_type}:{rendered_value}"
        if len(rendered) <= INVALID_EFFECT_PRIORITY_DIAGNOSTIC_MAX_LEN:
            return rendered
        return f"{rendered[: INVALID_EFFECT_PRIORITY_DIAGNOSTIC_MAX_LEN - 3]}..."

    def _resolve_effect_priority(self, payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict) or "priority" not in payload:
            return {
                "valid": True,
                "priority": 0,
                "sort_priority": 0,
            }

        priority = payload.get("priority")
        if isinstance(priority, bool) or not isinstance(priority, int):
            return {
                "valid": False,
                "priority": 0,
                "sort_priority": EFFECT_PRIORITY_MAX + 1,
                "invalid_priority_value": self._bounded_invalid_priority_value(priority),
            }
        if priority < EFFECT_PRIORITY_MIN or priority > EFFECT_PRIORITY_MAX:
            return {
                "valid": False,
                "priority": int(priority),
                "sort_priority": int(priority),
                "invalid_priority_value": self._bounded_invalid_priority_value(priority),
            }
        return {
            "valid": True,
            "priority": int(priority),
            "sort_priority": int(priority),
        }

    def _site_effect_entry_handlers(self) -> dict[str, Any]:
        return {
            REINHABITATION_PENDING_EFFECT_TYPE: self._consume_reinhabitation_pending_effect,
            FORTIFICATION_PENDING_EFFECT_TYPE: self._consume_fortification_pending_effect,
        }

    @staticmethod
    def _consume_reinhabitation_pending_effect(*, site_state: dict[str, Any]) -> dict[str, Any]:
        policy = site_state.get("rehab_policy", REHAB_POLICY_REPLACE)
        if not isinstance(policy, str) or policy not in REHAB_POLICY_ALLOWED:
            return {
                "status": "rejected",
                "reason": "invalid_rehab_policy",
                "invalid_rehab_policy_value": LocalEncounterInstanceModule._bounded_invalid_rehab_policy_value(policy),
            }
        return {
            "status": "consumed",
            "effect_type": REINHABITATION_PENDING_EFFECT_TYPE,
            "generation_after": int(site_state.get("rehab_generation", 0)) + 1,
            "rehab_policy": policy,
            "fortified": bool(site_state.get("fortified", False)),
        }

    @staticmethod
    def _consume_fortification_pending_effect(*, site_state: dict[str, Any]) -> dict[str, Any]:
        return {
            "status": "consumed",
            "effect_type": FORTIFICATION_PENDING_EFFECT_TYPE,
            "generation_after": int(site_state.get("rehab_generation", 0)),
            "rehab_policy": str(site_state.get("rehab_policy", REHAB_POLICY_REPLACE)),
            "fortified": True,
        }

    @staticmethod
    def _normalize_rehab_policy(value: Any) -> str | None:
        if value is None:
            return REHAB_POLICY_REPLACE
        if not isinstance(value, str):
            return None
        if value not in REHAB_POLICY_ALLOWED:
            return None
        return value

    @staticmethod
    def _bounded_invalid_rehab_policy_value(value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            rendered = value
        else:
            value_type = type(value).__name__
            try:
                rendered = f"{value_type}:{json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True)}"
            except (TypeError, ValueError):
                rendered = f"{value_type}:<non_json_serializable>"
        if len(rendered) <= INVALID_REHAB_POLICY_DIAGNOSTIC_MAX_LEN:
            return rendered
        return f"{rendered[: INVALID_REHAB_POLICY_DIAGNOSTIC_MAX_LEN - 3]}..."

    def _plan_reinhabitation_generation(
        self,
        *,
        sim: Simulation,
        local_space: SpaceState,
        site_key: dict[str, Any],
        generation: int,
        occupied_coords: tuple[dict[str, int], ...],
        remove_existing: bool,
    ) -> dict[str, Any] | None:
        participant_coord, participant_placement_rule = self._resolve_participant_placement(
            local_space=local_space,
            occupied_coords=occupied_coords,
        )
        if participant_coord is None:
            return None
        try:
            spawn_x, spawn_y = sim._coord_to_world_xy(space=local_space, coord=participant_coord)
        except (KeyError, TypeError, ValueError):
            return None

        spawn_entity_id = self._generation_scoped_participant_id(site_key=site_key, generation=generation, index=0)
        if spawn_entity_id in sim.state.entities:
            return None

        return {
            "remove_ids": self._hostile_participant_ids_for_space(sim=sim, local_space_id=local_space.space_id)
            if remove_existing
            else [],
            "spawn_entities": [
                EntityState(
                    entity_id=spawn_entity_id,
                    position_x=spawn_x,
                    position_y=spawn_y,
                    space_id=local_space.space_id,
                    template_id="encounter_hostile_v1",
                )
            ],
            "spawn_records": [
                {
                    "entity_id": spawn_entity_id,
                    "coord": copy.deepcopy(participant_coord),
                    "placement_rule": participant_placement_rule,
                }
            ],
        }

    def _apply_reinhabitation_replace(
        self,
        *,
        sim: Simulation,
        local_space: SpaceState,
        site_key: dict[str, Any],
        generation: int,
        occupied_coords: tuple[dict[str, int], ...],
    ) -> dict[str, Any] | None:
        return self._plan_reinhabitation_generation(
            sim=sim,
            local_space=local_space,
            site_key=site_key,
            generation=generation,
            occupied_coords=occupied_coords,
            remove_existing=True,
        )

    def _apply_reinhabitation_add(
        self,
        *,
        sim: Simulation,
        local_space: SpaceState,
        site_key: dict[str, Any],
        generation: int,
        occupied_coords: tuple[dict[str, int], ...],
    ) -> dict[str, Any] | None:
        return self._plan_reinhabitation_generation(
            sim=sim,
            local_space=local_space,
            site_key=site_key,
            generation=generation,
            occupied_coords=occupied_coords,
            remove_existing=False,
        )

    @staticmethod
    def _hostile_participant_ids_for_space(*, sim: Simulation, local_space_id: str) -> list[str]:
        return sorted(
            candidate_id
            for candidate_id, candidate in sim.state.entities.items()
            if candidate.space_id == local_space_id and candidate.template_id == "encounter_hostile_v1"
        )

    @staticmethod
    def _generation_scoped_participant_id(*, site_key: dict[str, Any], generation: int, index: int) -> str:
        site_hash = hashlib.sha256(json.dumps(site_key, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()[:12]
        return f"{SPAWN_ENTITY_ID_PREFIX}:{site_hash}:gen{int(generation)}:{int(index)}"

    def _schedule_site_effect_once(
        self,
        *,
        pending_effects: list[dict[str, Any]],
        effect_type: str,
        created_tick: int,
        source: str,
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        normalized = self._normalize_pending_effects(pending_effects)
        if any(str(effect.get("effect_type", "")) == effect_type for effect in normalized):
            return normalized, None
        effect = {
            "effect_type": effect_type,
            "created_tick": int(created_tick),
            "source": source,
        }
        combined = [*normalized, effect]
        bounded = self._normalize_pending_effects(combined)
        return bounded, effect if any(str(item.get("effect_type", "")) == effect_type for item in bounded) else None

    def _normalize_pending_effects(self, value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        normalized: list[dict[str, Any]] = []
        for item in value:
            effect = self._normalize_pending_effect_storage_payload(item)
            if effect is None:
                continue
            normalized.append(effect)
        if len(normalized) > MAX_PENDING_EFFECTS_PER_SITE:
            normalized = normalized[-MAX_PENDING_EFFECTS_PER_SITE:]
        return normalized

    def _normalize_pending_effect_storage_payload(self, payload: Any) -> dict[str, Any] | None:
        if not isinstance(payload, dict):
            return None
        normalized: dict[str, Any] = {}
        for key in sorted(payload):
            if not isinstance(key, str):
                continue
            normalized_value = self._normalize_json_value(payload[key])
            if normalized_value is None and payload[key] is not None:
                continue
            normalized[key] = normalized_value
        return normalized

    def _normalize_pending_effect_payload(self, payload: Any) -> dict[str, Any] | None:
        if not isinstance(payload, dict):
            return None
        effect_type = payload.get("effect_type")
        source = payload.get("source")
        if not isinstance(effect_type, str) or not effect_type:
            return None
        if not isinstance(source, str) or not source:
            return None
        created_tick = max(0, int(payload.get("created_tick", 0)))
        normalized = {
            "effect_type": effect_type,
            "created_tick": created_tick,
            "source": source,
        }
        for key in sorted(payload):
            if key in self._SITE_EFFECT_REQUIRED_KEYS:
                continue
            if not isinstance(key, str):
                continue
            normalized_value = self._normalize_json_value(payload[key])
            if normalized_value is None and payload[key] is not None:
                continue
            normalized[key] = normalized_value
        return normalized

    def _normalize_json_value(self, value: Any) -> Any:
        if value is None or isinstance(value, (bool, int, float, str)):
            return value
        if isinstance(value, list):
            normalized_items: list[Any] = []
            for item in value:
                normalized_item = self._normalize_json_value(item)
                if normalized_item is None and item is not None:
                    continue
                normalized_items.append(normalized_item)
            return normalized_items
        if isinstance(value, dict):
            normalized_obj: dict[str, Any] = {}
            for key in sorted(value):
                if not isinstance(key, str):
                    continue
                normalized_item = self._normalize_json_value(value[key])
                if normalized_item is None and value[key] is not None:
                    continue
                normalized_obj[key] = normalized_item
            return normalized_obj
        return None

    @staticmethod
    def _normalize_tags(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        unique_tags: list[str] = []
        seen: set[str] = set()
        for item in value:
            tag = str(item)
            if not tag or tag in seen:
                continue
            seen.add(tag)
            unique_tags.append(tag)
        return unique_tags[:MAX_SITE_STATE_TAGS]

    @staticmethod
    def _normalize_growth_applied_steps(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        normalized: list[str] = []
        for item in value:
            if not isinstance(item, str) or not item:
                continue
            normalized.append(item)
        if len(normalized) > SITE_GROWTH_LEDGER_MAX:
            normalized = normalized[-SITE_GROWTH_LEDGER_MAX:]
        return normalized

    @staticmethod
    def _normalize_ecology_decisions(value: Any) -> dict[str, Any] | None:
        if value is None:
            return {"order": [], "by_key": {}}
        if not isinstance(value, dict):
            return None
        raw_order = value.get("order", [])
        raw_by_key = value.get("by_key", {})
        if not isinstance(raw_order, list) or not isinstance(raw_by_key, dict):
            return None

        def _normalize_ecology_json_value(raw: Any) -> Any:
            if raw is None or isinstance(raw, (bool, int, float, str)):
                return raw
            if isinstance(raw, list):
                normalized_items: list[Any] = []
                for item in raw:
                    normalized_item = _normalize_ecology_json_value(item)
                    if normalized_item is None and item is not None:
                        continue
                    normalized_items.append(normalized_item)
                return normalized_items
            if isinstance(raw, dict):
                normalized_obj: dict[str, Any] = {}
                for field_name in sorted(raw):
                    if not isinstance(field_name, str):
                        continue
                    normalized_item = _normalize_ecology_json_value(raw[field_name])
                    if normalized_item is None and raw[field_name] is not None:
                        continue
                    normalized_obj[field_name] = normalized_item
                return normalized_obj
            return None

        normalized_by_key: dict[str, dict[str, Any]] = {}
        for decision_key, decision_payload in sorted(raw_by_key.items()):
            if not isinstance(decision_key, str) or not decision_key:
                return None
            if not isinstance(decision_payload, dict):
                return None
            roll_u32 = decision_payload.get("roll_u32")
            pct_roll = decision_payload.get("pct_roll")
            threshold = decision_payload.get("threshold")
            d20_roll = decision_payload.get("d20_roll")
            result = decision_payload.get("result")
            if isinstance(roll_u32, bool) or not isinstance(roll_u32, int):
                return None
            if isinstance(pct_roll, bool) or not isinstance(pct_roll, int):
                return None
            if isinstance(threshold, bool) or not isinstance(threshold, int):
                return None
            if isinstance(d20_roll, bool) or not isinstance(d20_roll, int):
                return None
            if not isinstance(result, str) or not result:
                return None
            normalized_payload = {
                "roll_u32": int(roll_u32),
                "pct_roll": int(pct_roll),
                "threshold": int(threshold),
                "d20_roll": int(d20_roll),
                "result": result,
            }
            for field_name in sorted(decision_payload):
                if field_name in normalized_payload or not isinstance(field_name, str):
                    continue
                field_value = _normalize_ecology_json_value(decision_payload[field_name])
                if field_value is None and decision_payload[field_name] is not None:
                    continue
                normalized_payload[field_name] = field_value
            normalized_by_key[decision_key] = normalized_payload

        normalized_order: list[str] = []
        for raw_key in raw_order:
            if not isinstance(raw_key, str) or not raw_key:
                return None
            if raw_key not in normalized_by_key:
                return None
            if raw_key in normalized_order:
                continue
            normalized_order.append(raw_key)
        for key in sorted(normalized_by_key):
            if key not in normalized_order:
                normalized_order.append(key)
        if len(normalized_order) > MAX_SITE_ECOLOGY_DECISIONS:
            normalized_order = normalized_order[-MAX_SITE_ECOLOGY_DECISIONS:]
        bounded_by_key = {key: normalized_by_key[key] for key in normalized_order}
        return {"order": normalized_order, "by_key": bounded_by_key}

    @staticmethod
    def _site_key_json(site_key: dict[str, Any]) -> str:
        return json.dumps(site_key, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _local_space_id_for_site_key(site_key_by_local_space: dict[str, dict[str, Any]], site_key: dict[str, Any]) -> str | None:
        canonical_key = json.dumps(site_key, sort_keys=True, separators=(",", ":"))
        for local_space_id, existing_site_key in sorted(site_key_by_local_space.items()):
            if not isinstance(existing_site_key, dict):
                continue
            if json.dumps(existing_site_key, sort_keys=True, separators=(",", ":")) == canonical_key:
                return local_space_id
        return None

    def _normalize_site_key_payload(self, payload: Any) -> dict[str, Any] | None:
        if not isinstance(payload, dict):
            return None
        origin_space_id = payload.get("origin_space_id")
        origin_coord = payload.get("origin_coord")
        template_id = payload.get("template_id")
        if not isinstance(origin_space_id, str) or not origin_space_id:
            return None
        if not isinstance(template_id, str) or not template_id:
            return None
        if not isinstance(origin_coord, dict):
            return None
        topology_type = self._infer_topology_type_from_coord(origin_coord)
        if topology_type is None:
            return None

        normalized = {
            "origin_space_id": origin_space_id,
            "origin_coord": copy.deepcopy(origin_coord),
            "origin_topology_type": topology_type,
            "template_id": template_id,
        }
        encounter_entry_id = payload.get("encounter_entry_id")
        if isinstance(encounter_entry_id, str) and encounter_entry_id:
            normalized["encounter_entry_id"] = encounter_entry_id
        return normalized

    @staticmethod
    def _infer_topology_type_from_coord(coord: Any) -> str | None:
        if not isinstance(coord, dict):
            return None
        if "q" in coord and "r" in coord:
            return OVERWORLD_HEX_TOPOLOGY
        if "x" in coord and "y" in coord:
            return SQUARE_GRID_TOPOLOGY
        return None

    def _normalize_origin_location_payload(
        self,
        *,
        origin_space_id: str,
        origin_location_payload: Any,
        legacy_coord: Any,
    ) -> dict[str, Any] | None:
        if not isinstance(origin_space_id, str) or not origin_space_id:
            return None
        candidate = origin_location_payload if isinstance(origin_location_payload, dict) else {}
        coord = candidate.get("coord")
        if not isinstance(coord, dict) and isinstance(legacy_coord, dict):
            coord = legacy_coord
        if not isinstance(coord, dict):
            return None
        topology_type = candidate.get("topology_type")
        if not isinstance(topology_type, str) or not topology_type:
            topology_type = self._infer_topology_type_from_coord(coord)
        if topology_type is None:
            return None

        location_payload = copy.deepcopy(candidate)
        location_payload["space_id"] = str(candidate.get("space_id", origin_space_id))
        location_payload["topology_type"] = topology_type
        location_payload["coord"] = copy.deepcopy(coord)
        try:
            location = LocationRef.from_dict(location_payload)
        except (KeyError, TypeError, ValueError):
            return None
        return location.to_dict()

    @staticmethod
    def _normalize_origin_position_payload(origin_position_payload: Any) -> dict[str, float] | None:
        if not isinstance(origin_position_payload, dict):
            return None
        try:
            x = float(origin_position_payload["x"])
            y = float(origin_position_payload["y"])
        except (KeyError, TypeError, ValueError):
            return None
        if not math.isfinite(x) or not math.isfinite(y):
            return None
        return {"x": x, "y": y}

    @staticmethod
    def _normalize_local_square_coord_payload(coord_payload: Any) -> dict[str, int] | None:
        if not isinstance(coord_payload, dict):
            return None
        try:
            x = int(coord_payload["x"])
            y = int(coord_payload["y"])
        except (KeyError, TypeError, ValueError):
            return None
        return {"x": x, "y": y}

    def _is_at_local_return_exit(self, *, sim: Simulation, entity_id: str, active_context: dict[str, Any]) -> bool:
        entity = sim.state.entities.get(entity_id)
        if entity is None:
            return False
        target_coord = self._normalize_local_square_coord_payload(active_context.get("return_exit_coord"))
        if target_coord is None:
            return False
        actor_coord = sim._entity_location_ref(entity).coord
        return actor_coord == target_coord

    def _is_exit_pinned_by_hostile(self, *, sim: Simulation, entity_id: str) -> bool:
        actor = sim.state.entities.get(entity_id)
        if actor is None:
            return False
        actor_location = sim._entity_location_ref(actor)
        for hostile_id in sorted(sim.state.entities):
            hostile = sim.state.entities[hostile_id]
            if hostile.space_id != actor.space_id:
                continue
            if hostile.template_id != LOCAL_ENCOUNTER_HOSTILE_TEMPLATE_ID:
                continue
            hostile_location = sim._entity_location_ref(hostile)
            distance = distance_between_locations(actor_location, hostile_location)
            if distance is not None and distance <= LOCAL_ENCOUNTER_EXIT_PIN_DISTANCE:
                return True
        return False

    @staticmethod
    def _select_entity_id(sim: Simulation, *, from_space_id: str) -> str | None:
        if DEFAULT_PLAYER_ENTITY_ID in sim.state.entities:
            return DEFAULT_PLAYER_ENTITY_ID
        candidate_ids = sorted(
            entity_id for entity_id, entity in sim.state.entities.items() if entity.space_id == from_space_id
        )
        if not candidate_ids:
            return None
        return candidate_ids[0]


class EncounterActionExecutionModule(RuleModule):
    """Phase 4J deterministic action execution substrate.

    Executes a minimal, explicitly bounded set of action intents into
    deterministic world records with a serialized idempotence ledger.
    """

    name = "encounter_action_execution"
    _STATE_EXECUTED_ACTION_UIDS = "executed_action_uids"
    _SUPPORTED_ACTION_TYPES = {"signal_intent", "track_intent", "spawn_intent", "local_encounter_intent"}

    def on_simulation_start(self, sim: Simulation) -> None:
        sim.set_rules_state(self.name, self._rules_state(sim))

    def on_event_executed(self, sim: Simulation, event: SimEvent) -> None:
        if event.event_type == ENCOUNTER_ACTION_STUB_EVENT_TYPE:
            self._schedule_execute_event(sim, event)
            return
        if event.event_type != ENCOUNTER_ACTION_EXECUTE_EVENT_TYPE:
            return
        self._execute_actions(sim, event)

    def _schedule_execute_event(self, sim: Simulation, event: SimEvent) -> None:
        params = copy.deepcopy(event.params)
        params["source_event_id"] = event.event_id
        params["source_tick"] = int(event.tick)
        sim.schedule_event_at(
            tick=event.tick + 1,
            event_type=ENCOUNTER_ACTION_EXECUTE_EVENT_TYPE,
            params=params,
        )

    def _execute_actions(self, sim: Simulation, event: SimEvent) -> None:
        source_event_id = str(event.params.get("source_event_id", ""))
        actions = event.params.get("actions", [])
        if not isinstance(actions, list):
            raise ValueError("encounter_action_execute actions must be a list")

        state = self._rules_state(sim)
        executed_action_uids = set(state[self._STATE_EXECUTED_ACTION_UIDS])

        for action_index, action in enumerate(actions):
            if not isinstance(action, dict):
                raise ValueError(f"encounter_action_execute actions[{action_index}] must be an object")

            action_uid = self._action_uid(source_event_id=source_event_id, action_index=action_index)
            action_type = str(action.get("action_type", ""))
            template_id = str(action.get("template_id", ""))
            params = action.get("params", {})
            if not isinstance(params, dict):
                raise ValueError(f"encounter_action_execute actions[{action_index}].params must be an object")
            quantity = int(action.get("quantity", params.get("quantity", 1)))
            if quantity < 1:
                raise ValueError(f"encounter_action_execute actions[{action_index}].quantity must be >= 1")

            outcome = "executed"
            mutation = "none"
            location = self._location_from_execute_event(event)
            if action_uid in executed_action_uids:
                outcome = "already_executed"
            elif action_type not in self._SUPPORTED_ACTION_TYPES:
                outcome = "ignored_unsupported"
                executed_action_uids.add(action_uid)
            elif action_type == "signal_intent":
                created = sim.state.world.upsert_signal(
                    {
                        "signal_uid": action_uid,
                        "template_id": template_id,
                        "location": location,
                        "created_tick": int(event.tick),
                        "params": copy.deepcopy(params),
                        "expires_tick": self._optional_expires_tick(params=params, created_tick=int(event.tick)),
                    }
                )
                mutation = "signal_created" if created else "signal_existing"
                executed_action_uids.add(action_uid)
            elif action_type == "track_intent":
                created = sim.state.world.upsert_track(
                    {
                        "track_uid": action_uid,
                        "template_id": template_id,
                        "location": location,
                        "created_tick": int(event.tick),
                        "params": copy.deepcopy(params),
                        "expires_tick": self._optional_expires_tick(params=params, created_tick=int(event.tick)),
                    }
                )
                mutation = "track_created" if created else "track_existing"
                executed_action_uids.add(action_uid)
            elif action_type == "spawn_intent":
                descriptor = {
                    "created_tick": int(event.tick),
                    "location": location,
                    "template_id": template_id,
                    "quantity": quantity,
                    "expires_tick": self._optional_expires_tick(params=params, created_tick=int(event.tick)),
                    "source_event_id": source_event_id,
                    "action_uid": action_uid,
                    "params": copy.deepcopy(params),
                }
                for key, value in action.items():
                    if key in descriptor or key in {"action_type", "template_id", "quantity", "params"}:
                        continue
                    descriptor[key] = copy.deepcopy(value)
                sim.state.world.append_spawn_descriptor(descriptor)
                mutation = "spawn_descriptor_recorded"
                executed_action_uids.add(action_uid)
            elif action_type == "local_encounter_intent":
                actor_id, actor_space_id, actor_space_role = self._local_encounter_actor_context(sim=sim, location=location)
                if actor_space_role != CAMPAIGN_SPACE_ROLE:
                    outcome = "rejected_local_encounter_origin"
                    mutation = "none"
                    executed_action_uids.add(action_uid)
                    sim.schedule_event_at(
                        tick=event.tick + 1,
                        event_type=ENCOUNTER_ACTION_OUTCOME_EVENT_TYPE,
                        params={
                            "source_event_id": source_event_id,
                            "execute_event_id": event.event_id,
                            "action_index": action_index,
                            "action_uid": action_uid,
                            "action_type": action_type,
                            "template_id": template_id,
                            "location": location,
                            "quantity": quantity,
                            "outcome": outcome,
                            "mutation": mutation,
                            "applied": False,
                            "reason": "local_encounter_not_allowed_from_local_space",
                            "entity_id": actor_id,
                            "space_id": actor_space_id,
                            "tick": int(event.tick),
                        },
                    )
                    continue
                from_space_id, from_location = self._local_encounter_origin(sim=sim, location=location)
                if from_space_id is None or from_location is None:
                    outcome = "ignored_invalid_origin"
                    mutation = "none"
                    executed_action_uids.add(action_uid)
                else:
                    passthrough = self._encounter_passthrough_blob(event.params)
                    suggested_local_template_id = self._optional_non_empty_string(
                        params.get("suggested_local_template_id", template_id)
                    )
                    site_key = {
                        "origin_space_id": from_space_id,
                        "origin_coord": copy.deepcopy(from_location.get("coord")),
                        "template_id": suggested_local_template_id or "__default__",
                    }
                    encounter_entry_id = self._optional_non_empty_string(passthrough.get("entry_id"))
                    if encounter_entry_id is not None:
                        site_key["encounter_entry_id"] = encounter_entry_id
                    sim.schedule_event_at(
                        tick=event.tick + 1,
                        event_type=LOCAL_ENCOUNTER_REQUEST_EVENT_TYPE,
                        params={
                            "action_uid": action_uid,
                            "from_space_id": from_space_id,
                            "from_location": from_location,
                            "suggested_local_template_id": suggested_local_template_id,
                            "site_key": site_key,
                            "encounter_context_passthrough": passthrough,
                            "tick": passthrough.get("tick"),
                            "context": passthrough.get("context"),
                            "trigger": passthrough.get("trigger"),
                            "location": passthrough.get("location"),
                            "roll": passthrough.get("roll"),
                            "category": passthrough.get("category"),
                            "table_id": passthrough.get("table_id"),
                            "entry_id": passthrough.get("entry_id"),
                            "entry_tags": passthrough.get("entry_tags"),
                        },
                    )
                    mutation = "local_encounter_requested"
                    executed_action_uids.add(action_uid)

            sim.schedule_event_at(
                tick=event.tick + 1,
                event_type=ENCOUNTER_ACTION_OUTCOME_EVENT_TYPE,
                params={
                    "source_event_id": source_event_id,
                    "execute_event_id": event.event_id,
                    "action_index": action_index,
                    "action_uid": action_uid,
                    "action_type": action_type,
                    "template_id": template_id,
                    "location": location,
                    "quantity": quantity,
                    "outcome": outcome,
                    "mutation": mutation,
                },
            )

        state[self._STATE_EXECUTED_ACTION_UIDS] = sorted(executed_action_uids)
        sim.set_rules_state(self.name, state)

    def _rules_state(self, sim: Simulation) -> dict[str, Any]:
        state = sim.get_rules_state(self.name)
        executed_action_uids = state.get(self._STATE_EXECUTED_ACTION_UIDS, [])
        if not isinstance(executed_action_uids, list):
            raise ValueError("encounter_action_execution.rules_state.executed_action_uids must be a list")
        normalized_uids: list[str] = []
        for uid in executed_action_uids:
            if not isinstance(uid, str) or not uid:
                raise ValueError("encounter_action_execution.rules_state.executed_action_uids entries must be strings")
            normalized_uids.append(uid)
        return {self._STATE_EXECUTED_ACTION_UIDS: sorted(set(normalized_uids))}

    def _action_uid(self, *, source_event_id: str, action_index: int) -> str:
        if not source_event_id:
            raise ValueError("encounter_action_execute source_event_id must be a non-empty string")
        return f"{source_event_id}:{action_index}"

    def _optional_expires_tick(self, *, params: dict[str, Any], created_tick: int) -> int | None:
        expires_tick = params.get("expires_tick")
        if expires_tick is not None:
            return int(expires_tick)
        ttl_ticks = params.get("ttl_ticks")
        if ttl_ticks is None:
            return None
        return created_tick + int(ttl_ticks)

    def _location_from_execute_event(self, event: SimEvent) -> dict[str, Any]:
        location = event.params.get("location")
        if not isinstance(location, dict):
            raise ValueError("encounter_action_execute location must be an object")
        return copy.deepcopy(location)

    def _local_encounter_origin(self, *, sim: Simulation, location: dict[str, Any]) -> tuple[str | None, dict[str, Any] | None]:
        from_space_id = str(location.get("space_id", ""))
        from_space = sim.state.world.spaces.get(from_space_id)
        if from_space is None or from_space.role != CAMPAIGN_SPACE_ROLE:
            return None, None
        return from_space_id, copy.deepcopy(location)

    def _local_encounter_actor_context(
        self, *, sim: Simulation, location: dict[str, Any]
    ) -> tuple[str | None, str | None, str | None]:
        location_space_id = str(location.get("space_id", ""))
        if DEFAULT_PLAYER_ENTITY_ID in sim.state.entities:
            player = sim.state.entities[DEFAULT_PLAYER_ENTITY_ID]
            player_space = sim.state.world.spaces.get(player.space_id)
            return DEFAULT_PLAYER_ENTITY_ID, str(player.space_id), None if player_space is None else str(player_space.role)

        entity_ids = sorted(entity_id for entity_id, entity in sim.state.entities.items() if entity.space_id == location_space_id)
        if entity_ids:
            entity_id = entity_ids[0]
            entity = sim.state.entities[entity_id]
            actor_space = sim.state.world.spaces.get(entity.space_id)
            return entity_id, str(entity.space_id), None if actor_space is None else str(actor_space.role)

        location_space = sim.state.world.spaces.get(location_space_id)
        return None, location_space_id if location_space_id else None, None if location_space is None else str(location_space.role)

    @staticmethod
    def _optional_non_empty_string(value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        normalized = value.strip()
        if not normalized:
            return None
        return normalized

    def _encounter_passthrough_blob(self, params: dict[str, Any]) -> dict[str, Any]:
        blob = {
            "tick": params.get("tick"),
            "context": params.get("context"),
            "trigger": params.get("trigger"),
            "location": params.get("location"),
            "roll": params.get("roll"),
            "category": params.get("category"),
            "table_id": params.get("table_id"),
            "entry_id": params.get("entry_id"),
            "entry_tags": params.get("entry_tags"),
        }
        return json.loads(json.dumps(blob, sort_keys=True))





class SiteEcologyModule(RuleModule):
    """Phase 6D-M10 deterministic site-ecology scaffolding (campaign-role aware)."""

    name = "site_ecology"

    def on_simulation_start(self, sim: Simulation) -> None:
        scheduler = sim.get_rule_module(PeriodicScheduler.name)
        if scheduler is None:
            scheduler = PeriodicScheduler()
            sim.register_rule_module(scheduler)
        if not isinstance(scheduler, PeriodicScheduler):
            raise TypeError("periodic_scheduler module must be a PeriodicScheduler")

        sim.set_rules_state(self.name, self._rules_state(sim))
        interval_ticks = max(1, int(sim.state.time.ticks_per_day) * SITE_ECOLOGY_INTERVAL_DAYS)
        scheduler.register_task(
            task_name=SITE_ECOLOGY_TASK_NAME,
            interval_ticks=interval_ticks,
            start_tick=0,
        )
        scheduler.set_task_callback(SITE_ECOLOGY_TASK_NAME, self._build_tick_callback())

    def on_command(self, sim: Simulation, command: SimCommand, command_index: int) -> bool:
        if command.command_type == CLAIM_SITE_FROM_OPPORTUNITY_INTENT:
            self._handle_claim_from_opportunity(sim=sim, command=command)
            return True
        if command.command_type != CLAIM_SITE_INTENT:
            return False

        tick = int(command.tick)
        site_key_payload = command.params.get("site_key")
        group_id = str(command.params.get("group_id", ""))
        if not isinstance(site_key_payload, dict):
            self._emit_claim_outcome(sim=sim, tick=tick, site_key=None, group_id=group_id, outcome="invalid_site_key")
            return True
        site_key = LocalEncounterInstanceModule()._normalize_site_key_payload(site_key_payload)
        if site_key is None:
            self._emit_claim_outcome(sim=sim, tick=tick, site_key=site_key_payload, group_id=group_id, outcome="invalid_site_key")
            return True
        self._apply_claim(sim=sim, tick=tick, site_key=site_key, group_id=group_id)
        return True

    def _handle_claim_from_opportunity(self, *, sim: Simulation, command: SimCommand) -> None:
        tick = int(command.tick)
        opportunity_id = command.params.get("opportunity_id")
        if not isinstance(opportunity_id, str) or not opportunity_id:
            self._emit_claim_outcome(sim=sim, tick=tick, site_key=None, group_id="", outcome="unknown_opportunity")
            return

        opportunities = list(sim.state.world.claim_opportunities)
        matching_index = None
        for index, row in enumerate(opportunities):
            if str(row.get("opportunity_id", "")) == opportunity_id:
                matching_index = index
                break
        if matching_index is None:
            self._emit_claim_outcome(sim=sim, tick=tick, site_key=None, group_id="", outcome="unknown_opportunity")
            return

        matching = dict(opportunities[matching_index])
        site_key = copy.deepcopy(matching.get("site_key"))
        group_id = str(matching.get("group_id", ""))
        if matching.get("consumed_tick") is not None:
            self._emit_claim_outcome(sim=sim, tick=tick, site_key=site_key, group_id=group_id, outcome="opportunity_already_consumed")
            return

        group = sim.state.world.groups.get(group_id)
        if group is None:
            self._emit_claim_outcome(sim=sim, tick=tick, site_key=site_key, group_id=group_id, outcome="unknown_group")
            return
        expected_cell = matching.get("cell")
        if not isinstance(expected_cell, dict) or group.location != expected_cell:
            self._emit_claim_outcome(sim=sim, tick=tick, site_key=site_key, group_id=group_id, outcome="group_not_at_opportunity_cell")
            return

        claim_outcome = self._inspect_claim_preconditions(sim=sim, site_key=site_key, group_id=group_id)
        if claim_outcome != "ok":
            self._emit_claim_outcome(sim=sim, tick=tick, site_key=site_key, group_id=group_id, outcome=claim_outcome)
            return

        matching["consumed_tick"] = tick
        opportunities[matching_index] = matching
        sim.state.world.claim_opportunities = opportunities
        sim.schedule_event_at(
            tick=tick + 1,
            event_type=CLAIM_OPPORTUNITY_CONSUMED_EVENT_TYPE,
            params={
                "tick": tick,
                "opportunity_id": opportunity_id,
                "group_id": group_id,
                "site_key": copy.deepcopy(site_key),
            },
        )
        self._apply_claim(sim=sim, tick=tick, site_key=site_key, group_id=group_id)

    def _apply_claim(self, *, sim: Simulation, tick: int, site_key: dict[str, Any], group_id: str) -> None:
        precondition = self._inspect_claim_preconditions(sim=sim, site_key=site_key, group_id=group_id)
        if precondition != "ok":
            self._emit_claim_outcome(sim=sim, tick=tick, site_key=site_key, group_id=group_id, outcome=precondition)
            return

        local_state = sim.get_rules_state(LocalEncounterInstanceModule.name)
        assert isinstance(local_state, dict)
        site_state_by_key = dict(local_state.get(LocalEncounterInstanceModule._STATE_SITE_STATE_BY_KEY, {}))
        site_key_json = LocalEncounterInstanceModule._site_key_json(site_key)
        existing = site_state_by_key.get(site_key_json)
        normalized = LocalEncounterInstanceModule()._normalize_site_state_payload(existing) if isinstance(existing, dict) else None
        if normalized is None:
            normalized = {
                "site_key": copy.deepcopy(site_key),
                "status": "inactive",
                "last_active_tick": 0,
                "next_check_tick": 0,
                "tags": [],
                "pending_effects": [],
                "rehab_generation": 0,
                "fortified": False,
                "rehab_policy": REHAB_POLICY_REPLACE,
                "claimed_by_group_id": None,
                "claimed_tick": None,
                "growth_applied_steps": [],
                "ecology_decisions": {"order": [], "by_key": {}},
            }

        normalized["claimed_by_group_id"] = group_id
        normalized["claimed_tick"] = tick
        site_state_by_key[site_key_json] = normalized
        local_state[LocalEncounterInstanceModule._STATE_SITE_STATE_BY_KEY] = dict(sorted(site_state_by_key.items()))
        sim.set_rules_state(LocalEncounterInstanceModule.name, local_state)
        self._emit_claim_outcome(sim=sim, tick=tick, site_key=site_key, group_id=group_id, outcome="applied")

    def _inspect_claim_preconditions(self, *, sim: Simulation, site_key: dict[str, Any], group_id: str) -> str:
        if group_id not in sim.state.world.groups:
            return "unknown_group"

        local_state = sim.get_rules_state(LocalEncounterInstanceModule.name)
        if not isinstance(local_state, dict):
            return "missing_site_state_module"
        site_state_by_key = dict(local_state.get(LocalEncounterInstanceModule._STATE_SITE_STATE_BY_KEY, {}))
        site_key_json = LocalEncounterInstanceModule._site_key_json(site_key)
        existing = site_state_by_key.get(site_key_json)
        normalized = LocalEncounterInstanceModule()._normalize_site_state_payload(existing) if isinstance(existing, dict) else None
        if normalized is None:
            normalized = {
                "site_key": copy.deepcopy(site_key),
                "status": "inactive",
                "last_active_tick": 0,
                "next_check_tick": 0,
                "tags": [],
                "pending_effects": [],
                "rehab_generation": 0,
                "fortified": False,
                "rehab_policy": REHAB_POLICY_REPLACE,
                "claimed_by_group_id": None,
                "claimed_tick": None,
                "growth_applied_steps": [],
                "ecology_decisions": {"order": [], "by_key": {}},
            }

        if normalized.get("claimed_by_group_id") is not None:
            return "already_claimed"
        return "ok"

    def on_event_executed(self, sim: Simulation, event: SimEvent) -> None:
        if event.event_type != GROUP_MOVE_ARRIVED_EVENT_TYPE:
            return
        group_id = str(event.params.get("group_id", ""))
        to_cell = event.params.get("to_cell")
        if not isinstance(to_cell, dict):
            return
        sites = sim.state.world.get_sites_at_location(to_cell)
        ordered_sites: list[tuple[str, dict[str, Any]]] = []
        for site in sites:
            site_key = {
                "origin_space_id": str(site.location.get("space_id", "")),
                "origin_coord": copy.deepcopy(site.location.get("coord", {})),
                "template_id": f"site:{site.site_id}",
            }
            site_key_json = LocalEncounterInstanceModule._site_key_json(site_key)
            ordered_sites.append((site_key_json, site_key))

        for _, site_key in sorted(ordered_sites)[:MAX_CLAIM_SITES_PROCESSED_PER_ARRIVAL]:
            sim.schedule_event_at(
                tick=event.tick + 1,
                event_type=GROUP_ARRIVED_AT_SITE_EVENT_TYPE,
                params={
                    "tick": int(event.tick),
                    "group_id": group_id,
                    "site_key": copy.deepcopy(site_key),
                    "cell": copy.deepcopy(to_cell),
                },
            )
            if self._inspect_claim_preconditions(sim=sim, site_key=site_key, group_id=group_id) == "already_claimed":
                continue
            if self._has_unconsumed_opportunity(sim=sim, group_id=group_id, site_key=site_key):
                continue
            self._create_claim_opportunity(sim=sim, tick=int(event.tick), group_id=group_id, site_key=site_key, cell=to_cell)

    def _has_unconsumed_opportunity(self, *, sim: Simulation, group_id: str, site_key: dict[str, Any]) -> bool:
        site_key_json = LocalEncounterInstanceModule._site_key_json(site_key)
        for row in sim.state.world.claim_opportunities:
            if (
                str(row.get("group_id", "")) == group_id
                and LocalEncounterInstanceModule._site_key_json(dict(row.get("site_key", {}))) == site_key_json
                and row.get("consumed_tick") is None
            ):
                return True
        return False

    def _create_claim_opportunity(self, *, sim: Simulation, tick: int, group_id: str, site_key: dict[str, Any], cell: dict[str, Any]) -> None:
        opportunities = list(sim.state.world.claim_opportunities)
        while len(opportunities) >= MAX_CLAIM_OPPORTUNITIES:
            # Deterministic FIFO regardless of consumed status to keep policy simple/predictable.
            del opportunities[0]

        opportunity_id = f"{tick}:{len(sim.input_log)}:{group_id}:{LocalEncounterInstanceModule._site_key_json(site_key)}"
        opportunities.append(
            {
                "opportunity_id": opportunity_id,
                "group_id": group_id,
                "site_key": copy.deepcopy(site_key),
                "cell": copy.deepcopy(cell),
                "created_tick": tick,
                "consumed_tick": None,
            }
        )
        sim.state.world.claim_opportunities = opportunities
        sim.schedule_event_at(
            tick=tick + 1,
            event_type=CLAIM_OPPORTUNITY_CREATED_EVENT_TYPE,
            params={
                "tick": tick,
                "opportunity_id": opportunity_id,
                "group_id": group_id,
                "site_key": copy.deepcopy(site_key),
            },
        )

    def _build_tick_callback(self):
        def _on_periodic(sim: Simulation, tick: int) -> None:
            self._process_periodic_tick(sim, tick)

        return _on_periodic

    def _process_periodic_tick(self, sim: Simulation, tick: int) -> None:
        local_state = sim.get_rules_state(LocalEncounterInstanceModule.name)
        if not isinstance(local_state, dict):
            return

        raw_site_state_by_key = local_state.get(LocalEncounterInstanceModule._STATE_SITE_STATE_BY_KEY, {})
        if not isinstance(raw_site_state_by_key, dict):
            raise ValueError("local_encounter_instance.site_state_by_key must be an object")

        ecology_state = self._rules_state(sim)
        site_state_by_key = dict(raw_site_state_by_key)
        ordered_keys = sorted(site_state_by_key)
        if ordered_keys:
            start_index = int(ecology_state["next_site_cursor"]) % len(ordered_keys)
            due_keys = ordered_keys[start_index:] + ordered_keys[:start_index]
        else:
            start_index = 0
            due_keys = []
        processed = 0
        scheduled_count = 0

        for site_key_json in due_keys:
            if processed >= SITE_ECOLOGY_MAX_PROCESSED_PER_TICK:
                break
            current_state = site_state_by_key.get(site_key_json)
            normalized = LocalEncounterInstanceModule()._normalize_site_state_payload(current_state) if isinstance(current_state, dict) else None
            if normalized is None:
                continue
            processed += 1

            claim_group_id = normalized.get("claimed_by_group_id")
            claimed_tick = normalized.get("claimed_tick")
            if claim_group_id is None or claimed_tick is None:
                continue

            ecology_config = normalized.get("ecology_config")
            if ecology_config is None:
                growth_rules = self._legacy_growth_rules(sim)
                legacy_mode = True
            else:
                if not bool(ecology_config.get("enabled", True)):
                    continue
                tick_interval = int(ecology_config.get("tick_interval", SITE_ECOLOGY_INTERVAL_DAYS))
                if tick_interval > 1:
                    interval_ticks = tick_interval * int(sim.state.time.ticks_per_day)
                    if interval_ticks > 0 and int(tick) % interval_ticks != 0:
                        continue
                growth_rules = self._configured_growth_rules(sim=sim, ecology_config=ecology_config)
                legacy_mode = False

            applied_steps = list(normalized.get("growth_applied_steps", []))
            pending_effects = list(normalized.get("pending_effects", []))
            ecology_decisions = LocalEncounterInstanceModule._normalize_ecology_decisions(normalized.get("ecology_decisions"))
            if ecology_decisions is None:
                raise ValueError("local_encounter_instance.site_state_by_key ecology_decisions must be valid")

            max_steps = len(growth_rules)
            if ecology_config is not None:
                max_steps = min(max_steps, int(ecology_config.get("max_steps_per_tick", SITE_ECOLOGY_CONFIG_MAX_STEPS_PER_TICK_HARD_CAP)))
            applied_this_tick = 0

            for growth_rule in growth_rules:
                if applied_this_tick >= max_steps:
                    break
                step_id = str(growth_rule["step_id"])
                threshold_ticks = int(growth_rule["threshold_ticks"])
                chance_percent = int(growth_rule["chance_percent"])
                effect_payload = copy.deepcopy(growth_rule["effect_payload"])
                rule_id = str(growth_rule.get("rule_id", step_id))
                marker_type = str(growth_rule.get("marker_type", effect_payload.get("effect_type", "")))
                use_d20_payload = bool(growth_rule.get("d20_payload", True))
                if step_id in applied_steps:
                    continue
                age_ticks = max(0, int(tick) - int(claimed_tick))
                if age_ticks < threshold_ticks:
                    continue
                schedule_tick = int(claimed_tick) + int(threshold_ticks)
                if legacy_mode:
                    decision_key = self._legacy_decision_key(
                        step_id=step_id,
                        rehab_generation=int(normalized.get("rehab_generation", 0)),
                        schedule_tick=schedule_tick,
                    )
                else:
                    decision_key = self._decision_key(
                        site_key_json=site_key_json,
                        rule_id=rule_id,
                        claimed_tick=int(claimed_tick),
                        rehab_generation=int(normalized.get("rehab_generation", 0)),
                        schedule_tick=schedule_tick,
                        step_id=step_id,
                    )
                decision, ecology_decisions, created = self._resolve_ecology_decision(
                    sim=sim,
                    site_key_json=site_key_json,
                    decisions=ecology_decisions,
                    decision_key=decision_key,
                    chance_percent=chance_percent,
                    marker_type=marker_type,
                    rule_id=rule_id,
                    d20_payload=use_d20_payload,
                    legacy_mode=legacy_mode,
                )
                if created:
                    if legacy_mode:
                        params = {
                            "tick": tick,
                            "site_key": copy.deepcopy(normalized["site_key"]),
                            "group_id": str(claim_group_id),
                            "decision_key": decision_key,
                            "roll_u32": int(decision["roll_u32"]),
                            "pct_roll": int(decision["pct_roll"]),
                            "threshold": int(decision["threshold"]),
                            "d20_roll": int(decision["d20_roll"]),
                            "result": str(decision["result"]),
                        }
                    else:
                        params = {
                            "tick": tick,
                            "site_key": copy.deepcopy(normalized["site_key"]),
                            "group_id": str(claim_group_id),
                            "decision_key": decision_key,
                            "rule_id": rule_id,
                            "marker_type": str(decision.get("marker_type", "no-op")),
                            "chance_percent": int(decision["chance_percent"]),
                            "pct_roll": int(decision["pct_roll"]),
                            "result": str(decision["result"]),
                        }
                        if int(decision.get("d20_roll", 0)) > 0:
                            params["d20_roll"] = int(decision["d20_roll"])
                    sim.schedule_event_at(
                        tick=tick + 1,
                        event_type=SITE_ECOLOGY_DECISION_EVENT_TYPE,
                        params=params,
                    )

                should_schedule = str(decision.get("result", "")).startswith("scheduled:")
                if should_schedule:
                    if use_d20_payload:
                        effect_payload["ecology_d20_roll"] = int(decision["d20_roll"])
                    pending_effects = self._schedule_growth_effect(pending_effects, effect_payload)
                    scheduled_count += 1
                    sim.schedule_event_at(
                        tick=tick + 1,
                        event_type=SITE_ECOLOGY_SCHEDULED_EFFECT_EVENT_TYPE,
                        params={
                            "tick": tick,
                            "site_key": copy.deepcopy(normalized["site_key"]),
                            "group_id": str(claim_group_id),
                            "step_id": step_id,
                            "effect_type": str(effect_payload["effect_type"]),
                            "decision_key": decision_key,
                        },
                    )

                applied_steps.append(step_id)
                applied_this_tick += 1

            if len(applied_steps) > SITE_GROWTH_LEDGER_MAX:
                applied_steps = applied_steps[-SITE_GROWTH_LEDGER_MAX:]

            normalized["growth_applied_steps"] = applied_steps
            normalized["pending_effects"] = pending_effects
            normalized["ecology_decisions"] = ecology_decisions
            site_state_by_key[site_key_json] = normalized

        local_state[LocalEncounterInstanceModule._STATE_SITE_STATE_BY_KEY] = dict(sorted(site_state_by_key.items()))
        sim.set_rules_state(LocalEncounterInstanceModule.name, local_state)
        if ordered_keys:
            ecology_state["next_site_cursor"] = (start_index + processed) % len(ordered_keys)
        else:
            ecology_state["next_site_cursor"] = 0
        sim.set_rules_state(self.name, ecology_state)
        sim.schedule_event_at(
            tick=tick + 1,
            event_type=SITE_ECOLOGY_TICK_EVENT_TYPE,
            params={
                "tick": tick,
                "processed_sites": int(processed),
                "scheduled_effects": int(scheduled_count),
                "site_cap": SITE_ECOLOGY_MAX_PROCESSED_PER_TICK,
            },
        )

    def _legacy_growth_rules(self, sim: Simulation) -> list[dict[str, Any]]:
        return [
            {
                "step_id": "fortify_1",
                "rule_id": "fortify_1",
                "threshold_ticks": int(sim.state.time.ticks_per_day) * 7,
                "chance_percent": SITE_ECOLOGY_FORTIFY_CHANCE_PERCENT,
                "marker_type": FORTIFICATION_PENDING_EFFECT_TYPE,
                "d20_payload": True,
                "effect_payload": {
                    "effect_type": FORTIFICATION_PENDING_EFFECT_TYPE,
                    "source": "site_ecology",
                    "priority": 0,
                },
            },
            {
                "step_id": "reinforce_1",
                "rule_id": "reinforce_1",
                "threshold_ticks": int(sim.state.time.ticks_per_day) * 30,
                "chance_percent": SITE_ECOLOGY_REINFORCE_CHANCE_PERCENT,
                "marker_type": REINHABITATION_PENDING_EFFECT_TYPE,
                "d20_payload": True,
                "effect_payload": {
                    "effect_type": REINHABITATION_PENDING_EFFECT_TYPE,
                    "source": "site_ecology",
                    "rehab_policy": REHAB_POLICY_ADD,
                    "priority": 10,
                },
            },
        ]

    def _configured_growth_rules(self, *, sim: Simulation, ecology_config: dict[str, Any]) -> list[dict[str, Any]]:
        ticks_per_day = int(sim.state.time.ticks_per_day)
        rules: list[dict[str, Any]] = []
        for rule in sorted(ecology_config.get("rules", []), key=lambda row: str(row["id"])):
            marker_type = str(rule["marker_type"])
            step_id = str(rule["id"])
            effect_payload: dict[str, Any] = {
                "effect_type": marker_type,
                "source": "site_ecology",
            }
            if marker_type == REINHABITATION_PENDING_EFFECT_TYPE:
                effect_payload["rehab_policy"] = REHAB_POLICY_ADD
            if "priority" in rule:
                effect_payload["priority"] = int(rule["priority"])
            rules.append(
                {
                    "step_id": step_id,
                    "rule_id": step_id,
                    "threshold_ticks": ticks_per_day,
                    "chance_percent": int(rule["chance_percent"]),
                    "marker_type": marker_type,
                    "d20_payload": bool(rule.get("d20_payload", False)),
                    "effect_payload": effect_payload,
                }
            )
        return rules

    def _legacy_decision_key(self, *, step_id: str, rehab_generation: int, schedule_tick: int) -> str:
        return f"{step_id}:rehab{int(rehab_generation)}:tick{int(schedule_tick)}"

    def _decision_key(
        self,
        *,
        site_key_json: str,
        rule_id: str,
        claimed_tick: int,
        rehab_generation: int,
        schedule_tick: int,
        step_id: str,
    ) -> str:
        return (
            f"site:{site_key_json}:rule:{rule_id}:claim:{int(claimed_tick)}:"
            f"rehab{int(rehab_generation)}:tick{int(schedule_tick)}:step:{step_id}"
        )

    def _resolve_ecology_decision(
        self,
        *,
        sim: Simulation,
        site_key_json: str,
        decisions: dict[str, Any],
        decision_key: str,
        chance_percent: int,
        marker_type: str,
        rule_id: str,
        d20_payload: bool,
        legacy_mode: bool,
    ) -> tuple[dict[str, Any], dict[str, Any], bool]:
        order = [str(key) for key in decisions.get("order", []) if isinstance(key, str) and key]
        by_key = {
            str(key): copy.deepcopy(value)
            for key, value in dict(decisions.get("by_key", {})).items()
            if isinstance(key, str) and key and isinstance(value, dict)
        }
        if decision_key in by_key:
            return by_key[decision_key], {"order": order, "by_key": by_key}, False

        rng = sim.rng_stream(f"site_ecology:{site_key_json}")
        roll_u32 = int(rng.randrange(0, 2**32))
        pct_roll = int((roll_u32 % 100) + 1)
        d20_roll = int(rng.randrange(1, SITE_ECOLOGY_D20_SIZE + 1)) if d20_payload else 0
        did_schedule = pct_roll <= int(chance_percent)
        if legacy_mode:
            decision_payload = {
                "roll_u32": roll_u32,
                "pct_roll": pct_roll,
                "threshold": int(chance_percent),
                "d20_roll": d20_roll,
                "result": f"scheduled:{marker_type}" if did_schedule else f"no-op:{marker_type}",
            }
        else:
            decision_payload = {
                "roll_u32": roll_u32,
                "pct_roll": pct_roll,
                "threshold": int(chance_percent),
                "chance_percent": int(chance_percent),
                "d20_roll": d20_roll,
                "rule_id": rule_id,
                "marker_type": marker_type,
                "result": f"scheduled:{marker_type}" if did_schedule else f"no-op:{marker_type}",
            }
        by_key[decision_key] = decision_payload
        order.append(decision_key)

        while len(order) > MAX_SITE_ECOLOGY_DECISIONS:
            evicted_key = order.pop(0)
            by_key.pop(evicted_key, None)

        return decision_payload, {"order": order, "by_key": by_key}, True

    def _schedule_growth_effect(self, pending_effects: list[Any], effect_payload: dict[str, Any]) -> list[dict[str, Any]]:
        local_module = LocalEncounterInstanceModule()
        normalized = local_module._normalize_pending_effects(pending_effects)
        effect_type = str(effect_payload.get("effect_type", ""))
        if any(str(effect.get("effect_type", "")) == effect_type for effect in normalized):
            return normalized
        combined = [*normalized, copy.deepcopy(effect_payload)]
        return local_module._normalize_pending_effects(combined)

    def _rules_state(self, sim: Simulation) -> dict[str, Any]:
        state = sim.get_rules_state(self.name)
        cursor = int(state.get("next_site_cursor", 0))
        if cursor < 0:
            cursor = 0
        return {"next_site_cursor": cursor}

    def _emit_claim_outcome(
        self,
        *,
        sim: Simulation,
        tick: int,
        site_key: dict[str, Any] | None,
        group_id: str,
        outcome: str,
    ) -> None:
        sim.schedule_event_at(
            tick=tick + 1,
            event_type=SITE_CLAIM_OUTCOME_EVENT_TYPE,
            params={
                "tick": tick,
                "site_key": copy.deepcopy(site_key),
                "group_id": group_id,
                "outcome": outcome,
            },
        )


class RumorPipelineModule(RuleModule):
    """Phase 6D-M15 deterministic rumor substrate from claim/arrival seams."""

    name = "rumor_pipeline"

    def on_event_executed(self, sim: Simulation, event: SimEvent) -> None:
        if event.event_type == GROUP_MOVE_ARRIVED_EVENT_TYPE:
            self._on_group_move_arrived(sim, event)
            return
        if event.event_type == CLAIM_OPPORTUNITY_CREATED_EVENT_TYPE:
            self._on_claim_opportunity_created(sim, event)
            return
        if event.event_type in {CLAIM_OPPORTUNITY_CONSUMED_EVENT_TYPE, SITE_CLAIM_OUTCOME_EVENT_TYPE}:
            self._on_site_claim(sim, event)

    def _on_group_move_arrived(self, sim: Simulation, event: SimEvent) -> None:
        group_id = self._optional_non_empty_string(event.params.get("group_id"))
        if group_id is None:
            return
        to_cell = event.params.get("to_cell")
        if not isinstance(to_cell, dict):
            return

        sites = sim.state.world.get_sites_at_location(to_cell)
        if not sites:
            self._append_rumor(
                sim=sim,
                rumor=RumorRecord(
                    rumor_id=self._rumor_id(
                        event=event,
                        kind="group_arrival",
                        site_key_json=None,
                        group_id=group_id,
                    ),
                    kind="group_arrival",
                    site_key=None,
                    group_id=group_id,
                    created_tick=int(event.tick),
                    consumed=False,
                ),
                dedupe_key=("group_arrival", "", group_id, "none"),
            )
            return

        for site in sorted(sites, key=lambda row: row.site_id):
            site_key = {
                "origin_space_id": str(site.location.get("space_id", "")),
                "origin_coord": copy.deepcopy(site.location.get("coord", {})),
                "template_id": f"site:{site.site_id}",
            }
            site_key_json = LocalEncounterInstanceModule._site_key_json(site_key)
            claim_state = self._site_claim_state(sim=sim, site_key=site_key)
            self._append_rumor(
                sim=sim,
                rumor=RumorRecord(
                    rumor_id=self._rumor_id(
                        event=event,
                        kind="group_arrival",
                        site_key_json=site_key_json,
                        group_id=group_id,
                    ),
                    kind="group_arrival",
                    site_key=site_key_json,
                    group_id=group_id,
                    created_tick=int(event.tick),
                    consumed=claim_state != "unclaimed",
                ),
                dedupe_key=("group_arrival", site_key_json, group_id, claim_state),
            )

    def _on_claim_opportunity_created(self, sim: Simulation, event: SimEvent) -> None:
        site_key_json = self._site_key_json_or_none(event.params.get("site_key"))
        group_id = self._optional_non_empty_string(event.params.get("group_id"))
        if site_key_json is None or group_id is None:
            return
        self._append_rumor(
            sim=sim,
            rumor=RumorRecord(
                rumor_id=self._rumor_id(
                    event=event,
                    kind="claim_opportunity",
                    site_key_json=site_key_json,
                    group_id=group_id,
                ),
                kind="claim_opportunity",
                site_key=site_key_json,
                group_id=group_id,
                created_tick=int(event.tick),
                consumed=False,
            ),
            dedupe_key=("claim_opportunity", site_key_json, group_id, "open"),
        )

    def _on_site_claim(self, sim: Simulation, event: SimEvent) -> None:
        site_key_json = self._site_key_json_or_none(event.params.get("site_key"))
        group_id = self._optional_non_empty_string(event.params.get("group_id"))
        if site_key_json is None or group_id is None:
            return
        self._append_rumor(
            sim=sim,
            rumor=RumorRecord(
                rumor_id=self._rumor_id(
                    event=event,
                    kind="site_claim",
                    site_key_json=site_key_json,
                    group_id=group_id,
                ),
                kind="site_claim",
                site_key=site_key_json,
                group_id=group_id,
                created_tick=int(event.tick),
                consumed=True,
            ),
            dedupe_key=("site_claim", site_key_json, group_id, "closed"),
        )

    def _append_rumor(self, *, sim: Simulation, rumor: RumorRecord, dedupe_key: tuple[str, str, str, str]) -> None:
        if self._has_dedupe(sim=sim, dedupe_key=dedupe_key):
            return
        sim.state.world.append_rumor(self._apply_ttl_defaults(sim=sim, rumor=rumor))

    def _apply_ttl_defaults(self, *, sim: Simulation, rumor: RumorRecord) -> RumorRecord:
        if rumor.expires_tick is not None:
            return rumor
        ttl_config = sim.state.world.rumor_ttl_config
        if not bool(ttl_config.get("enabled", True)):
            return rumor
        ttl_ticks = self._resolve_ttl_ticks(sim=sim, rumor=rumor)
        if ttl_ticks is None:
            return rumor
        return RumorRecord(
            rumor_id=rumor.rumor_id,
            kind=rumor.kind,
            site_key=rumor.site_key,
            group_id=rumor.group_id,
            created_tick=rumor.created_tick,
            consumed=rumor.consumed,
            expires_tick=rumor.created_tick + ttl_ticks,
        )

    def _resolve_ttl_ticks(self, *, sim: Simulation, rumor: RumorRecord) -> int | None:
        ttl_config = sim.state.world.rumor_ttl_config
        ttl_by_kind = ttl_config.get("ttl_by_kind", {})
        if not isinstance(ttl_by_kind, dict):
            return None
        base_ttl = ttl_by_kind.get(rumor.kind)
        if isinstance(base_ttl, bool) or not isinstance(base_ttl, int):
            return None

        site_template_override = self._resolve_site_template_override_ttl(
            sim=sim,
            rumor=rumor,
            ttl_config=ttl_config,
        )
        if site_template_override is not None:
            return site_template_override

        region_override = self._resolve_region_override_ttl(
            sim=sim,
            rumor=rumor,
            ttl_config=ttl_config,
        )
        if region_override is not None:
            return region_override
        return base_ttl

    def _resolve_site_template_override_ttl(
        self,
        *,
        sim: Simulation,
        rumor: RumorRecord,
        ttl_config: dict[str, Any],
    ) -> int | None:
        raw_overrides = ttl_config.get("ttl_by_site_template", {})
        if not isinstance(raw_overrides, dict):
            return None
        candidates = self._site_template_candidates(sim=sim, rumor=rumor)
        if not candidates:
            return None
        for template_id in candidates:
            row = raw_overrides.get(template_id)
            if not isinstance(row, dict):
                continue
            ttl_ticks = row.get(rumor.kind)
            if isinstance(ttl_ticks, bool) or not isinstance(ttl_ticks, int):
                continue
            return ttl_ticks
        return None

    def _resolve_region_override_ttl(
        self,
        *,
        sim: Simulation,
        rumor: RumorRecord,
        ttl_config: dict[str, Any],
    ) -> int | None:
        raw_overrides = ttl_config.get("ttl_by_region", {})
        if not isinstance(raw_overrides, dict):
            return None
        region_id = self._resolve_region_id(sim=sim, rumor=rumor)
        if region_id is None:
            return None
        row = raw_overrides.get(region_id)
        if not isinstance(row, dict):
            return None
        ttl_ticks = row.get(rumor.kind)
        if isinstance(ttl_ticks, bool) or not isinstance(ttl_ticks, int):
            return None
        return ttl_ticks

    def _site_template_candidates(self, *, sim: Simulation, rumor: RumorRecord) -> list[str]:
        site_key = self._site_key_dict_or_none(rumor.site_key)
        if site_key is None:
            return []

        candidates: list[str] = []
        seen: set[str] = set()

        template_id = self._normalized_optional_id(site_key.get("template_id"))
        if template_id is not None:
            candidates.append(template_id)
            seen.add(template_id)

        location_ref = self._site_key_location_ref(site_key)
        if location_ref is None:
            return candidates

        for site in sim.state.world.get_sites_at_location(location_ref):
            site_template_id = self._normalized_optional_id(f"site:{site.site_id}")
            if site_template_id is not None and site_template_id not in seen:
                seen.add(site_template_id)
                candidates.append(site_template_id)
            site_type = self._normalized_optional_id(site.site_type)
            if site_type is not None and site_type not in seen:
                seen.add(site_type)
                candidates.append(site_type)
        return candidates

    def _resolve_region_id(self, *, sim: Simulation, rumor: RumorRecord) -> str | None:
        site_key = self._site_key_dict_or_none(rumor.site_key)
        if site_key is None:
            return None
        region_id = self._normalized_optional_id(site_key.get("region_id"))
        if region_id is not None:
            return region_id
        location_ref = self._site_key_location_ref(site_key)
        if location_ref is None:
            return None
        candidates = {
            self._normalized_optional_id(site.location.get("region_id"))
            for site in sim.state.world.get_sites_at_location(location_ref)
        }
        candidates.discard(None)
        if not candidates:
            return None
        return sorted(candidates)[0]

    def _site_key_dict_or_none(self, site_key_json: str | None) -> dict[str, Any] | None:
        if not isinstance(site_key_json, str) or not site_key_json:
            return None
        try:
            parsed = json.loads(site_key_json)
        except json.JSONDecodeError:
            return None
        if not isinstance(parsed, dict):
            return None
        return parsed

    def _site_key_location_ref(self, site_key: dict[str, Any]) -> dict[str, Any] | None:
        origin_space_id = self._normalized_optional_id(site_key.get("origin_space_id"))
        origin_coord = site_key.get("origin_coord")
        if origin_space_id is None or not isinstance(origin_coord, dict):
            return None
        return {"space_id": origin_space_id, "coord": origin_coord}

    def _normalized_optional_id(self, value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        normalized = value.strip()
        if not normalized:
            return None
        return normalized

    def _has_dedupe(self, *, sim: Simulation, dedupe_key: tuple[str, str, str, str]) -> bool:
        kind, site_key, group_id, state_token = dedupe_key
        expected_consumed = state_token != "unclaimed" and state_token != "open"
        for record in sim.state.world.rumors:
            if str(record.get("kind", "")) != kind:
                continue
            if str(record.get("site_key", "")) != site_key:
                continue
            if str(record.get("group_id", "")) != group_id:
                continue
            if bool(record.get("consumed", False)) != expected_consumed:
                continue
            return True
        return False

    def _site_claim_state(self, *, sim: Simulation, site_key: dict[str, Any]) -> str:
        local_state = sim.get_rules_state(LocalEncounterInstanceModule.name)
        if not isinstance(local_state, dict):
            return "unclaimed"
        site_state_by_key = local_state.get(LocalEncounterInstanceModule._STATE_SITE_STATE_BY_KEY, {})
        if not isinstance(site_state_by_key, dict):
            return "unclaimed"
        site_key_json = LocalEncounterInstanceModule._site_key_json(site_key)
        row = site_state_by_key.get(site_key_json)
        if not isinstance(row, dict):
            return "unclaimed"
        normalized = LocalEncounterInstanceModule()._normalize_site_state_payload(row)
        if not isinstance(normalized, dict):
            return "unclaimed"
        claimed_by_group_id = normalized.get("claimed_by_group_id")
        if isinstance(claimed_by_group_id, str) and claimed_by_group_id:
            return f"claimed:{claimed_by_group_id}"
        return "unclaimed"

    def _rumor_id(self, *, event: SimEvent, kind: str, site_key_json: str | None, group_id: str | None) -> str:
        canonical_components = {
            "tick": int(event.tick),
            "event_id": event.event_id,
            "kind": kind,
            "site_key": site_key_json,
            "group_id": group_id,
        }
        digest = hashlib.sha256(
            json.dumps(canonical_components, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()[:12]
        return f"{int(event.tick)}:{event.event_id}:rumor:{digest}"

    def _site_key_json_or_none(self, value: Any) -> str | None:
        if not isinstance(value, dict):
            return None
        return LocalEncounterInstanceModule._site_key_json(value)

    def _optional_non_empty_string(self, value: Any) -> str | None:
        if not isinstance(value, str) or not value:
            return None
        return value


class RumorDecayModule(RuleModule):
    """Phase 6D-M20 deterministic bounded rumor expiration maintenance."""

    name = "rumor_decay"

    def on_simulation_start(self, sim: Simulation) -> None:
        scheduler = sim.get_rule_module(PeriodicScheduler.name)
        if scheduler is None:
            scheduler = PeriodicScheduler()
            sim.register_rule_module(scheduler)
        if not isinstance(scheduler, PeriodicScheduler):
            raise TypeError("periodic_scheduler module must be a PeriodicScheduler")
        scheduler.register_task(
            task_name=RUMOR_DECAY_TASK_NAME,
            interval_ticks=RUMOR_DECAY_INTERVAL_TICKS,
            start_tick=0,
        )
        scheduler.set_task_callback(RUMOR_DECAY_TASK_NAME, self._build_periodic_callback())

    def _build_periodic_callback(self) -> Any:
        def _on_periodic(sim: Simulation, tick: int) -> None:
            self._process_decay_tick(sim=sim, tick=tick)

        return _on_periodic

    def _process_decay_tick(self, *, sim: Simulation, tick: int) -> None:
        rumors = sim.state.world.rumors
        if not rumors:
            sim.state.world.rumor_decay_cursor = 0
            return

        cursor = int(sim.state.world.rumor_decay_cursor)
        if cursor < 0:
            cursor = 0
        if cursor >= len(rumors):
            cursor = len(rumors) - 1

        scanned = 0
        removed = 0
        while scanned < MAX_RUMOR_DECAY_PROCESSED_PER_TICK and rumors:
            if cursor >= len(rumors):
                cursor = 0
            rumor = rumors[cursor]
            expires_tick = rumor.get("expires_tick")
            if isinstance(expires_tick, int) and not isinstance(expires_tick, bool) and tick >= expires_tick:
                del rumors[cursor]
                removed += 1
                if not rumors:
                    cursor = 0
                    break
                if cursor >= len(rumors):
                    cursor = 0
            else:
                cursor = (cursor + 1) % len(rumors)
            scanned += 1

        sim.state.world.rumor_decay_cursor = cursor if rumors else 0
        if scanned > 0:
            sim._append_event_trace_entry(
                {
                    "tick": int(tick),
                    "event_id": sim._trace_event_id_as_int(f"rumor-decay:{tick}"),
                    "event_type": RUMOR_DECAY_TICK_EVENT_TYPE,
                    "params": {
                        "scanned_count": scanned,
                        "removed_count": removed,
                    },
                }
            )


class RumorQueryModule(RuleModule):
    """Phase 6D-M16 read-only deterministic rumor list/filter/pagination seam."""

    name = "rumor_query"
    _DEFAULT_LIMIT = 20
    _MIN_LIMIT = 1
    _MAX_LIMIT = 100
    _UINT32_SPAN = 1 << 32

    def on_command(self, sim: Simulation, command: SimCommand, command_index: int) -> bool:
        if command.command_type != LIST_RUMORS_INTENT:
            if command.command_type != SELECT_RUMORS_INTENT:
                return False
            return self._on_select_rumors_intent(sim=sim, command=command, command_index=command_index)

        action_uid = f"{int(command.tick)}:{int(command_index)}"
        params = command.params if isinstance(command.params, dict) else {}
        validation = self._validated_filters(params)
        if validation["outcome"] != "ok":
            sim.append_command_outcome(
                {
                    "kind": LIST_RUMORS_OUTCOME_KIND,
                    "action_uid": action_uid,
                    "outcome": validation["outcome"],
                    "diagnostic": validation["diagnostic"],
                    "rumors": [],
                    "next_cursor": None,
                }
            )
            return True

        limit = int(validation["limit"])
        cursor = validation["cursor"]
        filtered = self._filtered_sorted_rumors(sim=sim, filters=validation)
        page, next_cursor = self._paged_slice(filtered=filtered, limit=limit, cursor=cursor)

        sim.append_command_outcome(
            {
                "kind": LIST_RUMORS_OUTCOME_KIND,
                "action_uid": action_uid,
                "outcome": "ok",
                "diagnostic": validation["diagnostic"],
                "rumors": copy.deepcopy(page),
                "next_cursor": next_cursor,
            }
        )
        return True

    def _on_select_rumors_intent(self, *, sim: Simulation, command: SimCommand, command_index: int) -> bool:
        action_uid = f"{int(command.tick)}:{int(command_index)}"
        params = command.params if isinstance(command.params, dict) else {}
        validation = self._validated_selection_filters(params)
        if validation["outcome"] != "ok":
            sim.append_command_outcome(
                {
                    "kind": SELECT_RUMORS_OUTCOME_KIND,
                    "action_uid": action_uid,
                    "outcome": validation["outcome"],
                    "diagnostic": validation["diagnostic"],
                    "selection": [],
                    "next_cursor": None,
                    "decision_reused": False,
                }
            )
            return True

        decision_key = self._decision_key_for(selection_tick=int(command.tick), validation=validation)
        existing_decision = sim.state.world.rumor_selection_decisions.get(decision_key)
        created_decision = False
        if existing_decision is None:
            selection_ids, rng_rolls, candidate_count = self._select_rumor_ids(sim=sim, selection_tick=int(command.tick), validation=validation)
            record = {
                "selected_rumor_ids": selection_ids,
                "rng_rolls": rng_rolls,
                "created_tick": int(command.tick),
                "scope": validation["scope"],
                "seed_tag": validation["seed_tag"],
                "k": int(validation["k"]),
                "filters": self._decision_filters_snapshot(validation),
                "candidate_count": candidate_count,
            }
            sim.state.world.upsert_rumor_selection_decision(decision_key=decision_key, record=record)
            existing_decision = sim.state.world.rumor_selection_decisions[decision_key]
            created_decision = True
            sim._append_event_trace_entry(
                {
                    "tick": int(command.tick),
                    "event_id": sim._trace_event_id_as_int(f"rumor-selection:{decision_key}"),
                    "event_type": RUMOR_SELECTION_DECISION_EVENT_TYPE,
                    "params": {
                        "decision_key": decision_key,
                        "scope": validation["scope"],
                        "seed_tag": validation["seed_tag"],
                        "selection_tick": int(command.tick),
                        "k": int(validation["k"]),
                        "candidate_count": int(existing_decision.get("candidate_count", 0)),
                        "selected_ids": list(existing_decision.get("selected_rumor_ids", [])),
                    },
                }
            )

        offset = int(validation["cursor_offset"])
        selected_ids = list(existing_decision.get("selected_rumor_ids", []))
        page = selected_ids[offset : offset + int(validation["k"])]
        next_offset = offset + int(validation["k"])
        next_cursor = str(next_offset) if next_offset < len(selected_ids) else None
        rumor_lookup = {
            str(rumor.get("rumor_id", "")): rumor
            for rumor in sim.state.world.rumors
        }
        selection_rows = [copy.deepcopy(rumor_lookup[rumor_id]) for rumor_id in page if rumor_id in rumor_lookup]

        sim.append_command_outcome(
            {
                "kind": SELECT_RUMORS_OUTCOME_KIND,
                "action_uid": action_uid,
                "outcome": "ok",
                "diagnostic": validation["diagnostic"],
                "selection": selection_rows,
                "next_cursor": next_cursor,
                "decision_key": decision_key,
                "decision_reused": not created_decision,
            }
        )
        return True

    def _validated_selection_filters(self, params: dict[str, Any]) -> dict[str, Any]:
        scope = params.get("scope", RUMOR_SELECTION_DEFAULT_SCOPE)
        if not isinstance(scope, str) or not scope:
            return self._invalid_selection(diagnostic="invalid_scope")

        raw_kind = params.get("kind")
        kind = self._optional_non_empty_str(raw_kind)
        if raw_kind is not None and kind is None:
            return self._invalid_selection(diagnostic="invalid_kind")
        if kind is not None and kind not in RUMOR_KINDS:
            return self._invalid_selection(diagnostic="invalid_kind")

        raw_site_key = params.get("site_key")
        site_key = self._optional_non_empty_str(raw_site_key)
        if raw_site_key is not None and site_key is None:
            return self._invalid_selection(diagnostic="invalid_site_key")

        raw_group_id = params.get("group_id")
        group_id = self._optional_non_empty_str(raw_group_id)
        if raw_group_id is not None and group_id is None:
            return self._invalid_selection(diagnostic="invalid_group_id")

        consumed: bool | None = None
        raw_consumed = params.get("consumed")
        if raw_consumed is not None:
            if not isinstance(raw_consumed, bool):
                return self._invalid_selection(diagnostic="invalid_consumed")
            consumed = raw_consumed

        seed_tag = params.get("seed_tag", RUMOR_SELECTION_DEFAULT_SEED_TAG)
        if not isinstance(seed_tag, str) or not seed_tag:
            return self._invalid_selection(diagnostic="invalid_seed_tag")
        if len(seed_tag) > RUMOR_SELECTION_MAX_SEED_TAG_LEN:
            return self._invalid_selection(diagnostic="invalid_seed_tag")
        if any(ord(ch) < 32 or ord(ch) == 127 for ch in seed_tag):
            return self._invalid_selection(diagnostic="invalid_seed_tag")

        k = RUMOR_SELECTION_DEFAULT_K
        diagnostic: str | None = None
        raw_k = params.get("k")
        if raw_k is not None:
            if isinstance(raw_k, bool) or not isinstance(raw_k, int):
                return self._invalid_selection(diagnostic="invalid_k")
            clamped_k = max(RUMOR_SELECTION_MIN_K, min(RUMOR_SELECTION_MAX_K, raw_k))
            if clamped_k != raw_k:
                diagnostic = "k_clamped"
            k = int(clamped_k)

        cursor_offset = 0
        raw_cursor = params.get("cursor")
        if raw_cursor is not None:
            if not isinstance(raw_cursor, str):
                return self._invalid_selection(diagnostic="invalid_cursor")
            cursor_offset = self._parse_selection_cursor(raw_cursor)
            if cursor_offset is None:
                return self._invalid_selection(diagnostic="invalid_cursor")

        return {
            "outcome": "ok",
            "diagnostic": diagnostic,
            "scope": scope,
            "kind": kind,
            "site_key": site_key,
            "group_id": group_id,
            "consumed": consumed,
            "seed_tag": seed_tag,
            "k": k,
            "cursor_offset": cursor_offset,
        }

    def _decision_key_for(self, *, selection_tick: int, validation: dict[str, Any]) -> str:
        filters = self._decision_filters_snapshot(validation)
        digest = hashlib.sha256(
            json.dumps(filters, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return f"{validation['scope']}|{validation['seed_tag']}|{int(selection_tick)}|{digest}"

    def _decision_filters_snapshot(self, validation: dict[str, Any]) -> dict[str, Any]:
        return {
            "kind": validation["kind"],
            "site_key": validation["site_key"],
            "group_id": validation["group_id"],
            "consumed": validation["consumed"],
        }

    def _select_rumor_ids(
        self,
        *,
        sim: Simulation,
        selection_tick: int,
        validation: dict[str, Any],
    ) -> tuple[list[str], list[int], int]:
        candidates = self._scored_candidates(sim=sim, selection_tick=selection_tick, filters=validation)
        if not candidates:
            return [], [], 0
        rng = sim.rng_stream(f"rumor_select:{validation['scope']}:{validation['seed_tag']}")
        picks = min(int(validation["k"]), len(candidates))
        selected_ids: list[str] = []
        rng_rolls: list[int] = []
        mutable = list(candidates)
        for _ in range(picks):
            total_weight = sum(score for _, score in mutable)
            if total_weight <= 0:
                break
            draw = self._uniform_index(rng=rng, upper_exclusive=total_weight)
            rng_rolls.append(draw)
            running = 0
            selected_index = 0
            for index, (_, score) in enumerate(mutable):
                running += score
                if draw < running:
                    selected_index = index
                    break
            selected_id, _ = mutable.pop(selected_index)
            selected_ids.append(selected_id)
        return selected_ids, rng_rolls, len(candidates)

    def _scored_candidates(self, *, sim: Simulation, selection_tick: int, filters: dict[str, Any]) -> list[tuple[str, int]]:
        candidates = self._filtered_sorted_rumors(sim=sim, filters=self._selection_filter_defaults(filters))
        scored: list[tuple[str, int]] = []
        for rumor in candidates:
            rumor_id = str(rumor.get("rumor_id", ""))
            if not rumor_id:
                continue
            score = self._rumor_score(rumor=rumor, selection_tick=selection_tick)
            if score <= 0:
                continue
            scored.append((rumor_id, score))
        return scored

    def _selection_filter_defaults(self, filters: dict[str, Any]) -> dict[str, Any]:
        consumed = filters.get("consumed")
        if consumed is None:
            consumed = False
        return {
            "kind": filters.get("kind"),
            "site_key": filters.get("site_key"),
            "group_id": filters.get("group_id"),
            "consumed": consumed,
        }

    def _rumor_score(self, *, rumor: dict[str, Any], selection_tick: int) -> int:
        kind = str(rumor.get("kind", ""))
        base = int(RUMOR_SELECTION_KIND_BASE_POINTS.get(kind, 0))
        if base <= 0:
            return 0
        created_tick = int(rumor.get("created_tick", 0))
        age_ticks = max(0, int(selection_tick) - created_tick)
        numerator = base * RUMOR_SELECTION_RECENCY_HALFLIFE_TICKS
        denominator = RUMOR_SELECTION_RECENCY_HALFLIFE_TICKS + age_ticks
        score = numerator // denominator
        return max(1, score)

    def _uniform_index(self, *, rng: Any, upper_exclusive: int) -> int:
        if upper_exclusive <= 0:
            raise ValueError("upper_exclusive must be > 0")
        reject_threshold = self._UINT32_SPAN - (self._UINT32_SPAN % upper_exclusive)
        while True:
            raw = int(rng.getrandbits(32))
            if raw < reject_threshold:
                return raw % upper_exclusive

    def _parse_selection_cursor(self, raw_cursor: str) -> int | None:
        if raw_cursor.startswith("+"):
            return None
        try:
            value = int(raw_cursor)
        except ValueError:
            return None
        if value < 0:
            return None
        if str(value) != raw_cursor:
            return None
        return value

    def _invalid_selection(self, *, diagnostic: str) -> dict[str, Any]:
        return {
            "outcome": "invalid_params",
            "diagnostic": diagnostic,
            "scope": RUMOR_SELECTION_DEFAULT_SCOPE,
            "kind": None,
            "site_key": None,
            "group_id": None,
            "consumed": None,
            "seed_tag": RUMOR_SELECTION_DEFAULT_SEED_TAG,
            "k": RUMOR_SELECTION_DEFAULT_K,
            "cursor_offset": 0,
        }

    def _validated_filters(self, params: dict[str, Any]) -> dict[str, Any]:
        raw_kind = params.get("kind")
        kind = self._optional_non_empty_str(raw_kind)
        if raw_kind is not None and kind is None:
            return self._invalid(diagnostic="invalid_kind")
        if kind is not None and kind not in RUMOR_KINDS:
            return self._invalid(diagnostic="invalid_kind")

        raw_site_key = params.get("site_key")
        site_key = self._optional_non_empty_str(raw_site_key)
        if raw_site_key is not None and site_key is None:
            return self._invalid(diagnostic="invalid_site_key")

        raw_group_id = params.get("group_id")
        group_id = self._optional_non_empty_str(raw_group_id)
        if raw_group_id is not None and group_id is None:
            return self._invalid(diagnostic="invalid_group_id")

        raw_consumed = params.get("consumed")
        consumed: bool | None = None
        if raw_consumed is not None:
            if not isinstance(raw_consumed, bool):
                return self._invalid(diagnostic="invalid_consumed")
            consumed = raw_consumed

        limit = self._DEFAULT_LIMIT
        diagnostic: str | None = None
        raw_limit = params.get("limit")
        if raw_limit is not None:
            if isinstance(raw_limit, bool) or not isinstance(raw_limit, int):
                return self._invalid(diagnostic="invalid_limit")
            clamped = max(self._MIN_LIMIT, min(self._MAX_LIMIT, raw_limit))
            limit = int(clamped)
            if clamped != raw_limit:
                diagnostic = "limit_clamped"

        cursor: tuple[int, str] | None = None
        raw_cursor = params.get("cursor")
        if raw_cursor is not None:
            if not isinstance(raw_cursor, str):
                return self._invalid(diagnostic="invalid_cursor")
            cursor = self._parse_cursor(raw_cursor)
            if cursor is None:
                return self._invalid(diagnostic="invalid_cursor")

        return {
            "outcome": "ok",
            "diagnostic": diagnostic,
            "kind": kind,
            "site_key": site_key,
            "group_id": group_id,
            "consumed": consumed,
            "limit": limit,
            "cursor": cursor,
        }

    def _filtered_sorted_rumors(self, *, sim: Simulation, filters: dict[str, Any]) -> list[dict[str, Any]]:
        kind = filters["kind"]
        site_key = filters["site_key"]
        group_id = filters["group_id"]
        consumed = filters["consumed"]
        filtered: list[dict[str, Any]] = []
        for rumor in sim.state.world.rumors:
            if kind is not None and str(rumor.get("kind", "")) != kind:
                continue
            if site_key is not None and str(rumor.get("site_key", "")) != site_key:
                continue
            if group_id is not None and str(rumor.get("group_id", "")) != group_id:
                continue
            if consumed is not None and bool(rumor.get("consumed", False)) != consumed:
                continue
            filtered.append(rumor)
        return sorted(filtered, key=lambda row: (-int(row.get("created_tick", 0)), str(row.get("rumor_id", ""))))

    def _paged_slice(
        self,
        *,
        filtered: list[dict[str, Any]],
        limit: int,
        cursor: tuple[int, str] | None,
    ) -> tuple[list[dict[str, Any]], str | None]:
        start_index = 0
        if cursor is not None:
            start_index = len(filtered)
            for idx, row in enumerate(filtered):
                boundary = (int(row.get("created_tick", 0)), str(row.get("rumor_id", "")))
                if self._cursor_is_after(boundary=boundary, cursor=cursor):
                    start_index = idx
                    break

        page = filtered[start_index : start_index + limit]
        if start_index + limit >= len(filtered) or not page:
            return page, None
        last = page[-1]
        return page, self._cursor_for(rumor=last)

    def _cursor_for(self, *, rumor: dict[str, Any]) -> str:
        return f"{int(rumor.get('created_tick', 0))}:{str(rumor.get('rumor_id', ''))}"

    def _parse_cursor(self, raw_cursor: str) -> tuple[int, str] | None:
        parts = raw_cursor.split(":", 1)
        if len(parts) != 2:
            return None
        tick_raw, rumor_id = parts
        if not tick_raw or not rumor_id:
            return None
        if tick_raw.startswith("+"):
            return None
        try:
            created_tick = int(tick_raw)
        except ValueError:
            return None
        return (created_tick, rumor_id)

    def _cursor_is_after(self, *, boundary: tuple[int, str], cursor: tuple[int, str]) -> bool:
        boundary_tick, boundary_id = boundary
        cursor_tick, cursor_id = cursor
        if boundary_tick < cursor_tick:
            return True
        if boundary_tick > cursor_tick:
            return False
        return boundary_id > cursor_id

    def _optional_non_empty_str(self, value: Any) -> str | None:
        if not isinstance(value, str) or not value:
            return None
        return value

    def _invalid(self, *, diagnostic: str) -> dict[str, Any]:
        return {
            "outcome": "invalid_params",
            "diagnostic": diagnostic,
            "kind": None,
            "site_key": None,
            "group_id": None,
            "consumed": None,
            "limit": self._DEFAULT_LIMIT,
            "cursor": None,
        }


class SpawnMaterializationModule(RuleModule):
    """Phase 5C deterministic materialization from spawn descriptors into entities."""

    name = "spawn_materialization"

    def on_simulation_start(self, sim: Simulation) -> None:
        sim.set_rules_state(self.name, self._rules_state(sim))

    def on_tick_start(self, sim: Simulation, tick: int) -> None:
        self._materialize(sim)

    def _materialize(self, sim: Simulation) -> None:
        state = self._rules_state(sim)
        materialized_ids = set(state["materialized_entity_ids"])
        warnings = list(state["warnings"])
        warning_keys = {
            (warning["action_uid"], warning["reason"], warning["topology_type"])
            for warning in warnings
        }

        for descriptor in sim.state.world.spawn_descriptors:
            action_uid = self._required_non_empty_string(descriptor.get("action_uid"), field_name="action_uid")
            template_id = self._required_non_empty_string(descriptor.get("template_id"), field_name="template_id")
            quantity = int(descriptor.get("quantity", 0))
            if quantity < 1:
                raise ValueError("spawn_descriptor quantity must be >= 1")

            placement = self._placement_from_location(descriptor.get("location"))
            if placement is None:
                topology_type = self._topology_type_from_location(descriptor.get("location"))
                warning_key = (action_uid, "unsupported_topology", topology_type)
                if warning_key not in warning_keys:
                    warnings.append(
                        {
                            "action_uid": action_uid,
                            "reason": "unsupported_topology",
                            "topology_type": topology_type,
                        }
                    )
                    warning_keys.add(warning_key)
                continue
            for index in range(quantity):
                entity_id = self._entity_id(action_uid=action_uid, index=index)
                if entity_id in sim.state.entities:
                    materialized_ids.add(entity_id)
                    continue

                entity = EntityState(
                    entity_id=entity_id,
                    position_x=placement["position_x"],
                    position_y=placement["position_y"],
                    speed_per_tick=0.0,
                    space_id=placement["space_id"],
                )
                entity.template_id = template_id
                entity.source_action_uid = action_uid
                sim.add_entity(entity)
                materialized_ids.add(entity_id)

        state["materialized_entity_ids"] = sorted(materialized_ids)
        state["warnings"] = warnings[-200:]
        sim.set_rules_state(self.name, state)

    def _rules_state(self, sim: Simulation) -> dict[str, Any]:
        state = sim.get_rules_state(self.name)
        raw_ids = state.get("materialized_entity_ids", [])
        if not isinstance(raw_ids, list):
            raise ValueError("spawn_materialization.rules_state.materialized_entity_ids must be a list")
        normalized_ids: list[str] = []
        for value in raw_ids:
            if not isinstance(value, str) or not value:
                raise ValueError("spawn_materialization.rules_state.materialized_entity_ids entries must be strings")
            normalized_ids.append(value)
        raw_warnings = state.get("warnings", [])
        normalized_warnings: list[dict[str, Any]] = []
        if isinstance(raw_warnings, list):
            for warning in raw_warnings:
                if not isinstance(warning, dict):
                    continue
                action_uid = warning.get("action_uid")
                reason = warning.get("reason")
                topology_type = warning.get("topology_type")
                if isinstance(action_uid, str) and isinstance(reason, str) and isinstance(topology_type, str):
                    normalized_warnings.append(
                        {
                            "action_uid": action_uid,
                            "reason": reason,
                            "topology_type": topology_type,
                        }
                    )
        return {"materialized_entity_ids": sorted(set(normalized_ids)), "warnings": normalized_warnings}

    def _placement_from_location(self, location_payload: Any) -> dict[str, Any] | None:
        if not isinstance(location_payload, dict):
            raise ValueError("spawn_descriptor.location must be an object")
        location = LocationRef.from_dict(location_payload)
        if location.topology_type == OVERWORLD_HEX_TOPOLOGY:
            q = int(location.coord["q"])
            r = int(location.coord["r"])
            position_x, position_y = axial_to_world_xy(HexCoord(q=q, r=r))
            return {
                "space_id": location.space_id,
                "position_x": position_x,
                "position_y": position_y,
            }
        if location.topology_type == SQUARE_GRID_TOPOLOGY:
            x = int(location.coord["x"])
            y = int(location.coord["y"])
            position_x, position_y = square_grid_cell_to_world_xy(x, y)
            return {
                "space_id": location.space_id,
                "position_x": position_x,
                "position_y": position_y,
            }
        return None

    def _topology_type_from_location(self, location_payload: Any) -> str:
        if not isinstance(location_payload, dict):
            return ""
        topology_type = location_payload.get("topology_type")
        if not isinstance(topology_type, str):
            return ""
        return topology_type

    def _required_non_empty_string(self, value: Any, *, field_name: str) -> str:
        if not isinstance(value, str) or not value:
            raise ValueError(f"spawn_descriptor {field_name} must be a non-empty string")
        return value

    def _entity_id(self, *, action_uid: str, index: int) -> str:
        return f"{SPAWN_ENTITY_ID_PREFIX}:{action_uid}:{index}"


class EncounterCheckModule(RuleModule):
    """Phase 4B deterministic encounter eligibility gate skeleton.

    Intentionally content-free: this module only emits and accounts for
    deterministic encounter-check events.
    """

    name = "encounter_check"
    _STATE_LAST_CHECK_TICK = "last_check_tick"
    _STATE_CHECKS_EMITTED = "checks_emitted"
    _STATE_ELIGIBLE_COUNT = "eligible_count"
    _STATE_INELIGIBLE_STREAK = "ineligible_streak"
    _STATE_COOLDOWN_UNTIL_TICK = "cooldown_until_tick"
    _TASK_NAME = "encounter_check:global"
    _RNG_STREAM_NAME = "encounter_check"

    def on_simulation_start(self, sim: Simulation) -> None:
        scheduler = sim.get_rule_module(PeriodicScheduler.name)
        if scheduler is None:
            scheduler = PeriodicScheduler()
            sim.register_rule_module(scheduler)
        if not isinstance(scheduler, PeriodicScheduler):
            raise TypeError("periodic_scheduler module must be a PeriodicScheduler")

        state = self._rules_state(sim)
        sim.set_rules_state(self.name, state)

        scheduler.register_task(
            task_name=self._TASK_NAME,
            interval_ticks=ENCOUNTER_CHECK_INTERVAL,
            start_tick=0,
        )
        scheduler.set_task_callback(self._TASK_NAME, self._build_emit_callback())

    def on_event_executed(self, sim: Simulation, event: SimEvent) -> None:
        if event.event_type == TRAVEL_STEP_EVENT_TYPE:
            self._on_travel_step(sim, event)
            return
        if event.event_type == ENCOUNTER_ROLL_EVENT_TYPE:
            self._on_encounter_roll(sim, event)
            return
        if event.event_type == ENCOUNTER_RESULT_STUB_EVENT_TYPE:
            self._on_encounter_result_stub(sim, event)
            return
        if event.event_type != ENCOUNTER_CHECK_EVENT_TYPE:
            return

        state = self._rules_state(sim)
        check_tick = int(event.params.get("tick", event.tick))
        trigger = str(event.params.get("trigger", ENCOUNTER_TRIGGER_IDLE))
        location = self._location_for_check(sim=sim, event=event, trigger=trigger)
        rng = sim.rng_stream(self._RNG_STREAM_NAME)

        state[self._STATE_LAST_CHECK_TICK] = check_tick
        state[self._STATE_CHECKS_EMITTED] = int(state[self._STATE_CHECKS_EMITTED]) + 1

        cooldown_until_tick = int(state[self._STATE_COOLDOWN_UNTIL_TICK])
        if check_tick < cooldown_until_tick:
            state[self._STATE_INELIGIBLE_STREAK] = int(state[self._STATE_INELIGIBLE_STREAK]) + 1
            sim.set_rules_state(self.name, state)
            return

        eligible_roll = rng.randrange(0, 100)
        eligible = eligible_roll < ENCOUNTER_CHANCE_PERCENT

        if eligible:
            state[self._STATE_ELIGIBLE_COUNT] = int(state[self._STATE_ELIGIBLE_COUNT]) + 1
            state[self._STATE_INELIGIBLE_STREAK] = 0
            state[self._STATE_COOLDOWN_UNTIL_TICK] = check_tick + ENCOUNTER_COOLDOWN_TICKS
            encounter_roll = rng.randrange(1, 101)
            sim.schedule_event_at(
                tick=event.tick + 1,
                event_type=ENCOUNTER_ROLL_EVENT_TYPE,
                params={
                    "tick": check_tick,
                    "context": ENCOUNTER_CONTEXT_GLOBAL,
                    "roll": encounter_roll,
                    "trigger": trigger,
                    "location": location.to_dict(),
                },
            )
        else:
            state[self._STATE_INELIGIBLE_STREAK] = int(state[self._STATE_INELIGIBLE_STREAK]) + 1

        sim.set_rules_state(self.name, state)

    def _on_encounter_roll(self, sim: Simulation, event: SimEvent) -> None:
        roll = int(event.params.get("roll", 0))
        category = self._category_for_roll(roll)
        sim.schedule_event_at(
            tick=event.tick + 1,
            event_type=ENCOUNTER_RESULT_STUB_EVENT_TYPE,
            params={
                "tick": int(event.params.get("tick", event.tick)),
                "context": event.params.get("context", ENCOUNTER_CONTEXT_GLOBAL),
                "roll": roll,
                "category": category,
                "trigger": str(event.params.get("trigger", ENCOUNTER_TRIGGER_IDLE)),
                "location": dict(event.params["location"]),
            },
        )

    def _on_travel_step(self, sim: Simulation, event: SimEvent) -> None:
        sim.schedule_event_at(
            tick=event.tick + 1,
            event_type=ENCOUNTER_CHECK_EVENT_TYPE,
            params={
                "tick": int(event.params.get("tick", event.tick)),
                "context": ENCOUNTER_CONTEXT_GLOBAL,
                "trigger": ENCOUNTER_TRIGGER_TRAVEL,
                "location": dict(event.params["location_to"]),
            },
        )

    def _on_encounter_result_stub(self, sim: Simulation, event: SimEvent) -> None:
        sim.schedule_event_at(
            tick=event.tick + 1,
            event_type=ENCOUNTER_RESOLVE_REQUEST_EVENT_TYPE,
            params={
                "tick": int(event.params.get("tick", event.tick)),
                "context": event.params.get("context", ENCOUNTER_CONTEXT_GLOBAL),
                "trigger": event.params["trigger"],
                "location": dict(event.params["location"]),
                "roll": event.params["roll"],
                "category": event.params["category"],
                "offer_required": True,
                "offer_accepted": False,
            },
        )

    @staticmethod
    def _category_for_roll(roll: int) -> str:
        if not 1 <= roll <= 100:
            raise ValueError("encounter_roll must be in the inclusive range [1, 100]")
        if roll <= 40:
            return "hostile"
        if roll <= 75:
            return "neutral"
        return "omen"


    @staticmethod
    def _idle_location(sim: Simulation) -> LocationRef:
        if not sim.state.entities:
            return LocationRef.from_overworld_hex(next(iter(sorted(sim.state.world.hexes))))
        first_entity = sim.state.entities[sorted(sim.state.entities)[0]]
        return LocationRef.from_overworld_hex(first_entity.hex_coord)

    def _location_for_check(self, sim: Simulation, event: SimEvent, trigger: str) -> LocationRef:
        location_payload = event.params.get("location")
        if isinstance(location_payload, dict):
            return LocationRef.from_dict(location_payload)
        if trigger == ENCOUNTER_TRIGGER_TRAVEL:
            location_to = event.params.get("location_to")
            if not isinstance(location_to, dict):
                raise ValueError("travel_step must include location_to")
            return LocationRef.from_dict(location_to)
        return self._idle_location(sim)

    def _build_emit_callback(self):
        def _emit(sim: Simulation, tick: int) -> None:
            sim.schedule_event_at(
                tick=tick + 1,
                event_type=ENCOUNTER_CHECK_EVENT_TYPE,
                params={
                    "tick": tick,
                    "context": ENCOUNTER_CONTEXT_GLOBAL,
                    "trigger": ENCOUNTER_TRIGGER_IDLE,
                    "location": self._idle_location(sim).to_dict(),
                },
            )

        return _emit

    def _rules_state(self, sim: Simulation) -> dict[str, Any]:
        state = sim.get_rules_state(self.name)
        last_check_tick = int(state.get(self._STATE_LAST_CHECK_TICK, -1))
        checks_emitted = int(state.get(self._STATE_CHECKS_EMITTED, 0))
        eligible_count = int(state.get(self._STATE_ELIGIBLE_COUNT, 0))
        ineligible_streak = int(state.get(self._STATE_INELIGIBLE_STREAK, 0))
        cooldown_until_tick = int(state.get(self._STATE_COOLDOWN_UNTIL_TICK, -1))
        if checks_emitted < 0:
            raise ValueError("checks_emitted must be non-negative")
        if eligible_count < 0:
            raise ValueError("eligible_count must be non-negative")
        if ineligible_streak < 0:
            raise ValueError("ineligible_streak must be non-negative")
        return {
            self._STATE_LAST_CHECK_TICK: last_check_tick,
            self._STATE_CHECKS_EMITTED: checks_emitted,
            self._STATE_ELIGIBLE_COUNT: eligible_count,
            self._STATE_INELIGIBLE_STREAK: ineligible_streak,
            self._STATE_COOLDOWN_UNTIL_TICK: cooldown_until_tick,
        }
