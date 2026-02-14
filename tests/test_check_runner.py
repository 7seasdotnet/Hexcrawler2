from pathlib import Path

from hexcrawler.content.io import load_game_json, load_world_json, save_game_json
from hexcrawler.sim.checks import CHECK_EVENT_TYPE, CheckRunner
from hexcrawler.sim.core import SimCommand, SimEvent, Simulation
from hexcrawler.sim.hash import simulation_hash
from hexcrawler.sim.periodic import PERIODIC_EVENT_TYPE
from hexcrawler.sim.rules import RuleModule


class CheckEventRecorder(RuleModule):
    def __init__(self, out: list[tuple[str, int, str]]) -> None:
        self.name = "check_event_recorder"
        self.out = out

    def on_event_executed(self, sim: Simulation, event: SimEvent) -> None:
        if event.event_type != CHECK_EVENT_TYPE:
            return
        self.out.append((str(event.params["check"]), event.tick, str(event.params["source_task"])))


def _build_sim(seed: int = 123) -> Simulation:
    world = load_world_json("content/examples/basic_map.json")
    return Simulation(world=world, seed=seed)


def test_check_runner_emits_events_on_schedule() -> None:
    sim = _build_sim(seed=1)
    observed: list[tuple[str, int, str]] = []

    runner = CheckRunner()
    runner.register_check(check_name="alpha", interval_ticks=2, start_tick=0)
    runner.register_check(check_name="beta", interval_ticks=3, start_tick=1)

    sim.register_rule_module(runner)
    sim.register_rule_module(CheckEventRecorder(observed))

    sim.advance_ticks(7)

    assert observed == [
        ("alpha", 1, "check:alpha"),
        ("beta", 2, "check:beta"),
        ("alpha", 3, "check:alpha"),
        ("beta", 5, "check:beta"),
        ("alpha", 5, "check:alpha"),
    ]


def test_check_runner_same_tick_ordering_is_deterministic() -> None:
    sim = _build_sim(seed=2)
    observed: list[tuple[str, int, str]] = []

    runner = CheckRunner()
    runner.register_check(check_name="A", interval_ticks=4, start_tick=0)
    runner.register_check(check_name="B", interval_ticks=4, start_tick=0)

    sim.register_rule_module(runner)
    sim.register_rule_module(CheckEventRecorder(observed))

    sim.advance_ticks(2)

    assert observed == [
        ("A", 1, "check:A"),
        ("B", 1, "check:B"),
    ]


def test_check_runner_save_load_rehydrate_no_duplicates(tmp_path: Path) -> None:
    path = tmp_path / "check_runner_save.json"

    sim = _build_sim(seed=3)
    before: list[tuple[str, int, str]] = []
    runner = CheckRunner()
    runner.register_check(check_name="heartbeat", interval_ticks=4, start_tick=0)
    sim.register_rule_module(runner)
    sim.register_rule_module(CheckEventRecorder(before))

    sim.advance_ticks(9)
    assert before == [
        ("heartbeat", 1, "check:heartbeat"),
        ("heartbeat", 5, "check:heartbeat"),
    ]

    save_game_json(path, sim.state.world, sim)
    _, loaded_sim = load_game_json(path)

    after: list[tuple[str, int, str]] = []
    loaded_runner = CheckRunner()
    loaded_runner.register_check(check_name="heartbeat", interval_ticks=4, start_tick=0)
    loaded_runner.set_check_callback("heartbeat", lambda _sim, tick: {"tick": tick})
    loaded_sim.register_rule_module(loaded_runner)
    loaded_sim.register_rule_module(CheckEventRecorder(after))

    for _ in range(10):
        pending_heartbeat = [
            event
            for event in loaded_sim.pending_events()
            if event.event_type == PERIODIC_EVENT_TYPE and event.params.get("task") == "check:heartbeat"
        ]
        assert len(pending_heartbeat) <= 1
        loaded_sim.advance_ticks(1)

    assert after == [
        ("heartbeat", 9, "check:heartbeat"),
        ("heartbeat", 13, "check:heartbeat"),
        ("heartbeat", 17, "check:heartbeat"),
    ]


def test_check_runner_replay_hash_stability() -> None:
    sim_a = _build_sim(seed=999)
    sim_b = _build_sim(seed=999)

    for sim in (sim_a, sim_b):
        runner = CheckRunner()
        runner.register_check(check_name="clock", interval_ticks=3, start_tick=0)
        runner.set_check_callback("clock", lambda _sim, tick: {"phase": tick % 3})
        sim.register_rule_module(runner)
        sim.append_command(SimCommand(tick=2, command_type="noop_input", params={"value": 1}))

    sim_a.advance_ticks(20)
    sim_b.advance_ticks(20)

    assert simulation_hash(sim_a) == simulation_hash(sim_b)
