from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

from hexcrawler.content.encounters import EncounterTable
from hexcrawler.content.local_arenas import DEFAULT_LOCAL_ARENAS_PATH, LocalArenaTemplate, load_local_arena_templates_json
from hexcrawler.sim.core import DEFAULT_PLAYER_ENTITY_ID, EntityState, TRAVEL_STEP_EVENT_TYPE, SimCommand, SimEvent, Simulation
from hexcrawler.sim.location import LocationRef, OVERWORLD_HEX_TOPOLOGY, SQUARE_GRID_TOPOLOGY
from hexcrawler.sim.movement import axial_to_world_xy, square_grid_cell_to_world_xy
from hexcrawler.sim.periodic import PeriodicScheduler
from hexcrawler.sim.rules import RuleModule
from hexcrawler.sim.world import CAMPAIGN_SPACE_ROLE, LOCAL_SPACE_ROLE, AnchorRecord, DoorRecord, HexCoord, InteractableRecord, RumorRecord, SpaceState

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
LOCAL_ARENA_TEMPLATE_APPLIED_EVENT_TYPE = "local_arena_template_applied"
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

        from_location_payload = event.params.get("location")
        if not isinstance(from_location_payload, dict):
            return
        from_location = LocationRef.from_dict(from_location_payload)
        from_space = sim.state.world.spaces.get(from_location.space_id)
        if from_space is None or from_space.role != CAMPAIGN_SPACE_ROLE:
            return

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
                "suggested_local_template_id": self._optional_string(event.params.get("suggested_local_template_id")),
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
                elif state[self._STATE_RETURN_IN_PROGRESS_BY_LOCAL_SPACE].get(local_space_id, False):
                    reason = "already_returning"
                else:
                    origin_location = copy.deepcopy(active_context.get("origin_location", active_context.get("from_location")))
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
                            "from_location": copy.deepcopy(active_context["from_location"]),
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

        active_by_local_space = dict(state[self._STATE_ACTIVE_BY_LOCAL_SPACE])
        if len(active_by_local_space) >= MAX_ACTIVE_LOCAL_ENCOUNTERS:
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
                },
            )
            processed_ids.append(request_id)
            state[self._STATE_PROCESSED_REQUEST_IDS] = processed_ids[-LOCAL_ENCOUNTER_INSTANCE_LEDGER_MAX:]
            sim.set_rules_state(self.name, state)
            return

        from_space_id = str(event.params.get("from_space_id", ""))
        local_space_id = f"local_encounter:{request_id}"
        local_space = sim.state.world.spaces.get(local_space_id)
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

        entity_id = self._select_entity_id(sim=sim, from_space_id=from_space_id)
        transition_applied = False
        from_location_payload = event.params.get("from_location")
        if entity_id is not None:
            entity = sim.state.entities[entity_id]
            from_location_payload = sim._entity_location_ref(entity).to_dict()
            to_spawn_coord = self._spawn_coord(local_space)
            next_x, next_y = sim._coord_to_world_xy(space=local_space, coord=to_spawn_coord)
            entity.space_id = local_space.space_id
            entity.position_x = next_x
            entity.position_y = next_y
            transition_applied = True
        else:
            to_spawn_coord = self._spawn_coord(local_space)

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

        sim.schedule_event_at(
            tick=event.tick,
            event_type=LOCAL_ENCOUNTER_BEGIN_EVENT_TYPE,
            params={
                "request_event_id": request_id,
                "from_space_id": from_space_id,
                "to_space_id": local_space_id,
                "entity_id": entity_id,
                "from_location": copy.deepcopy(from_location_payload),
                "to_spawn_coord": dict(to_spawn_coord),
                "transition_applied": transition_applied,
                "template_id": template_id,
                "template_selection_reason": selection_reason,
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
                "return_spawn_coord": copy.deepcopy(from_location_payload.get("coord", {})),
                "started_tick": int(event.tick),
            }

        ordered_space_ids = sorted(active_by_local_space.keys())
        state[self._STATE_ACTIVE_BY_LOCAL_SPACE] = {
            space_id: active_by_local_space[space_id] for space_id in ordered_space_ids[-MAX_ACTIVE_LOCAL_ENCOUNTERS:]
        }
        state[self._STATE_APPLIED_TEMPLATE_BY_LOCAL_SPACE] = {
            space_id: applied_template_map[space_id] for space_id in sorted(applied_template_map)
        }
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
    def _spawn_coord(local_space: SpaceState) -> dict[str, int]:
        entry = local_space.anchors.get("entry")
        if entry is not None and local_space.is_valid_cell(entry.coord):
            return copy.deepcopy(entry.coord)
        return local_space.default_spawn_coord()

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
        context = active_by_local_space.get(local_space_id)
        entity_id = str(event.params.get("entity_id", "")) if isinstance(event.params.get("entity_id"), str) else None
        applied = False
        reason = "resolved"
        to_space_id = None
        to_coord = None

        if context is None:
            reason = "no_active_local_encounter"
        elif entity_id is None or entity_id not in sim.state.entities:
            reason = "invalid_entity"
        else:
            fallback_space_id = str(context.get("origin_space_id", context["from_space_id"]))
            normalized_origin = self._normalize_origin_location_payload(
                origin_space_id=fallback_space_id,
                origin_location_payload=context.get("origin_location", context.get("from_location")),
                legacy_coord=context.get("return_spawn_coord"),
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
                    entity.space_id = to_space_id
                    entity.position_x = next_x
                    entity.position_y = next_y
                    applied = True

        if context is not None:
            del active_by_local_space[local_space_id]
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
        sim.set_rules_state(self.name, state)

        sim.schedule_event_at(
            tick=event.tick,
            event_type=LOCAL_ENCOUNTER_RETURN_EVENT_TYPE,
            params={
                "tick": int(event.tick),
                "action_uid": action_uid,
                "entity_id": entity_id,
                "request_event_id": str(event.params.get("request_event_id", "")),
                "from_space_id": local_space_id,
                "to_space_id": to_space_id,
                "from_location": copy.deepcopy(event.params.get("from_location")),
                "to_coord": to_coord,
                "applied": applied,
                "reason": reason,
                "tags": [str(tag) for tag in event.params.get("tags", [])] if isinstance(event.params.get("tags"), list) else [],
            },
        )

    def _rules_state(self, sim: Simulation) -> dict[str, Any]:
        state = sim.get_rules_state(self.name)
        raw_processed = state.get(self._STATE_PROCESSED_REQUEST_IDS, [])
        raw_processed_end = state.get(self._STATE_PROCESSED_END_ACTION_UIDS, [])
        raw_active_by_local_space = state.get(self._STATE_ACTIVE_BY_LOCAL_SPACE, {})
        raw_applied_template_by_local_space = state.get(self._STATE_APPLIED_TEMPLATE_BY_LOCAL_SPACE, {})
        raw_return_in_progress_by_local_space = state.get(self._STATE_RETURN_IN_PROGRESS_BY_LOCAL_SPACE, {})
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
                "return_spawn_coord": copy.deepcopy(return_spawn_coord),
                "started_tick": int(context.get("started_tick", 0)),
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
        return state

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
                    sim.schedule_event_at(
                        tick=event.tick + 1,
                        event_type=LOCAL_ENCOUNTER_REQUEST_EVENT_TYPE,
                        params={
                            "action_uid": action_uid,
                            "from_space_id": from_space_id,
                            "from_location": from_location,
                            "suggested_local_template_id": suggested_local_template_id,
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




class RumorPipelineModule(RuleModule):
    """Phase 5E deterministic rumor pipeline from executed encounter outcomes."""

    name = "rumor_pipeline"

    def on_simulation_start(self, sim: Simulation) -> None:
        scheduler = sim.get_rule_module(PeriodicScheduler.name)
        if scheduler is None:
            scheduler = PeriodicScheduler()
            sim.register_rule_module(scheduler)
        if not isinstance(scheduler, PeriodicScheduler):
            raise TypeError("periodic_scheduler module must be a PeriodicScheduler")

        sim.set_rules_state(self.name, self._rules_state(sim))
        scheduler.register_task(
            task_name=RUMOR_PROPAGATION_TASK_NAME,
            interval_ticks=RUMOR_PROPAGATION_INTERVAL_TICKS,
            start_tick=0,
        )
        scheduler.set_task_callback(RUMOR_PROPAGATION_TASK_NAME, self._build_tick_callback())

    def on_event_executed(self, sim: Simulation, event: SimEvent) -> None:
        if event.event_type != ENCOUNTER_ACTION_OUTCOME_EVENT_TYPE:
            return
        params = event.params
        if str(params.get("outcome", "")) != "executed":
            return
        action_uid = str(params.get("action_uid", ""))
        if not action_uid:
            raise ValueError("encounter_action_outcome.action_uid must be a non-empty string")

        state = self._rules_state(sim)
        emitted = set(state["emitted_ledger_keys"])
        ledger_key = f"base:{action_uid}"
        if ledger_key in emitted:
            return

        location = self._location_dict(params.get("location"))
        created_tick = int(event.tick)
        record = RumorRecord(
            rumor_id=self._rumor_id_for_identity(ledger_key),
            created_tick=created_tick,
            location=location,
            template_id=f"rumor.{str(params.get('action_type', 'unknown'))}",
            source_action_uid=action_uid,
            confidence=0.75,
            hop=0,
            expires_tick=created_tick + RUMOR_TTL_TICKS,
            payload={
                "source_outcome_event_id": event.event_id,
                "mutation": str(params.get("mutation", "none")),
            },
        )
        sim.state.world.append_rumor(record)
        emitted.add(ledger_key)
        state["emitted_ledger_keys"] = sorted(emitted)
        sim.set_rules_state(self.name, state)

    def _build_tick_callback(self):
        def _on_periodic(sim: Simulation, tick: int) -> None:
            self._process_periodic_tick(sim, tick)

        return _on_periodic

    def _process_periodic_tick(self, sim: Simulation, tick: int) -> None:
        state = self._rules_state(sim)
        emitted = set(state["emitted_ledger_keys"])

        for index, rumor in enumerate(sim.state.world.rumors):
            payload = rumor.get("payload")
            payload = payload if isinstance(payload, dict) else None
            expires_tick = int(rumor.get("expires_tick", -1))
            if tick > expires_tick and payload is not None and payload.get("expired") is not True:
                next_payload = dict(payload)
                next_payload["expired"] = True
                next_payload["expired_tick"] = tick
                sim.state.world.rumors[index]["payload"] = next_payload

        for rumor in list(sim.state.world.rumors):
            if int(rumor.get("hop", 0)) >= RUMOR_HOP_CAP:
                continue
            if tick > int(rumor.get("expires_tick", -1)):
                continue
            next_location = self._propagated_location(sim, rumor)
            if next_location is None:
                continue

            next_hop = int(rumor.get("hop", 0)) + 1
            source_action_uid = str(rumor.get("source_action_uid", ""))
            ledger_key = (
                f"prop:{str(rumor.get('rumor_id', '?'))}:"
                f"{next_hop}:{next_location['coord']['q']}:{next_location['coord']['r']}"
            )
            if ledger_key in emitted:
                continue

            parent_confidence = float(rumor.get("confidence", 0.0))
            confidence = max(0.1, round(parent_confidence * 0.8, 4))
            child = RumorRecord(
                rumor_id=self._rumor_id_for_identity(ledger_key),
                created_tick=tick,
                location=next_location,
                template_id=str(rumor.get("template_id", "rumor.unknown")),
                source_action_uid=source_action_uid,
                confidence=confidence,
                hop=next_hop,
                expires_tick=tick + RUMOR_TTL_TICKS,
                payload={"derived_from": str(rumor.get("rumor_id", ""))},
            )
            sim.state.world.append_rumor(child)
            emitted.add(ledger_key)

        state["emitted_ledger_keys"] = sorted(emitted)
        sim.set_rules_state(self.name, state)

    def _propagated_location(self, sim: Simulation, rumor: dict[str, Any]) -> dict[str, Any] | None:
        location = LocationRef.from_dict(self._location_dict(rumor.get("location")))
        if location.topology_type != "overworld_hex":
            return None
        source = HexCoord(q=int(location.coord["q"]), r=int(location.coord["r"]))
        neighbors = [
            HexCoord(source.q + 1, source.r),
            HexCoord(source.q + 1, source.r - 1),
            HexCoord(source.q, source.r - 1),
            HexCoord(source.q - 1, source.r),
            HexCoord(source.q - 1, source.r + 1),
            HexCoord(source.q, source.r + 1),
        ]
        preferred = self._stable_index(f"{rumor.get('rumor_id','')}:{rumor.get('hop', 0)}", len(neighbors))
        for offset in range(len(neighbors)):
            candidate = neighbors[(preferred + offset) % len(neighbors)]
            if sim.state.world.get_hex_record(candidate) is None:
                continue
            return LocationRef.from_overworld_hex(candidate).to_dict()
        return None

    def _location_dict(self, payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("rumor pipeline expected dict location")
        return LocationRef.from_dict(payload).to_dict()

    def _rules_state(self, sim: Simulation) -> dict[str, Any]:
        state = sim.get_rules_state(self.name)
        raw_ledger = state.get("emitted_ledger_keys", [])
        if not isinstance(raw_ledger, list):
            raise ValueError("rumor_pipeline.rules_state.emitted_ledger_keys must be a list")
        normalized: list[str] = []
        for item in raw_ledger:
            if not isinstance(item, str) or not item:
                raise ValueError("rumor_pipeline.rules_state.emitted_ledger_keys entries must be non-empty strings")
            normalized.append(item)
        return {"emitted_ledger_keys": sorted(set(normalized))}

    def _rumor_id_for_identity(self, identity: str) -> str:
        digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
        return f"rumor-{digest[:20]}"

    def _stable_index(self, value: str, width: int) -> int:
        digest = hashlib.sha256(value.encode("utf-8")).digest()
        return int.from_bytes(digest[:4], byteorder="big") % width


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
