import hashlib
import json

from hexcrawler.content.io import load_world_json
from hexcrawler.sim.core import DEFAULT_PLAYER_ENTITY_ID, EntityState, SimCommand, Simulation
from hexcrawler.sim.encounters import (
    ENCOUNTER_ACTION_EXECUTE_EVENT_TYPE,
    END_LOCAL_ENCOUNTER_INTENT,
    LOCAL_ENCOUNTER_BEGIN_EVENT_TYPE,
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


def test_m6_consumes_pending_effect_once_and_increments_generation_with_hash_stability() -> None:
    sim, local_space_id, site_key_json, _ = _setup_with_pending_effect(seed=501)

    _schedule_local_encounter(sim, "phase6d-m6-reenter")
    sim.advance_ticks(5)

    state = sim.get_rules_state(LocalEncounterInstanceModule.name)
    site_state = state["site_state_by_key"][site_key_json]
    assert site_state["rehab_generation"] == 1
    assert [e for e in site_state["pending_effects"] if e["effect_type"] == REINHABITATION_PENDING_EFFECT_TYPE] == []

    consumed = _trace(sim, SITE_EFFECT_CONSUMED_EVENT_TYPE)
    assert len(consumed) == 1
    assert consumed[0]["params"]["generation_after"] == 1

    scheduled = _trace(sim, SITE_EFFECT_SCHEDULED_EVENT_TYPE)
    assert len(scheduled) == 1

    payload = sim.simulation_payload()
    loaded = Simulation.from_simulation_payload(payload)
    loaded.register_rule_module(EncounterActionExecutionModule())
    loaded.register_rule_module(LocalEncounterInstanceModule())
    assert loaded.get_rules_state(LocalEncounterInstanceModule.name)["site_state_by_key"][site_key_json]["rehab_generation"] == 1

    _end_local(sim)
    sim.advance_ticks(4)
    hash_a = simulation_hash(sim)

    sim_b, _, _, _ = _setup_with_pending_effect(seed=501)
    _schedule_local_encounter(sim_b, "phase6d-m6-reenter")
    sim_b.advance_ticks(5)
    _end_local(sim_b)
    sim_b.advance_ticks(4)
    assert simulation_hash(sim_b) == hash_a
    assert local_space_id in sim.state.world.spaces


def test_m6_reinhabitation_replace_policy_uses_generation_scoped_ids_and_is_idempotent() -> None:
    sim, local_space_id, _, old_ids = _setup_with_pending_effect(seed=502)

    _schedule_local_encounter(sim, "phase6d-m6-reenter")
    sim.advance_ticks(5)

    begins = _trace(sim, LOCAL_ENCOUNTER_BEGIN_EVENT_TYPE)
    replace_begin = begins[-1]["params"]
    assert replace_begin["reuse"] is True
    assert replace_begin["to_spawn_coord"] == {"x": 1, "y": 6}

    new_ids = sorted(
        entity_id
        for entity_id, entity in sim.state.entities.items()
        if entity.space_id == local_space_id and entity.template_id == "encounter_hostile_v1"
    )
    assert len(new_ids) == 1
    assert new_ids[0] not in old_ids
    assert new_ids[0].startswith("spawn:")
    assert ":gen1:0" in new_ids[0]

    _end_local(sim)
    sim.advance_ticks(4)
    _schedule_local_encounter(sim, "phase6d-m6-reenter-no-effect")
    sim.advance_ticks(5)

    newest_begin = _trace(sim, LOCAL_ENCOUNTER_BEGIN_EVENT_TYPE)[-1]["params"]
    assert newest_begin["reuse"] is True
    assert newest_begin["spawned_entities"][0]["entity_id"] == new_ids[0]
    assert newest_begin["spawned_entities"][0]["placement_rule"] == "reuse_existing"


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




def test_m6_reinhabitation_rejection_is_atomic_and_does_not_move_actor() -> None:
    sim, local_space_id, site_key_json, old_ids = _setup_with_pending_effect(seed=505)

    state = sim.get_rules_state(LocalEncounterInstanceModule.name)
    site_key = state["site_state_by_key"][site_key_json]["site_key"]
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

    player_before = sim.state.entities[DEFAULT_PLAYER_ENTITY_ID]
    before_space_id = player_before.space_id
    before_position = (player_before.position_x, player_before.position_y)

    _schedule_local_encounter(sim, "phase6d-m6-reenter-reject")
    sim.advance_ticks(5)

    begin = _trace(sim, LOCAL_ENCOUNTER_BEGIN_EVENT_TYPE)[-1]["params"]
    assert begin["reuse"] is True
    assert begin["transition_applied"] is False
    assert begin["reason"] == "reinhabitation_replace_failed"

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
    assert rejected[-1]["params"]["reason"] == "participant_replace_failed"

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
