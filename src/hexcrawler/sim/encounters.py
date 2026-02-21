from __future__ import annotations

import copy
import hashlib
from typing import Any

from hexcrawler.content.encounters import EncounterTable
from hexcrawler.sim.core import DEFAULT_PLAYER_ENTITY_ID, EntityState, TRAVEL_STEP_EVENT_TYPE, SimEvent, Simulation
from hexcrawler.sim.location import LocationRef, OVERWORLD_HEX_TOPOLOGY, SQUARE_GRID_TOPOLOGY
from hexcrawler.sim.movement import axial_to_world_xy, square_grid_cell_to_world_xy
from hexcrawler.sim.periodic import PeriodicScheduler
from hexcrawler.sim.rules import RuleModule
from hexcrawler.sim.world import CAMPAIGN_SPACE_ROLE, HexCoord, LOCAL_SPACE_ROLE, RumorRecord, SpaceState

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
                "trigger": self._optional_string(event.params.get("trigger")),
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
    """Phase 6B bridge: deterministic local encounter instancing and transition.

    Applies to both space roles:
    - campaign role emits `local_encounter_request` upstream.
    - local role is used for deterministic tactical instance creation/reuse here.
    """

    name = "local_encounter_instance"
    _STATE_PROCESSED_REQUEST_IDS = "processed_request_ids"

    def on_simulation_start(self, sim: Simulation) -> None:
        sim.set_rules_state(self.name, self._rules_state(sim))

    def on_event_executed(self, sim: Simulation, event: SimEvent) -> None:
        if event.event_type != LOCAL_ENCOUNTER_REQUEST_EVENT_TYPE:
            return

        state = self._rules_state(sim)
        processed_ids = list(state[self._STATE_PROCESSED_REQUEST_IDS])
        request_id = str(event.event_id)
        if request_id in processed_ids:
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

        entity_id = self._select_entity_id(sim=sim, from_space_id=from_space_id)
        transition_applied = False
        from_location_payload = event.params.get("from_location")
        if entity_id is not None:
            entity = sim.state.entities[entity_id]
            from_location_payload = sim._entity_location_ref(entity).to_dict()
            to_spawn_coord = local_space.default_spawn_coord()
            next_x, next_y = sim._coord_to_world_xy(space=local_space, coord=to_spawn_coord)
            entity.space_id = local_space.space_id
            entity.position_x = next_x
            entity.position_y = next_y
            transition_applied = True
        else:
            to_spawn_coord = local_space.default_spawn_coord()

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
            },
        )

        processed_ids.append(request_id)
        state[self._STATE_PROCESSED_REQUEST_IDS] = processed_ids[-LOCAL_ENCOUNTER_INSTANCE_LEDGER_MAX:]
        sim.set_rules_state(self.name, state)

    def _rules_state(self, sim: Simulation) -> dict[str, Any]:
        state = sim.get_rules_state(self.name)
        raw_processed = state.get(self._STATE_PROCESSED_REQUEST_IDS, [])
        if not isinstance(raw_processed, list):
            raise ValueError("local_encounter_instance.processed_request_ids must be a list")
        normalized = [str(value) for value in raw_processed if str(value)]
        state[self._STATE_PROCESSED_REQUEST_IDS] = normalized[-LOCAL_ENCOUNTER_INSTANCE_LEDGER_MAX:]
        return state

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
    _SUPPORTED_ACTION_TYPES = {"signal_intent", "track_intent", "spawn_intent"}

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
