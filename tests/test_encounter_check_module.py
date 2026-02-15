from pathlib import Path

from hexcrawler.content.io import load_game_json, load_world_json, save_game_json
from hexcrawler.sim.core import SimCommand, Simulation
from hexcrawler.sim.encounters import ENCOUNTER_CHECK_EVENT_TYPE, EncounterCheckModule
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


def test_encounter_check_deterministic_emission_hash() -> None:
    sim_a = _build_sim(seed=444)
    sim_b = _build_sim(seed=444)

    for command in _input_log():
        sim_a.append_command(command)
        sim_b.append_command(command.to_dict())

    sim_a.advance_ticks(65)
    sim_b.advance_ticks(65)

    assert simulation_hash(sim_a) == simulation_hash(sim_b)


def test_encounter_check_save_load_round_trip_hash(tmp_path: Path) -> None:
    sim_contiguous = _build_sim(seed=555)
    for command in _input_log():
        sim_contiguous.append_command(command)
    sim_contiguous.advance_ticks(80)

    split = _build_sim(seed=555)
    for command in _input_log():
        split.append_command(command)
    split.advance_ticks(35)

    path = tmp_path / "encounter_check_save.json"
    save_game_json(path, split.state.world, split)
    _, loaded = load_game_json(path)
    loaded.register_rule_module(EncounterCheckModule())
    loaded.advance_ticks(45)

    assert simulation_hash(sim_contiguous) == simulation_hash(loaded)


def test_encounter_check_replay_stability_from_input_log() -> None:
    base = _build_sim(seed=777)
    replay = _build_sim(seed=777)

    for command in _input_log():
        base.append_command(command)

    for command in base.input_log:
        replay.append_command(command.to_dict())

    base.advance_ticks(70)
    replay.advance_ticks(70)

    assert simulation_hash(base) == simulation_hash(replay)


def test_encounter_check_rules_state_persists_across_save_load(tmp_path: Path) -> None:
    sim = _build_sim(seed=888)
    sim.advance_ticks(52)

    state_before = sim.get_rules_state(EncounterCheckModule.name)
    assert state_before == {"last_check_tick": 50, "checks_emitted": 6}

    path = tmp_path / "encounter_state.json"
    save_game_json(path, sim.state.world, sim)
    _, loaded = load_game_json(path)
    loaded.register_rule_module(EncounterCheckModule())

    assert loaded.get_rules_state(EncounterCheckModule.name) == state_before

    loaded.advance_ticks(11)

    assert loaded.get_rules_state(EncounterCheckModule.name) == {"last_check_tick": 60, "checks_emitted": 7}
    assert any(
        entry["event_type"] == ENCOUNTER_CHECK_EVENT_TYPE
        for entry in loaded.get_event_trace()
    )
