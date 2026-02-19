from pathlib import Path

from hexcrawler.content.io import load_game_json, load_world_json, save_game_json
from hexcrawler.sim.core import Simulation
from hexcrawler.sim.encounters import (
    ENCOUNTER_ACTION_EXECUTE_EVENT_TYPE,
    ENCOUNTER_ACTION_OUTCOME_EVENT_TYPE,
    ENCOUNTER_ACTION_STUB_EVENT_TYPE,
    EncounterActionExecutionModule,
)
from hexcrawler.sim.hash import simulation_hash


def _action_stub_params(actions: list[dict[str, object]]) -> dict[str, object]:
    return {
        "tick": 0,
        "context": "global",
        "trigger": "idle",
        "location": {"space_id": "overworld", "topology_type": "overworld_hex", "coord": {"q": 0, "r": 0}},
        "roll": 50,
        "category": "hostile",
        "table_id": "fixture",
        "entry_id": "entry_a",
        "actions": actions,
    }


def _build_execution_sim(seed: int = 37) -> Simulation:
    sim = Simulation(world=load_world_json("content/examples/basic_map.json"), seed=seed)
    sim.register_rule_module(EncounterActionExecutionModule())
    return sim


def test_action_execute_event_scheduled_once_from_action_stub_plus_one_tick() -> None:
    sim = _build_execution_sim()
    stub_event_id = sim.schedule_event_at(
        tick=0,
        event_type=ENCOUNTER_ACTION_STUB_EVENT_TYPE,
        params=_action_stub_params(
            [{"action_type": "signal_intent", "template_id": "omens.crows", "params": {}}]
        ),
    )

    sim.advance_ticks(2)

    execute_entries = [
        entry for entry in sim.get_event_trace() if entry["event_type"] == ENCOUNTER_ACTION_EXECUTE_EVENT_TYPE
    ]
    assert len(execute_entries) == 1
    assert execute_entries[0]["tick"] == 1
    assert execute_entries[0]["params"]["source_event_id"] == stub_event_id


def test_supported_actions_create_signal_and_track_records_with_stable_action_uids() -> None:
    sim = _build_execution_sim(seed=41)
    stub_event_id = sim.schedule_event_at(
        tick=0,
        event_type=ENCOUNTER_ACTION_STUB_EVENT_TYPE,
        params=_action_stub_params(
            [
                {
                    "action_type": "signal_intent",
                    "template_id": "omens.crows",
                    "params": {"detail": "north", "ttl_ticks": 5},
                },
                {
                    "action_type": "track_intent",
                    "template_id": "tracks.bootprint",
                    "params": {"expires_tick": 12, "size": "large"},
                },
            ]
        ),
    )

    sim.advance_ticks(4)

    assert sim.state.world.signals == [
        {
            "signal_uid": f"{stub_event_id}:0",
            "template_id": "omens.crows",
            "location": {"space_id": "overworld", "topology_type": "overworld_hex", "coord": {"q": 0, "r": 0}},
            "created_tick": 1,
            "params": {"detail": "north", "ttl_ticks": 5},
            "expires_tick": 6,
        }
    ]
    assert sim.state.world.tracks == [
        {
            "track_uid": f"{stub_event_id}:1",
            "template_id": "tracks.bootprint",
            "location": {"space_id": "overworld", "topology_type": "overworld_hex", "coord": {"q": 0, "r": 0}},
            "created_tick": 1,
            "params": {"expires_tick": 12, "size": "large"},
            "expires_tick": 12,
        }
    ]


def test_spawn_intent_appends_descriptor_once_with_required_fields() -> None:
    sim = _build_execution_sim(seed=141)
    execute_params = {
        "source_event_id": "evt-spawn-source",
        "location": {"space_id": "overworld", "topology_type": "overworld_hex", "coord": {"q": 2, "r": -1}},
        "actions": [
            {
                "action_type": "spawn_intent",
                "template_id": "bandit_scouts",
                "quantity": 2,
                "params": {"ttl_ticks": 4, "note": "scouts"},
                "extra_hint": "north_road",
            }
        ],
    }
    sim.schedule_event_at(tick=0, event_type=ENCOUNTER_ACTION_EXECUTE_EVENT_TYPE, params=execute_params)

    sim.advance_ticks(3)

    assert sim.state.world.spawn_descriptors == [
        {
            "created_tick": 0,
            "location": {"space_id": "overworld", "topology_type": "overworld_hex", "coord": {"q": 2, "r": -1}},
            "template_id": "bandit_scouts",
            "quantity": 2,
            "expires_tick": 4,
            "source_event_id": "evt-spawn-source",
            "action_uid": "evt-spawn-source:0",
            "params": {"ttl_ticks": 4, "note": "scouts"},
            "extra_hint": "north_road",
        }
    ]

    outcomes = [entry for entry in sim.get_event_trace() if entry["event_type"] == ENCOUNTER_ACTION_OUTCOME_EVENT_TYPE]
    assert outcomes[-1]["params"]["outcome"] == "executed"
    assert outcomes[-1]["params"]["quantity"] == 2
    assert outcomes[-1]["params"]["location"] == {"space_id": "overworld", "topology_type": "overworld_hex", "coord": {"q": 2, "r": -1}}


def test_idempotence_repeated_execution_path_does_not_duplicate_world_records() -> None:
    sim = _build_execution_sim(seed=5)
    execute_params = {
        "source_event_id": "evt-source",
        "location": {"space_id": "overworld", "topology_type": "overworld_hex", "coord": {"q": 1, "r": -1}},
        "actions": [{"action_type": "signal_intent", "template_id": "omens.crows", "params": {}}],
    }
    sim.schedule_event_at(tick=0, event_type=ENCOUNTER_ACTION_EXECUTE_EVENT_TYPE, params=execute_params)
    sim.schedule_event_at(tick=1, event_type=ENCOUNTER_ACTION_EXECUTE_EVENT_TYPE, params=execute_params)

    sim.advance_ticks(4)

    assert len(sim.state.world.signals) == 1
    outcomes = [entry for entry in sim.get_event_trace() if entry["event_type"] == ENCOUNTER_ACTION_OUTCOME_EVENT_TYPE]
    assert [entry["params"]["outcome"] for entry in outcomes] == ["executed", "already_executed"]


def test_spawn_idempotence_reexecuting_action_uid_does_not_duplicate_descriptors() -> None:
    sim = _build_execution_sim(seed=88)
    execute_params = {
        "source_event_id": "evt-source",
        "location": {"space_id": "overworld", "topology_type": "overworld_hex", "coord": {"q": 1, "r": -1}},
        "actions": [{"action_type": "spawn_intent", "template_id": "bandit_scouts", "params": {}}],
    }
    sim.schedule_event_at(tick=0, event_type=ENCOUNTER_ACTION_EXECUTE_EVENT_TYPE, params=execute_params)
    sim.schedule_event_at(tick=1, event_type=ENCOUNTER_ACTION_EXECUTE_EVENT_TYPE, params=execute_params)

    sim.advance_ticks(4)

    assert len(sim.state.world.spawn_descriptors) == 1
    outcomes = [entry for entry in sim.get_event_trace() if entry["event_type"] == ENCOUNTER_ACTION_OUTCOME_EVENT_TYPE]
    assert [entry["params"]["outcome"] for entry in outcomes] == ["executed", "already_executed"]


def test_idempotence_save_load_continuation_does_not_duplicate_world_records(tmp_path: Path) -> None:
    sim = _build_execution_sim(seed=15)
    execute_params = {
        "source_event_id": "evt-source",
        "location": {"space_id": "overworld", "topology_type": "overworld_hex", "coord": {"q": 0, "r": 0}},
        "actions": [{"action_type": "track_intent", "template_id": "tracks.bootprint", "params": {}}],
    }
    sim.schedule_event_at(tick=0, event_type=ENCOUNTER_ACTION_EXECUTE_EVENT_TYPE, params=execute_params)
    sim.advance_ticks(2)

    save_path = tmp_path / "action_execution_save.json"
    save_game_json(save_path, sim.state.world, sim)

    _, loaded = load_game_json(save_path)
    loaded.register_rule_module(EncounterActionExecutionModule())
    loaded.schedule_event_at(tick=loaded.state.tick, event_type=ENCOUNTER_ACTION_EXECUTE_EVENT_TYPE, params=execute_params)
    loaded.advance_ticks(2)

    assert len(loaded.state.world.tracks) == 1
    assert loaded.state.world.tracks[0]["track_uid"] == "evt-source:0"


def test_unsupported_actions_are_ignored_deterministically_with_outcomes() -> None:
    sim = _build_execution_sim(seed=66)
    sim.schedule_event_at(
        tick=0,
        event_type=ENCOUNTER_ACTION_EXECUTE_EVENT_TYPE,
        params={
            "source_event_id": "evt-source",
            "location": {"space_id": "overworld", "topology_type": "overworld_hex", "coord": {"q": 0, "r": 0}},
            "actions": [{"action_type": "weather_shift", "template_id": "cold.front", "params": {}}],
        },
    )

    sim.advance_ticks(3)

    outcomes = [entry for entry in sim.get_event_trace() if entry["event_type"] == ENCOUNTER_ACTION_OUTCOME_EVENT_TYPE]
    assert len(outcomes) == 1
    assert outcomes[0]["params"]["outcome"] == "ignored_unsupported"
    assert sim.state.world.signals == []
    assert sim.state.world.tracks == []


def test_action_execution_save_load_hash_identity() -> None:
    contiguous = _build_execution_sim(seed=71)
    split = _build_execution_sim(seed=71)
    execute_params = {
        "source_event_id": "evt-source",
        "location": {"space_id": "overworld", "topology_type": "overworld_hex", "coord": {"q": 0, "r": 2}},
        "actions": [{"action_type": "signal_intent", "template_id": "omens.crows", "params": {"ttl_ticks": 2}}],
    }
    contiguous.schedule_event_at(tick=0, event_type=ENCOUNTER_ACTION_EXECUTE_EVENT_TYPE, params=execute_params)
    split.schedule_event_at(tick=0, event_type=ENCOUNTER_ACTION_EXECUTE_EVENT_TYPE, params=execute_params)

    contiguous.advance_ticks(8)
    split.advance_ticks(3)
    payload = split.simulation_payload()
    loaded = Simulation.from_simulation_payload(payload)
    loaded.register_rule_module(EncounterActionExecutionModule())
    loaded.advance_ticks(5)

    assert simulation_hash(contiguous) == simulation_hash(loaded)


def test_action_execution_replay_hash_identity() -> None:
    sim_a = _build_execution_sim(seed=72)
    sim_b = _build_execution_sim(seed=72)

    for sim in (sim_a, sim_b):
        sim.schedule_event_at(
            tick=0,
            event_type=ENCOUNTER_ACTION_EXECUTE_EVENT_TYPE,
            params={
                "source_event_id": "evt-source",
                "location": {"space_id": "overworld", "topology_type": "overworld_hex", "coord": {"q": 0, "r": 0}},
                "actions": [
                    {"action_type": "signal_intent", "template_id": "omens.crows", "params": {}},
                    {"action_type": "track_intent", "template_id": "tracks.bootprint", "params": {}},
                ],
            },
        )

    sim_a.advance_ticks(6)
    sim_b.advance_ticks(6)

    assert simulation_hash(sim_a) == simulation_hash(sim_b)


def test_spawn_execution_replay_hash_and_summary_identity() -> None:
    sim_a = _build_execution_sim(seed=903)
    sim_b = _build_execution_sim(seed=903)
    execute_params = {
        "source_event_id": "evt-source",
        "location": {"space_id": "overworld", "topology_type": "overworld_hex", "coord": {"q": -2, "r": 1}},
        "actions": [
            {"action_type": "spawn_intent", "template_id": "bandit_scouts", "quantity": 1, "params": {}},
            {"action_type": "spawn_intent", "template_id": "wolf_pack", "quantity": 3, "params": {"ttl_ticks": 2}},
        ],
    }

    for sim in (sim_a, sim_b):
        sim.schedule_event_at(tick=0, event_type=ENCOUNTER_ACTION_EXECUTE_EVENT_TYPE, params=execute_params)
        sim.advance_ticks(6)

    summary_a = [
        {
            "created_tick": row["created_tick"],
            "location": row["location"],
            "template_id": row["template_id"],
            "quantity": row["quantity"],
            "expires_tick": row["expires_tick"],
            "action_uid": row["action_uid"],
        }
        for row in sim_a.state.world.spawn_descriptors
    ]
    summary_b = [
        {
            "created_tick": row["created_tick"],
            "location": row["location"],
            "template_id": row["template_id"],
            "quantity": row["quantity"],
            "expires_tick": row["expires_tick"],
            "action_uid": row["action_uid"],
        }
        for row in sim_b.state.world.spawn_descriptors
    ]

    assert simulation_hash(sim_a) == simulation_hash(sim_b)
    assert summary_a == summary_b


def test_action_execution_contract_regression_hash_is_stable() -> None:
    sim = _build_execution_sim(seed=17)
    sim.schedule_event_at(
        tick=0,
        event_type=ENCOUNTER_ACTION_EXECUTE_EVENT_TYPE,
        params={
            "source_event_id": "evt-source",
            "location": {"space_id": "overworld", "topology_type": "overworld_hex", "coord": {"q": 0, "r": 0}},
            "actions": [
                {"action_type": "signal_intent", "template_id": "omens.crows", "params": {"ttl_ticks": 3}},
                {"action_type": "weather_shift", "template_id": "cold.front", "params": {}},
                {"action_type": "track_intent", "template_id": "tracks.bootprint", "params": {}},
            ],
        },
    )

    sim.advance_ticks(8)

    assert simulation_hash(sim) == "8f88f56638804ac99981627692ac3f697a95e3e01640960909243d252ba87d3d"
