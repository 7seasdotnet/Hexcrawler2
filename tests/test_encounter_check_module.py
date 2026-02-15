from pathlib import Path

from hexcrawler.content.io import load_game_json, load_world_json, save_game_json
from hexcrawler.sim.core import SimCommand, Simulation
from hexcrawler.sim.encounters import (
    ENCOUNTER_CHECK_EVENT_TYPE,
    ENCOUNTER_CHECK_INTERVAL,
    ENCOUNTER_COOLDOWN_TICKS,
    ENCOUNTER_RESULT_STUB_EVENT_TYPE,
    ENCOUNTER_ROLL_EVENT_TYPE,
    EncounterCheckModule,
)
from hexcrawler.sim.hash import simulation_hash


def _build_sim(seed: int = 123) -> Simulation:
    world = load_world_json("content/examples/basic_map.json")
    sim = Simulation(world=world, seed=seed)
    sim.register_rule_module(EncounterCheckModule())
    return sim


def _input_log() -> list[SimCommand]:
    return [
        SimCommand(tick=2, command_type="noop_input", params={"source": "qa", "index": 0}),
        SimCommand(tick=17, command_type="noop_input", params={"source": "qa", "index": 1}),
    ]


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

    assert state["checks_emitted"] == len(check_entries)
    assert state["eligible_count"] == len(roll_entries)
    assert len(result_entries) == len(roll_entries)
    assert len(roll_entries) > 0

    roll_source_ticks = [int(entry["params"]["tick"]) for entry in roll_entries]
    for prior_tick, next_tick in zip(roll_source_ticks, roll_source_ticks[1:]):
        assert next_tick - prior_tick >= ENCOUNTER_COOLDOWN_TICKS

    for entry in roll_entries:
        roll = int(entry["params"]["roll"])
        assert 1 <= roll <= 100
        assert entry["params"]["context"] == "global"

    for entry in result_entries:
        assert entry["params"]["category"] in {"hostile", "neutral", "omen"}
        assert 1 <= int(entry["params"]["roll"]) <= 100


def test_encounter_result_stub_save_load_round_trip_hash(tmp_path: Path) -> None:
    contiguous = _build_sim(seed=902)
    contiguous.advance_ticks(180)

    split = _build_sim(seed=902)
    split.advance_ticks(83)

    path = tmp_path / "encounter_result_stub_save.json"
    save_game_json(path, split.state.world, split)
    _, loaded = load_game_json(path)
    loaded.register_rule_module(EncounterCheckModule())
    loaded.advance_ticks(97)

    assert simulation_hash(contiguous) == simulation_hash(loaded)
    assert any(
        entry["event_type"] == ENCOUNTER_RESULT_STUB_EVENT_TYPE
        for entry in loaded.get_event_trace()
    )


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
