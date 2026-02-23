from hexcrawler.content.io import load_world_json
from hexcrawler.sim.core import EntityState, SimCommand, Simulation
from hexcrawler.sim.encounters import (
    END_LOCAL_ENCOUNTER_INTENT,
    ENCOUNTER_RESOLVE_REQUEST_EVENT_TYPE,
    LOCAL_ENCOUNTER_BEGIN_EVENT_TYPE,
    MAX_PENDING_EFFECTS_PER_SITE,
    MAX_SITE_CHECKS_PER_TICK,
    REINHABITATION_PENDING_EFFECT_TYPE,
    SITE_CHECK_INTERVAL_TICKS,
    SITE_EFFECT_SCHEDULED_EVENT_TYPE,
    SITE_STATE_TICK_EVENT_TYPE,
    STALE_TICKS,
    LocalEncounterInstanceModule,
    LocalEncounterRequestModule,
)
from hexcrawler.sim.location import SQUARE_GRID_TOPOLOGY
from hexcrawler.sim.movement import square_grid_cell_to_world_xy
from hexcrawler.sim.world import CAMPAIGN_SPACE_ROLE, SpaceState

CAMPAIGN_SPACE_ID = "campaign_plane_site_state"


def _build_sim(seed: int = 123) -> Simulation:
    world = load_world_json("content/examples/basic_map.json")
    world.spaces[CAMPAIGN_SPACE_ID] = SpaceState(
        space_id=CAMPAIGN_SPACE_ID,
        topology_type=SQUARE_GRID_TOPOLOGY,
        role=CAMPAIGN_SPACE_ROLE,
        topology_params={"width": 8, "height": 8, "origin": {"x": 10, "y": 20}},
    )
    sim = Simulation(world=world, seed=seed)
    scout_x, scout_y = square_grid_cell_to_world_xy(12, 21)
    sim.add_entity(EntityState(entity_id="scout", position_x=scout_x, position_y=scout_y, space_id=CAMPAIGN_SPACE_ID))
    sim.register_rule_module(LocalEncounterRequestModule())
    sim.register_rule_module(LocalEncounterInstanceModule())
    return sim


def _schedule_request(sim: Simulation) -> None:
    sim.schedule_event_at(
        tick=0,
        event_type=ENCOUNTER_RESOLVE_REQUEST_EVENT_TYPE,
        params={
            "tick": 0,
            "context": "global",
            "trigger": "travel",
            "location": {
                "space_id": CAMPAIGN_SPACE_ID,
                "topology_type": SQUARE_GRID_TOPOLOGY,
                "coord": {"x": 12, "y": 21},
            },
            "roll": 48,
            "category": "hostile",
            "table_id": "enc_table_primary",
            "entry_id": "wolves_1",
        },
    )


def _issue_end_intent(sim: Simulation) -> None:
    sim.append_command(
        SimCommand(
            tick=sim.state.tick,
            entity_id="scout",
            command_type=END_LOCAL_ENCOUNTER_INTENT,
            params={"intent": END_LOCAL_ENCOUNTER_INTENT, "entity_id": "scout", "tags": []},
        )
    )


def _trace_by_type(sim: Simulation, event_type: str) -> list[dict]:
    return [entry for entry in sim.get_event_trace() if entry["event_type"] == event_type]


def test_stale_transition_schedules_reinhabitation_pending_once() -> None:
    sim = _build_sim(seed=19)
    _schedule_request(sim)
    sim.advance_ticks(3)

    begin = _trace_by_type(sim, LOCAL_ENCOUNTER_BEGIN_EVENT_TYPE)[0]
    local_space_id = begin["params"]["to_space_id"]

    _issue_end_intent(sim)
    sim.advance_ticks(3)

    state = sim.get_rules_state(LocalEncounterInstanceModule.name)
    site_key = state["active_by_local_space"][local_space_id]["site_key"]
    site_key_json = LocalEncounterInstanceModule._site_key_json(site_key)  # noqa: SLF001 - deterministic key helper usage in test

    sim.advance_ticks(STALE_TICKS + SITE_CHECK_INTERVAL_TICKS)

    state = sim.get_rules_state(LocalEncounterInstanceModule.name)
    site_state = state["site_state_by_key"][site_key_json]
    assert site_state["status"] == "stale"
    assert "stale" in site_state["tags"]

    pending_effects = site_state["pending_effects"]
    matching = [effect for effect in pending_effects if effect["effect_type"] == REINHABITATION_PENDING_EFFECT_TYPE]
    assert len(matching) == 1

    sim.advance_ticks(STALE_TICKS + SITE_CHECK_INTERVAL_TICKS)
    state = sim.get_rules_state(LocalEncounterInstanceModule.name)
    pending_effects_after = state["site_state_by_key"][site_key_json]["pending_effects"]
    matching_after = [effect for effect in pending_effects_after if effect["effect_type"] == REINHABITATION_PENDING_EFFECT_TYPE]
    assert len(matching_after) == 1

    effect_events = _trace_by_type(sim, SITE_EFFECT_SCHEDULED_EVENT_TYPE)
    assert len(effect_events) == 1
    assert effect_events[0]["params"]["site_key"] == site_key
    assert effect_events[0]["params"]["effect_type"] == REINHABITATION_PENDING_EFFECT_TYPE


def test_pending_effects_save_load_stability() -> None:
    sim = _build_sim(seed=51)
    _schedule_request(sim)
    sim.advance_ticks(3)
    _issue_end_intent(sim)
    sim.advance_ticks(3)

    sim.advance_ticks(STALE_TICKS + SITE_CHECK_INTERVAL_TICKS)
    payload = sim.simulation_payload()

    loaded = Simulation.from_simulation_payload(payload)
    loaded.register_rule_module(LocalEncounterRequestModule())
    loaded.register_rule_module(LocalEncounterInstanceModule())

    assert sim.get_rules_state(LocalEncounterInstanceModule.name)["site_state_by_key"] == loaded.get_rules_state(
        LocalEncounterInstanceModule.name
    )["site_state_by_key"]
    assert _trace_by_type(sim, SITE_EFFECT_SCHEDULED_EVENT_TYPE) == _trace_by_type(loaded, SITE_EFFECT_SCHEDULED_EVENT_TYPE)


def test_pending_effects_boundedness_cap() -> None:
    sim = _build_sim(seed=77)
    sim.advance_ticks(1)

    raw_state = sim.get_rules_state(LocalEncounterInstanceModule.name)
    site_key = {
        "origin_space_id": CAMPAIGN_SPACE_ID,
        "origin_coord": {"x": 10, "y": 20},
        "origin_topology_type": SQUARE_GRID_TOPOLOGY,
        "template_id": "default_local",
    }
    site_key_json = LocalEncounterInstanceModule._site_key_json(site_key)  # noqa: SLF001 - deterministic key helper usage in test
    raw_state["site_state_by_key"] = {
        site_key_json: {
            "site_key": site_key,
            "status": "inactive",
            "last_active_tick": 0,
            "next_check_tick": 0,
            "tags": [],
            "pending_effects": [
                {"effect_type": f"effect_{i}", "created_tick": i, "source": "test"}
                for i in range(MAX_PENDING_EFFECTS_PER_SITE + 3)
            ],
        }
    }
    sim.set_rules_state(LocalEncounterInstanceModule.name, raw_state)

    sim.advance_ticks(1)
    state = sim.get_rules_state(LocalEncounterInstanceModule.name)
    pending = state["site_state_by_key"][site_key_json]["pending_effects"]

    assert len(pending) == MAX_PENDING_EFFECTS_PER_SITE
    assert [effect["effect_type"] for effect in pending] == [
        f"effect_{i}" for i in range(3, MAX_PENDING_EFFECTS_PER_SITE + 3)
    ]


def test_site_state_timer_processing_is_bounded_and_deferred() -> None:
    sim = _build_sim(seed=77)
    sim.advance_ticks(1)

    raw_state = sim.get_rules_state(LocalEncounterInstanceModule.name)

    site_state_by_key = {}
    for i in range(MAX_SITE_CHECKS_PER_TICK + 3):
        site_key = {
            "origin_space_id": CAMPAIGN_SPACE_ID,
            "origin_coord": {"x": 10 + i, "y": 20},
            "origin_topology_type": SQUARE_GRID_TOPOLOGY,
            "template_id": "default_local",
        }
        site_key_json = LocalEncounterInstanceModule._site_key_json(site_key)  # noqa: SLF001 - deterministic key helper usage in test
        site_state_by_key[site_key_json] = {
            "site_key": site_key,
            "status": "inactive",
            "last_active_tick": 0,
            "next_check_tick": 0,
            "tags": [],
            "pending_effects": [],
        }

    raw_state["site_state_by_key"] = dict(sorted(site_state_by_key.items()))
    sim.set_rules_state(LocalEncounterInstanceModule.name, raw_state)

    sim.advance_ticks(1)
    first_batch = _trace_by_type(sim, SITE_STATE_TICK_EVENT_TYPE)
    assert len(first_batch) == MAX_SITE_CHECKS_PER_TICK
    first_keys = [entry["params"]["site_key"] for entry in first_batch]

    sim.advance_ticks(1)
    second_batch = _trace_by_type(sim, SITE_STATE_TICK_EVENT_TYPE)[MAX_SITE_CHECKS_PER_TICK:]
    assert len(second_batch) == 3
    second_keys = [entry["params"]["site_key"] for entry in second_batch]

    expected_order = [site_state_by_key[key]["site_key"] for key in sorted(site_state_by_key)]
    assert first_keys + second_keys == expected_order
