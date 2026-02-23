import hashlib
import json

from hexcrawler.content.io import load_world_json
from hexcrawler.sim.core import DEFAULT_PLAYER_ENTITY_ID, EntityState, SimCommand, Simulation
from hexcrawler.sim.encounters import (
    ENCOUNTER_ACTION_EXECUTE_EVENT_TYPE,
    END_LOCAL_ENCOUNTER_INTENT,
    FORTIFICATION_PENDING_EFFECT_TYPE,
    LOCAL_ENCOUNTER_BEGIN_EVENT_TYPE,
    REHAB_POLICY_ADD,
    REHAB_POLICY_REPLACE,
    REINHABITATION_PENDING_EFFECT_TYPE,
    SITE_CHECK_INTERVAL_TICKS,
    SITE_EFFECT_CONSUMED_EVENT_TYPE,
    SITE_EFFECT_CONSUMPTION_REJECTED_EVENT_TYPE,
    SITE_EFFECT_SCHEDULED_EVENT_TYPE,
    STALE_TICKS,
    EncounterActionExecutionModule,
    LocalEncounterInstanceModule,
)
from hexcrawler.sim.hash import simulation_hash
from hexcrawler.sim.movement import axial_to_world_xy
from hexcrawler.sim.world import HexCoord


def _build_sim(seed: int = 606) -> Simulation:
    sim = Simulation(world=load_world_json("content/examples/basic_map.json"), seed=seed)
    sim.register_rule_module(EncounterActionExecutionModule())
    sim.register_rule_module(LocalEncounterInstanceModule())
    x, y = axial_to_world_xy(HexCoord(q=0, r=0))
    sim.add_entity(EntityState(entity_id=DEFAULT_PLAYER_ENTITY_ID, position_x=x, position_y=y, space_id="overworld"))
    return sim


def _schedule_local_encounter(sim: Simulation, source_event_id: str) -> None:
    sim.schedule_event_at(
        tick=sim.state.tick,
        event_type=ENCOUNTER_ACTION_EXECUTE_EVENT_TYPE,
        params={
            "source_event_id": source_event_id,
            "tick": sim.state.tick,
            "context": "global",
            "trigger": "travel",
            "location": {"space_id": "overworld", "topology_type": "overworld_hex", "coord": {"q": 0, "r": 0}},
            "roll": 22,
            "category": "hostile",
            "table_id": "basic_encounters",
            "entry_id": "scavenger_patrol",
            "entry_tags": ["patrol"],
            "actions": [
                {
                    "action_type": "local_encounter_intent",
                    "template_id": "default_arena_v1",
                    "params": {"suggested_local_template_id": "default_arena_v1"},
                }
            ],
        },
    )


def _trace(sim: Simulation, event_type: str) -> list[dict]:
    return [entry for entry in sim.get_event_trace() if entry["event_type"] == event_type]


def _end_local(sim: Simulation) -> None:
    sim.append_command(
        SimCommand(
            tick=sim.state.tick,
            entity_id=DEFAULT_PLAYER_ENTITY_ID,
            command_type=END_LOCAL_ENCOUNTER_INTENT,
            params={"intent": END_LOCAL_ENCOUNTER_INTENT, "entity_id": DEFAULT_PLAYER_ENTITY_ID, "tags": []},
        )
    )


def _setup_with_pending_effect(seed: int = 500) -> tuple[Simulation, str, str, list[str]]:
    sim = _build_sim(seed=seed)
    _schedule_local_encounter(sim, "phase6d-m6-enter")
    sim.advance_ticks(5)
    begin = _trace(sim, LOCAL_ENCOUNTER_BEGIN_EVENT_TYPE)[0]["params"]
    local_space_id = begin["to_space_id"]
    old_ids = sorted(
        entity_id
        for entity_id, entity in sim.state.entities.items()
        if entity.space_id == local_space_id and entity.template_id == "encounter_hostile_v1"
    )

    _end_local(sim)
    sim.advance_ticks(4)
    sim.advance_ticks(STALE_TICKS + SITE_CHECK_INTERVAL_TICKS)

    state = sim.get_rules_state(LocalEncounterInstanceModule.name)
    site_key = state["active_by_local_space"][local_space_id]["site_key"]
    site_key_json = LocalEncounterInstanceModule._site_key_json(site_key)  # noqa: SLF001
    return sim, local_space_id, site_key_json, old_ids


def test_m7_default_policy_remains_replace_and_consumes_once() -> None:
    sim, local_space_id, site_key_json, old_ids = _setup_with_pending_effect(seed=501)

    _schedule_local_encounter(sim, "phase6d-m7-reenter")
    sim.advance_ticks(5)

    state = sim.get_rules_state(LocalEncounterInstanceModule.name)
    site_state = state["site_state_by_key"][site_key_json]
    assert site_state["rehab_policy"] == REHAB_POLICY_REPLACE
    assert site_state["rehab_generation"] == 1
    assert [e for e in site_state["pending_effects"] if e["effect_type"] == REINHABITATION_PENDING_EFFECT_TYPE] == []

    new_ids = sorted(
        entity_id
        for entity_id, entity in sim.state.entities.items()
        if entity.space_id == local_space_id and entity.template_id == "encounter_hostile_v1"
    )
    assert len(new_ids) == 1
    assert new_ids[0] not in old_ids

    consumed = _trace(sim, SITE_EFFECT_CONSUMED_EVENT_TYPE)
    assert len(consumed) == 1
    assert consumed[0]["params"]["generation_after"] == 1
    assert consumed[0]["params"]["rehab_policy"] == REHAB_POLICY_REPLACE

    _end_local(sim)
    sim.advance_ticks(4)
    _schedule_local_encounter(sim, "phase6d-m7-reenter-no-effect")
    sim.advance_ticks(5)
    newest_begin = _trace(sim, LOCAL_ENCOUNTER_BEGIN_EVENT_TYPE)[-1]["params"]
    assert newest_begin["reuse"] is True
    assert newest_begin["spawned_entities"][0]["entity_id"] == new_ids[0]


def test_m7_add_policy_adds_hostiles_without_replacing_existing() -> None:
    sim, local_space_id, site_key_json, old_ids = _setup_with_pending_effect(seed=502)

    state = sim.get_rules_state(LocalEncounterInstanceModule.name)
    state["site_state_by_key"][site_key_json]["rehab_policy"] = REHAB_POLICY_ADD
    sim.set_rules_state(LocalEncounterInstanceModule.name, state)

    _schedule_local_encounter(sim, "phase6d-m7-reenter-add")
    sim.advance_ticks(5)

    begin = _trace(sim, LOCAL_ENCOUNTER_BEGIN_EVENT_TYPE)[-1]["params"]
    assert begin["reuse"] is True
    assert begin["transition_applied"] is True

    participant_ids = sorted(
        entity_id
        for entity_id, entity in sim.state.entities.items()
        if entity.space_id == local_space_id and entity.template_id == "encounter_hostile_v1"
    )
    assert all(old_id in participant_ids for old_id in old_ids)
    assert len(participant_ids) == len(old_ids) + 1
    added_ids = [entity_id for entity_id in participant_ids if entity_id not in old_ids]
    assert len(added_ids) == 1
    assert ":gen1:0" in added_ids[0]

    consumed = _trace(sim, SITE_EFFECT_CONSUMED_EVENT_TYPE)
    assert consumed[-1]["params"]["rehab_policy"] == REHAB_POLICY_ADD

    _end_local(sim)
    sim.advance_ticks(4)
    _schedule_local_encounter(sim, "phase6d-m7-reenter-add-no-effect")
    sim.advance_ticks(5)

    participant_ids_after = sorted(
        entity_id
        for entity_id, entity in sim.state.entities.items()
        if entity.space_id == local_space_id and entity.template_id == "encounter_hostile_v1"
    )
    assert participant_ids_after == participant_ids


def test_m7_invalid_policy_rejects_atomically_with_forensics() -> None:
    sim, local_space_id, site_key_json, old_ids = _setup_with_pending_effect(seed=505)

    state = sim.get_rules_state(LocalEncounterInstanceModule.name)
    state["site_state_by_key"][site_key_json]["rehab_policy"] = "bogus"
    sim.set_rules_state(LocalEncounterInstanceModule.name, state)

    player_before = sim.state.entities[DEFAULT_PLAYER_ENTITY_ID]
    before_space_id = player_before.space_id
    before_position = (player_before.position_x, player_before.position_y)

    _schedule_local_encounter(sim, "phase6d-m7-reenter-invalid")
    sim.advance_ticks(5)

    begin = _trace(sim, LOCAL_ENCOUNTER_BEGIN_EVENT_TYPE)[-1]["params"]
    assert begin["reuse"] is True
    assert begin["transition_applied"] is False
    assert begin["reason"] == "invalid_rehab_policy"

    player_after = sim.state.entities[DEFAULT_PLAYER_ENTITY_ID]
    assert player_after.space_id == before_space_id
    assert (player_after.position_x, player_after.position_y) == before_position

    participant_ids_after = sorted(
        entity_id
        for entity_id, entity in sim.state.entities.items()
        if entity.space_id == local_space_id and entity.template_id == "encounter_hostile_v1"
    )
    assert participant_ids_after == old_ids

    site_state = sim.get_rules_state(LocalEncounterInstanceModule.name)["site_state_by_key"][site_key_json]
    assert site_state["rehab_generation"] == 0
    assert any(effect["effect_type"] == REINHABITATION_PENDING_EFFECT_TYPE for effect in site_state["pending_effects"])

    rejected = _trace(sim, SITE_EFFECT_CONSUMPTION_REJECTED_EVENT_TYPE)
    assert rejected[-1]["params"]["reason"] == "invalid_rehab_policy"
    assert rejected[-1]["params"]["invalid_rehab_policy_value"] == "bogus"
    consumed = _trace(sim, SITE_EFFECT_CONSUMED_EVENT_TYPE)
    assert consumed == []


def test_m7_invalid_non_string_policy_rejects_with_specific_reason() -> None:
    sim, local_space_id, site_key_json, old_ids = _setup_with_pending_effect(seed=508)

    state = sim.get_rules_state(LocalEncounterInstanceModule.name)
    state["site_state_by_key"][site_key_json]["rehab_policy"] = {"x": 1}
    sim.set_rules_state(LocalEncounterInstanceModule.name, state)

    player_before = sim.state.entities[DEFAULT_PLAYER_ENTITY_ID]
    before_space_id = player_before.space_id
    before_position = (player_before.position_x, player_before.position_y)

    _schedule_local_encounter(sim, "phase6d-m7-reenter-invalid-non-string")
    sim.advance_ticks(5)

    begin = _trace(sim, LOCAL_ENCOUNTER_BEGIN_EVENT_TYPE)[-1]["params"]
    assert begin["reuse"] is True
    assert begin["transition_applied"] is False
    assert begin["reason"] == "invalid_rehab_policy"

    player_after = sim.state.entities[DEFAULT_PLAYER_ENTITY_ID]
    assert player_after.space_id == before_space_id
    assert (player_after.position_x, player_after.position_y) == before_position

    participant_ids_after = sorted(
        entity_id
        for entity_id, entity in sim.state.entities.items()
        if entity.space_id == local_space_id and entity.template_id == "encounter_hostile_v1"
    )
    assert participant_ids_after == old_ids

    site_state = sim.get_rules_state(LocalEncounterInstanceModule.name)["site_state_by_key"][site_key_json]
    assert site_state["rehab_generation"] == 0
    assert any(effect["effect_type"] == REINHABITATION_PENDING_EFFECT_TYPE for effect in site_state["pending_effects"])

    rejected = _trace(sim, SITE_EFFECT_CONSUMPTION_REJECTED_EVENT_TYPE)
    assert rejected[-1]["params"]["reason"] == "invalid_rehab_policy"
    assert rejected[-1]["params"]["invalid_rehab_policy_value"] == 'dict:{"x":1}'
    consumed = _trace(sim, SITE_EFFECT_CONSUMED_EVENT_TYPE)
    assert consumed == []


def test_m7_add_policy_failure_is_atomic() -> None:
    sim, local_space_id, site_key_json, old_ids = _setup_with_pending_effect(seed=506)

    state = sim.get_rules_state(LocalEncounterInstanceModule.name)
    site_state = state["site_state_by_key"][site_key_json]
    site_state["rehab_policy"] = REHAB_POLICY_ADD
    site_key = site_state["site_key"]
    site_hash = hashlib.sha256(json.dumps(site_key, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()[:12]
    conflict_entity_id = f"spawn:{site_hash}:gen1:0"
    if conflict_entity_id not in sim.state.entities:
        sim.add_entity(
            EntityState(
                entity_id=conflict_entity_id,
                position_x=0.0,
                position_y=0.0,
                space_id="overworld",
                template_id="encounter_hostile_v1",
            )
        )
    sim.set_rules_state(LocalEncounterInstanceModule.name, state)

    player_before = sim.state.entities[DEFAULT_PLAYER_ENTITY_ID]
    before_space_id = player_before.space_id
    before_position = (player_before.position_x, player_before.position_y)

    _schedule_local_encounter(sim, "phase6d-m7-reenter-add-fail")
    sim.advance_ticks(5)

    begin = _trace(sim, LOCAL_ENCOUNTER_BEGIN_EVENT_TYPE)[-1]["params"]
    assert begin["reuse"] is True
    assert begin["transition_applied"] is False
    assert begin["reason"] == "reinhabitation_add_failed"

    player_after = sim.state.entities[DEFAULT_PLAYER_ENTITY_ID]
    assert player_after.space_id == before_space_id
    assert (player_after.position_x, player_after.position_y) == before_position

    participant_ids_after = sorted(
        entity_id
        for entity_id, entity in sim.state.entities.items()
        if entity.space_id == local_space_id and entity.template_id == "encounter_hostile_v1"
    )
    assert participant_ids_after == old_ids

    site_state_after = sim.get_rules_state(LocalEncounterInstanceModule.name)["site_state_by_key"][site_key_json]
    assert site_state_after["rehab_generation"] == 0
    assert any(effect["effect_type"] == REINHABITATION_PENDING_EFFECT_TYPE for effect in site_state_after["pending_effects"])

    rejected = _trace(sim, SITE_EFFECT_CONSUMPTION_REJECTED_EVENT_TYPE)
    assert rejected[-1]["params"]["reason"] == "participant_add_failed"


def test_m7_save_load_hash_stability_for_add_policy() -> None:
    sim, _, site_key_json, _ = _setup_with_pending_effect(seed=507)

    state = sim.get_rules_state(LocalEncounterInstanceModule.name)
    state["site_state_by_key"][site_key_json]["rehab_policy"] = REHAB_POLICY_ADD
    sim.set_rules_state(LocalEncounterInstanceModule.name, state)

    payload = sim.simulation_payload()
    loaded = Simulation.from_simulation_payload(payload)
    loaded.register_rule_module(EncounterActionExecutionModule())
    loaded.register_rule_module(LocalEncounterInstanceModule())

    _schedule_local_encounter(sim, "phase6d-m7-reenter-add-a")
    sim.advance_ticks(5)
    _schedule_local_encounter(loaded, "phase6d-m7-reenter-add-a")
    loaded.advance_ticks(5)

    assert simulation_hash(loaded) == simulation_hash(sim)


def test_m6_consumption_uses_first_retained_reinhabitation_marker() -> None:
    sim, local_space_id, site_key_json, _ = _setup_with_pending_effect(seed=503)

    state = sim.get_rules_state(LocalEncounterInstanceModule.name)
    state["site_state_by_key"][site_key_json]["pending_effects"] = [
        {"effect_type": "drop_0", "created_tick": 0, "source": "test"},
        {"effect_type": "drop_1", "created_tick": 1, "source": "test"},
        {"effect_type": REINHABITATION_PENDING_EFFECT_TYPE, "created_tick": 2, "source": "test", "marker": "A"},
        {"effect_type": "other_effect", "created_tick": 3, "source": "test"},
        {"effect_type": REINHABITATION_PENDING_EFFECT_TYPE, "created_tick": 4, "source": "test", "marker": "B"},
    ]
    sim.set_rules_state(LocalEncounterInstanceModule.name, state)

    _schedule_local_encounter(sim, "phase6d-m6-reenter")
    sim.advance_ticks(5)

    pending_after = sim.get_rules_state(LocalEncounterInstanceModule.name)["site_state_by_key"][site_key_json]["pending_effects"]
    retained_reinhab = [effect for effect in pending_after if effect["effect_type"] == REINHABITATION_PENDING_EFFECT_TYPE]
    assert len(retained_reinhab) == 1
    assert retained_reinhab[0]["marker"] == "B"

    participant_ids = sorted(
        entity_id
        for entity_id, entity in sim.state.entities.items()
        if entity.space_id == local_space_id and entity.template_id == "encounter_hostile_v1"
    )
    assert len(participant_ids) == 1


def test_m6_save_load_midflow_consumes_once_after_reload() -> None:
    sim, _, site_key_json, _ = _setup_with_pending_effect(seed=504)

    payload = sim.simulation_payload()
    loaded = Simulation.from_simulation_payload(payload)
    loaded.register_rule_module(EncounterActionExecutionModule())
    loaded.register_rule_module(LocalEncounterInstanceModule())

    _schedule_local_encounter(loaded, "phase6d-m6-reenter-after-load")
    loaded.advance_ticks(5)

    consumed = _trace(loaded, SITE_EFFECT_CONSUMED_EVENT_TYPE)
    assert len(consumed) == 1
    assert loaded.get_rules_state(LocalEncounterInstanceModule.name)["site_state_by_key"][site_key_json]["rehab_generation"] == 1


def test_m6_schedules_reinhabitation_effect_once() -> None:
    sim, _, _, _ = _setup_with_pending_effect(seed=508)
    scheduled = _trace(sim, SITE_EFFECT_SCHEDULED_EVENT_TYPE)
    assert len(scheduled) == 1


def test_m8_multi_effect_order_consumes_reinhabitation_then_fortification() -> None:
    sim, local_space_id, site_key_json, old_ids = _setup_with_pending_effect(seed=509)

    state = sim.get_rules_state(LocalEncounterInstanceModule.name)
    site_state = state["site_state_by_key"][site_key_json]
    site_state["pending_effects"] = [
        {"effect_type": REINHABITATION_PENDING_EFFECT_TYPE, "created_tick": 1, "source": "test"},
        {"effect_type": FORTIFICATION_PENDING_EFFECT_TYPE, "created_tick": 2, "source": "test"},
    ]
    site_state["fortified"] = False
    sim.set_rules_state(LocalEncounterInstanceModule.name, state)

    _schedule_local_encounter(sim, "phase6d-m8-reenter-1")
    sim.advance_ticks(5)

    site_state_after_first = sim.get_rules_state(LocalEncounterInstanceModule.name)["site_state_by_key"][site_key_json]
    assert site_state_after_first["fortified"] is False
    assert [effect["effect_type"] for effect in site_state_after_first["pending_effects"]] == [FORTIFICATION_PENDING_EFFECT_TYPE]

    first_participants = sorted(
        entity_id
        for entity_id, entity in sim.state.entities.items()
        if entity.space_id == local_space_id and entity.template_id == "encounter_hostile_v1"
    )
    assert len(first_participants) == 1
    assert first_participants[0] not in old_ids

    consumed_after_first = _trace(sim, SITE_EFFECT_CONSUMED_EVENT_TYPE)
    assert consumed_after_first[-1]["params"]["effect_type"] == REINHABITATION_PENDING_EFFECT_TYPE

    _end_local(sim)
    sim.advance_ticks(4)
    _schedule_local_encounter(sim, "phase6d-m8-reenter-2")
    sim.advance_ticks(5)

    site_state_after_second = sim.get_rules_state(LocalEncounterInstanceModule.name)["site_state_by_key"][site_key_json]
    assert site_state_after_second["fortified"] is True
    assert site_state_after_second["pending_effects"] == []

    second_participants = sorted(
        entity_id
        for entity_id, entity in sim.state.entities.items()
        if entity.space_id == local_space_id and entity.template_id == "encounter_hostile_v1"
    )
    assert second_participants == first_participants

    consumed_after_second = _trace(sim, SITE_EFFECT_CONSUMED_EVENT_TYPE)
    assert consumed_after_second[-1]["params"]["effect_type"] == FORTIFICATION_PENDING_EFFECT_TYPE
    assert consumed_after_second[-1]["params"]["fortified"] is True


def test_m8_ordering_reversal_consumes_fortification_before_reinhabitation() -> None:
    sim, local_space_id, site_key_json, old_ids = _setup_with_pending_effect(seed=510)

    state = sim.get_rules_state(LocalEncounterInstanceModule.name)
    site_state = state["site_state_by_key"][site_key_json]
    site_state["pending_effects"] = [
        {"effect_type": FORTIFICATION_PENDING_EFFECT_TYPE, "created_tick": 1, "source": "test"},
        {"effect_type": REINHABITATION_PENDING_EFFECT_TYPE, "created_tick": 2, "source": "test"},
    ]
    site_state["fortified"] = False
    sim.set_rules_state(LocalEncounterInstanceModule.name, state)

    _schedule_local_encounter(sim, "phase6d-m8-reversed-1")
    sim.advance_ticks(5)

    first_site_state = sim.get_rules_state(LocalEncounterInstanceModule.name)["site_state_by_key"][site_key_json]
    assert first_site_state["fortified"] is True
    assert [effect["effect_type"] for effect in first_site_state["pending_effects"]] == [REINHABITATION_PENDING_EFFECT_TYPE]
    participants_after_first = sorted(
        entity_id
        for entity_id, entity in sim.state.entities.items()
        if entity.space_id == local_space_id and entity.template_id == "encounter_hostile_v1"
    )
    assert participants_after_first == old_ids

    _end_local(sim)
    sim.advance_ticks(4)
    _schedule_local_encounter(sim, "phase6d-m8-reversed-2")
    sim.advance_ticks(5)

    participants_after_second = sorted(
        entity_id
        for entity_id, entity in sim.state.entities.items()
        if entity.space_id == local_space_id and entity.template_id == "encounter_hostile_v1"
    )
    assert len(participants_after_second) == 1
    assert participants_after_second[0] not in old_ids
    assert participants_after_second != participants_after_first


def test_m8_save_load_midsequence_matches_no_save_path() -> None:
    sim_a, _, _, _ = _setup_with_pending_effect(seed=511)
    sim_b = Simulation.from_simulation_payload(sim_a.simulation_payload())
    sim_b.register_rule_module(EncounterActionExecutionModule())
    sim_b.register_rule_module(LocalEncounterInstanceModule())

    for sim in (sim_a, sim_b):
        state = sim.get_rules_state(LocalEncounterInstanceModule.name)
        site_key_json = next(iter(state["site_state_by_key"]))
        site_state = state["site_state_by_key"][site_key_json]
        site_state["pending_effects"] = [
            {"effect_type": REINHABITATION_PENDING_EFFECT_TYPE, "created_tick": 1, "source": "test"},
            {"effect_type": FORTIFICATION_PENDING_EFFECT_TYPE, "created_tick": 2, "source": "test"},
        ]
        site_state["fortified"] = False
        sim.set_rules_state(LocalEncounterInstanceModule.name, state)

        _schedule_local_encounter(sim, "phase6d-m8-save-load-1")
        sim.advance_ticks(5)
        _end_local(sim)
        sim.advance_ticks(4)
        _schedule_local_encounter(sim, "phase6d-m8-save-load-2")
        sim.advance_ticks(5)

    assert simulation_hash(sim_a) == simulation_hash(sim_b)


def test_m8_skip_unsupported_marker_with_diagnostic_then_consume_supported() -> None:
    sim, _, site_key_json, _ = _setup_with_pending_effect(seed=512)

    state = sim.get_rules_state(LocalEncounterInstanceModule.name)
    site_state = state["site_state_by_key"][site_key_json]
    site_state["pending_effects"] = [
        {"effect_type": "future_effect_v9", "created_tick": 1, "source": "test"},
        {"effect_type": FORTIFICATION_PENDING_EFFECT_TYPE, "created_tick": 2, "source": "test"},
    ]
    site_state["fortified"] = False
    sim.set_rules_state(LocalEncounterInstanceModule.name, state)

    _schedule_local_encounter(sim, "phase6d-m8-unsupported-skip")
    sim.advance_ticks(5)

    site_state_after = sim.get_rules_state(LocalEncounterInstanceModule.name)["site_state_by_key"][site_key_json]
    assert site_state_after["fortified"] is True
    assert [effect["effect_type"] for effect in site_state_after["pending_effects"]] == ["future_effect_v9"]

    rejected = _trace(sim, SITE_EFFECT_CONSUMPTION_REJECTED_EVENT_TYPE)
    assert rejected[-1]["params"]["reason"] == "unsupported_site_effect_type"
    assert rejected[-1]["params"]["effect_type"] == "future_effect_v9"
    assert rejected[-1]["params"]["index"] == 0




def test_m8_unsupported_only_skip_is_pure_observation_across_retries() -> None:
    sim, local_space_id, site_key_json, old_ids = _setup_with_pending_effect(seed=514)

    state = sim.get_rules_state(LocalEncounterInstanceModule.name)
    site_state = state["site_state_by_key"][site_key_json]
    site_state["pending_effects"] = [
        {"effect_type": "future_effect_v9", "created_tick": 1, "source": "test"},
    ]
    site_state["fortified"] = False
    before_pending_effects = json.dumps(site_state["pending_effects"], sort_keys=True)
    before_fortified = bool(site_state.get("fortified", False))
    before_rehab_generation = int(site_state.get("rehab_generation", 0))
    sim.set_rules_state(LocalEncounterInstanceModule.name, state)

    _schedule_local_encounter(sim, "phase6d-m8-unsupported-only-1")
    sim.advance_ticks(5)
    _end_local(sim)
    sim.advance_ticks(4)
    _schedule_local_encounter(sim, "phase6d-m8-unsupported-only-2")
    sim.advance_ticks(5)

    after_state = sim.get_rules_state(LocalEncounterInstanceModule.name)["site_state_by_key"][site_key_json]
    assert json.dumps(after_state["pending_effects"], sort_keys=True) == before_pending_effects
    assert bool(after_state.get("fortified", False)) is before_fortified
    assert int(after_state.get("rehab_generation", 0)) == before_rehab_generation

    participant_ids_after = sorted(
        entity_id
        for entity_id, entity in sim.state.entities.items()
        if entity.space_id == local_space_id and entity.template_id == "encounter_hostile_v1"
    )
    assert participant_ids_after == old_ids

    rejections = [
        entry for entry in _trace(sim, SITE_EFFECT_CONSUMPTION_REJECTED_EVENT_TYPE) if entry["params"].get("reason") == "unsupported_site_effect_type"
    ]
    assert len(rejections) == 2
    assert all(entry["params"].get("index") == 0 for entry in rejections)
    assert all(entry["params"].get("effect_type") == "future_effect_v9" for entry in rejections)

def test_m8_malformed_marker_rejects_atomically() -> None:
    sim, local_space_id, site_key_json, old_ids = _setup_with_pending_effect(seed=513)
    state = sim.get_rules_state(LocalEncounterInstanceModule.name)
    site_state = state["site_state_by_key"][site_key_json]
    site_state["pending_effects"] = [
        {"effect_type": "", "created_tick": 1, "source": "test"},
        {"effect_type": REINHABITATION_PENDING_EFFECT_TYPE, "created_tick": 2, "source": "test"},
    ]
    sim.set_rules_state(LocalEncounterInstanceModule.name, state)

    player_before = sim.state.entities[DEFAULT_PLAYER_ENTITY_ID]
    before_space_id = player_before.space_id
    before_position = (player_before.position_x, player_before.position_y)

    _schedule_local_encounter(sim, "phase6d-m8-malformed")
    sim.advance_ticks(5)

    begin = _trace(sim, LOCAL_ENCOUNTER_BEGIN_EVENT_TYPE)[-1]["params"]
    assert begin["transition_applied"] is False
    assert begin["reason"] == "malformed_pending_effect_marker"
    player_after = sim.state.entities[DEFAULT_PLAYER_ENTITY_ID]
    assert player_after.space_id == before_space_id
    assert (player_after.position_x, player_after.position_y) == before_position

    participant_ids_after = sorted(
        entity_id
        for entity_id, entity in sim.state.entities.items()
        if entity.space_id == local_space_id and entity.template_id == "encounter_hostile_v1"
    )
    assert participant_ids_after == old_ids
    pending_after = sim.get_rules_state(LocalEncounterInstanceModule.name)["site_state_by_key"][site_key_json]["pending_effects"]
    assert pending_after[0]["effect_type"] == ""

    rejected = _trace(sim, SITE_EFFECT_CONSUMPTION_REJECTED_EVENT_TYPE)
    assert rejected[-1]["params"]["reason"] == "malformed_pending_effect_marker"
