from pathlib import Path

from hexcrawler.content.io import load_game_json, load_world_json, save_game_json
from hexcrawler.sim.core import EntityState, SimCommand, Simulation, TRAVEL_STEP_EVENT_TYPE
from hexcrawler.sim.encounters import (
    ENCOUNTER_CHECK_EVENT_TYPE,
    ENCOUNTER_CHECK_INTERVAL,
    ENCOUNTER_COOLDOWN_TICKS,
    ENCOUNTER_RESOLVE_REQUEST_EVENT_TYPE,
    ENCOUNTER_RESULT_STUB_EVENT_TYPE,
    ENCOUNTER_ROLL_EVENT_TYPE,
    ENCOUNTER_TRIGGER_IDLE,
    ENCOUNTER_TRIGGER_TRAVEL,
    EncounterCheckModule,
)
from hexcrawler.sim.hash import simulation_hash
from hexcrawler.sim.location import OVERWORLD_HEX_TOPOLOGY
from hexcrawler.sim.movement import axial_to_world_xy
from hexcrawler.sim.world import HexCoord


def _build_sim(seed: int = 123) -> Simulation:
    world = load_world_json("content/examples/basic_map.json")
    sim = Simulation(world=world, seed=seed)
    sim.add_entity(EntityState.from_hex(entity_id="watcher", hex_coord=HexCoord(0, 0), speed_per_tick=0.0))
    sim.register_rule_module(EncounterCheckModule())
    return sim


def _build_travel_sim(seed: int = 123) -> Simulation:
    sim = _build_sim(seed=seed)
    sim.add_entity(EntityState.from_hex(entity_id="runner", hex_coord=HexCoord(0, 0), speed_per_tick=2.0))
    to_x, to_y = axial_to_world_xy(HexCoord(1, 0))
    sim.append_command(
        SimCommand(
            tick=0,
            entity_id="runner",
            command_type="set_target_position",
            params={"x": to_x, "y": to_y},
        )
    )
    return sim


def _input_log() -> list[SimCommand]:
    return [
        SimCommand(tick=2, command_type="noop_input", params={"source": "qa", "index": 0}),
        SimCommand(tick=17, command_type="noop_input", params={"source": "qa", "index": 1}),
    ]


def _location(q: int, r: int) -> dict[str, object]:
    return {"topology_type": OVERWORLD_HEX_TOPOLOGY, "coord": {"q": q, "r": r}}


def test_encounter_check_eligibility_deterministic_hash() -> None:
    sim_a = _build_sim(seed=444)
    sim_b = _build_sim(seed=444)

    for command in _input_log():
        sim_a.append_command(command)
        sim_b.append_command(command.to_dict())

    sim_a.advance_ticks(120)
    sim_b.advance_ticks(120)

    assert simulation_hash(sim_a) == simulation_hash(sim_b)


def test_encounter_check_eligibility_save_load_round_trip_hash(tmp_path: Path) -> None:
    sim_contiguous = _build_sim(seed=555)
    for command in _input_log():
        sim_contiguous.append_command(command)
    sim_contiguous.advance_ticks(120)

    split = _build_sim(seed=555)
    for command in _input_log():
        split.append_command(command)
    split.advance_ticks(45)

    path = tmp_path / "encounter_check_save.json"
    save_game_json(path, split.state.world, split)
    _, loaded = load_game_json(path)
    loaded.register_rule_module(EncounterCheckModule())
    loaded.advance_ticks(75)

    assert simulation_hash(sim_contiguous) == simulation_hash(loaded)


def test_encounter_check_emits_roll_only_on_eligible_and_enforces_cooldown() -> None:
    sim = _build_sim(seed=444)
    sim.advance_ticks(120)

    state = sim.get_rules_state(EncounterCheckModule.name)
    trace = sim.get_event_trace()
    check_entries = [entry for entry in trace if entry["event_type"] == ENCOUNTER_CHECK_EVENT_TYPE]
    roll_entries = [entry for entry in trace if entry["event_type"] == ENCOUNTER_ROLL_EVENT_TYPE]
    result_entries = [
        entry for entry in trace if entry["event_type"] == ENCOUNTER_RESULT_STUB_EVENT_TYPE
    ]
    resolve_entries = [
        entry for entry in trace if entry["event_type"] == ENCOUNTER_RESOLVE_REQUEST_EVENT_TYPE
    ]

    assert state["checks_emitted"] == len(check_entries)
    assert state["eligible_count"] == len(roll_entries)
    assert len(result_entries) == len(roll_entries)
    assert len(resolve_entries) == len(result_entries)
    assert len(roll_entries) > 0

    roll_source_ticks = [int(entry["params"]["tick"]) for entry in roll_entries]
    for prior_tick, next_tick in zip(roll_source_ticks, roll_source_ticks[1:]):
        assert next_tick - prior_tick >= ENCOUNTER_COOLDOWN_TICKS

    for entry in roll_entries:
        roll = int(entry["params"]["roll"])
        assert 1 <= roll <= 100
        assert entry["params"]["context"] == "global"
        assert entry["params"]["trigger"] in {ENCOUNTER_TRIGGER_IDLE, ENCOUNTER_TRIGGER_TRAVEL}
        assert entry["params"]["location"]["topology_type"] == OVERWORLD_HEX_TOPOLOGY

    for entry in result_entries:
        assert entry["params"]["category"] in {"hostile", "neutral", "omen"}
        assert 1 <= int(entry["params"]["roll"]) <= 100
        assert entry["params"]["trigger"] in {ENCOUNTER_TRIGGER_IDLE, ENCOUNTER_TRIGGER_TRAVEL}
        assert entry["params"]["location"]["topology_type"] == OVERWORLD_HEX_TOPOLOGY

    for entry in resolve_entries:
        assert set(entry["params"]) == {"tick", "context", "trigger", "location", "roll", "category"}
        assert entry["params"]["category"] in {"hostile", "neutral", "omen"}
        assert 1 <= int(entry["params"]["roll"]) <= 100
        assert entry["params"]["trigger"] in {ENCOUNTER_TRIGGER_IDLE, ENCOUNTER_TRIGGER_TRAVEL}
        assert entry["params"]["location"]["topology_type"] == OVERWORLD_HEX_TOPOLOGY

    for entry in check_entries:
        assert entry["params"]["trigger"] in {ENCOUNTER_TRIGGER_IDLE, ENCOUNTER_TRIGGER_TRAVEL}
        assert entry["params"]["location"]["topology_type"] == OVERWORLD_HEX_TOPOLOGY


def test_encounter_resolve_request_save_load_round_trip_hash(tmp_path: Path) -> None:
    contiguous = _build_sim(seed=902)
    contiguous.advance_ticks(180)

    split = _build_sim(seed=902)
    split.advance_ticks(83)

    path = tmp_path / "encounter_resolve_request_save.json"
    save_game_json(path, split.state.world, split)
    _, loaded = load_game_json(path)
    loaded.register_rule_module(EncounterCheckModule())
    loaded.advance_ticks(97)

    assert simulation_hash(contiguous) == simulation_hash(loaded)
    trace = loaded.get_event_trace()
    assert any(entry["event_type"] == ENCOUNTER_RESULT_STUB_EVENT_TYPE for entry in trace)
    assert any(entry["event_type"] == ENCOUNTER_RESOLVE_REQUEST_EVENT_TYPE for entry in trace)


def test_encounter_check_rules_state_persists_across_save_load(tmp_path: Path) -> None:
    sim = _build_sim(seed=444)
    sim.advance_ticks(52)

    state_before = sim.get_rules_state(EncounterCheckModule.name)
    assert state_before["last_check_tick"] == 50
    assert state_before["checks_emitted"] == 6
    assert set(state_before) == {
        "last_check_tick",
        "checks_emitted",
        "eligible_count",
        "ineligible_streak",
        "cooldown_until_tick",
    }

    path = tmp_path / "encounter_state.json"
    save_game_json(path, sim.state.world, sim)
    _, loaded = load_game_json(path)
    loaded.register_rule_module(EncounterCheckModule())

    assert loaded.get_rules_state(EncounterCheckModule.name) == state_before

    loaded.advance_ticks(ENCOUNTER_CHECK_INTERVAL + 1)

    state_after = loaded.get_rules_state(EncounterCheckModule.name)
    assert state_after["checks_emitted"] == state_before["checks_emitted"] + 1
    assert any(
        entry["event_type"] == ENCOUNTER_CHECK_EVENT_TYPE
        for entry in loaded.get_event_trace()
    )


def test_encounter_trigger_propagates_check_to_roll_to_result_stub_and_resolve_request() -> None:
    sim = _build_sim(seed=777)
    sim.advance_ticks(220)

    trace = sim.get_event_trace()
    checks_by_tick = {
        int(entry["params"]["tick"]): entry
        for entry in trace
        if entry["event_type"] == ENCOUNTER_CHECK_EVENT_TYPE
    }
    roll_entries = [entry for entry in trace if entry["event_type"] == ENCOUNTER_ROLL_EVENT_TYPE]
    result_entries = {
        (int(entry["tick"]), int(entry["params"]["roll"])): entry
        for entry in trace
        if entry["event_type"] == ENCOUNTER_RESULT_STUB_EVENT_TYPE
    }
    resolve_entries = {
        (int(entry["tick"]), int(entry["params"]["roll"])): entry
        for entry in trace
        if entry["event_type"] == ENCOUNTER_RESOLVE_REQUEST_EVENT_TYPE
    }

    assert roll_entries
    for roll_entry in roll_entries:
        source_tick = int(roll_entry["params"]["tick"])
        roll_value = int(roll_entry["params"]["roll"])
        trigger = roll_entry["params"]["trigger"]
        location = roll_entry["params"]["location"]

        assert checks_by_tick[source_tick]["params"]["trigger"] == trigger
        assert checks_by_tick[source_tick]["params"]["location"] == location

        result_key = (int(roll_entry["tick"]) + 1, roll_value)
        result_entry = result_entries[result_key]
        assert result_entry["params"]["trigger"] == trigger
        assert result_entry["params"]["location"] == location

        resolve_key = (result_key[0] + 1, roll_value)
        resolve_entry = resolve_entries[resolve_key]
        assert set(resolve_entry["params"]) == {"tick", "context", "trigger", "location", "roll", "category"}
        assert resolve_entry["params"]["tick"] == result_entry["params"]["tick"]
        assert resolve_entry["params"]["context"] == result_entry["params"]["context"]
        assert resolve_entry["params"]["trigger"] == result_entry["params"]["trigger"]
        assert resolve_entry["params"]["location"] == result_entry["params"]["location"]
        assert resolve_entry["params"]["roll"] == result_entry["params"]["roll"]
        assert resolve_entry["params"]["category"] == result_entry["params"]["category"]


def test_travel_step_event_serializes_and_emits_travel_triggered_check(tmp_path: Path) -> None:
    sim = _build_travel_sim(seed=21)
    sim.advance_ticks(1)

    pending_travel_steps = [
        event for event in sim.pending_events() if event.event_type == TRAVEL_STEP_EVENT_TYPE
    ]
    assert len(pending_travel_steps) == 1
    assert pending_travel_steps[0].params["entity_id"] == "runner"
    assert pending_travel_steps[0].params["location_from"] == {"topology_type": OVERWORLD_HEX_TOPOLOGY, "coord": {"q": 0, "r": 0}}
    assert pending_travel_steps[0].params["location_to"] == {"topology_type": OVERWORLD_HEX_TOPOLOGY, "coord": {"q": 1, "r": 0}}

    save_path = tmp_path / "travel_step_save.json"
    save_game_json(save_path, sim.state.world, sim)
    _, loaded = load_game_json(save_path)
    loaded.register_rule_module(EncounterCheckModule())

    loaded_travel_steps = [
        event for event in loaded.pending_events() if event.event_type == TRAVEL_STEP_EVENT_TYPE
    ]
    assert [event.to_dict() for event in loaded_travel_steps] == [
        event.to_dict() for event in pending_travel_steps
    ]

    loaded.advance_ticks(2)

    trace = loaded.get_event_trace()
    travel_entry = next(entry for entry in trace if entry["event_type"] == TRAVEL_STEP_EVENT_TYPE)
    travel_check_entry = next(
        entry
        for entry in trace
        if entry["event_type"] == ENCOUNTER_CHECK_EVENT_TYPE
        and entry["params"]["trigger"] == ENCOUNTER_TRIGGER_TRAVEL
    )

    assert travel_check_entry["tick"] == travel_entry["tick"] + 1
    assert travel_check_entry["params"]["tick"] == travel_entry["params"]["tick"]
    assert travel_check_entry["params"]["location"] == travel_entry["params"]["location_to"]


def test_travel_trigger_propagates_through_roll_result_stub_and_resolve_request() -> None:
    sim = _build_sim(seed=90)
    sim.schedule_event_at(
        tick=0,
        event_type=ENCOUNTER_ROLL_EVENT_TYPE,
        params={
            "tick": 0,
            "context": "global",
            "roll": 60,
            "trigger": ENCOUNTER_TRIGGER_TRAVEL,
            "location": _location(1, 0),
        },
    )

    sim.advance_ticks(3)
    trace = sim.get_event_trace()

    result_entry = next(
        entry for entry in trace if entry["event_type"] == ENCOUNTER_RESULT_STUB_EVENT_TYPE
    )
    resolve_entry = next(
        entry for entry in trace if entry["event_type"] == ENCOUNTER_RESOLVE_REQUEST_EVENT_TYPE
    )
    assert result_entry["params"]["trigger"] == ENCOUNTER_TRIGGER_TRAVEL
    assert result_entry["params"]["location"] == _location(1, 0)
    assert resolve_entry["tick"] == result_entry["tick"] + 1
    assert resolve_entry["params"] == {
        "tick": result_entry["params"]["tick"],
        "context": result_entry["params"]["context"],
        "trigger": result_entry["params"]["trigger"],
        "location": result_entry["params"]["location"],
        "roll": result_entry["params"]["roll"],
        "category": result_entry["params"]["category"],
    }


def test_travel_channel_save_load_and_replay_hash_identity(tmp_path: Path) -> None:
    contiguous = _build_travel_sim(seed=314)
    contiguous.advance_ticks(80)

    split = _build_travel_sim(seed=314)
    split.advance_ticks(35)

    save_path = tmp_path / "travel_trigger_save.json"
    save_game_json(save_path, split.state.world, split)
    _, loaded = load_game_json(save_path)
    loaded.register_rule_module(EncounterCheckModule())
    loaded.advance_ticks(45)

    replay_a = _build_travel_sim(seed=314)
    replay_b = _build_travel_sim(seed=314)
    replay_a.advance_ticks(80)
    replay_b.advance_ticks(80)

    assert simulation_hash(contiguous) == simulation_hash(loaded)
    assert simulation_hash(replay_a) == simulation_hash(replay_b)


def test_encounter_trigger_contract_regression_hash_is_stable() -> None:
    sim = _build_sim(seed=444)
    for command in _input_log():
        sim.append_command(command)

    sim.advance_ticks(120)

    assert (
        simulation_hash(sim)
        == "b7d9386e7c37d77d927bdfde1382633e26e9163cbf4cd5bc8d7d473e05dd4fed"
    )


def test_travel_trigger_contract_regression_hash_is_stable() -> None:
    sim = _build_travel_sim(seed=21)
    sim.advance_ticks(80)

    assert (
        simulation_hash(sim)
        == "050a1ff80bed493e33d1b3db0e3aa5d799eda233e89426ca002776a762f3641d"
    )
