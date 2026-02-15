from pathlib import Path

from hexcrawler.content.io import load_game_json, load_world_json, save_game_json
from hexcrawler.sim.core import MAX_EVENT_TRACE, Simulation
from hexcrawler.sim.hash import simulation_hash


def _build_sim(seed: int) -> Simulation:
    world = load_world_json("content/examples/basic_map.json")
    return Simulation(world=world, seed=seed)


def test_event_trace_records_execution() -> None:
    sim = _build_sim(seed=11)

    first_id = sim.schedule_event_at(1, "debug_marker", {"label": "a"})
    second_id = sim.schedule_event_at(1, "noop", {"label": "b"})
    sim.schedule_event_at(4, "debug_marker", {"label": "future"})

    sim.advance_ticks(3)

    assert sim.get_event_trace() == [
        {
            "tick": 1,
            "event_id": int(first_id[4:]),
            "event_type": "debug_marker",
            "params": {"label": "a"},
            "module_hooks_called": False,
        },
        {
            "tick": 1,
            "event_id": int(second_id[4:]),
            "event_type": "noop",
            "params": {"label": "b"},
            "module_hooks_called": False,
        },
    ]


def test_event_trace_bounded_eviction() -> None:
    sim = _build_sim(seed=12)

    for index in range(MAX_EVENT_TRACE + 44):
        sim.schedule_event_at(0, "noop", {"index": index})

    sim.advance_ticks(1)

    trace = sim.get_event_trace()
    assert len(trace) == MAX_EVENT_TRACE
    assert trace[0]["event_id"] == 45
    assert trace[-1]["event_id"] == MAX_EVENT_TRACE + 44


def test_event_trace_in_hash() -> None:
    sim = _build_sim(seed=13)
    initial_hash = simulation_hash(sim)

    sim.schedule_event_at(0, "debug_marker", {"marker": "x"})
    sim.advance_ticks(1)

    assert simulation_hash(sim) != initial_hash


def test_event_trace_round_trip_save_load(tmp_path: Path) -> None:
    sim = _build_sim(seed=14)
    sim.schedule_event_at(0, "noop", {"v": 1})
    sim.schedule_event_at(1, "debug_marker", {"v": 2})
    sim.advance_ticks(2)

    save_path = tmp_path / "event_trace_save.json"
    save_game_json(save_path, sim.state.world, sim)

    _, loaded = load_game_json(save_path)

    assert loaded.get_event_trace() == sim.get_event_trace()
    assert simulation_hash(loaded) == simulation_hash(sim)


def test_event_trace_replay_stability() -> None:
    sim_a = _build_sim(seed=15)
    sim_b = _build_sim(seed=15)

    for sim in (sim_a, sim_b):
        sim.schedule_event_at(1, "noop", {"n": 1})
        sim.schedule_event_at(3, "debug_marker", {"n": 2})
        sim.schedule_event_at(5, "noop", {"n": 3})
        sim.advance_ticks(8)

    assert simulation_hash(sim_a) == simulation_hash(sim_b)
    assert sim_a.get_event_trace() == sim_b.get_event_trace()
