from pathlib import Path

from hexcrawler.content.io import load_game_json, load_world_json, save_game_json
from hexcrawler.sim.core import Simulation
from hexcrawler.sim.hash import simulation_hash


def _build_sim(seed: int) -> Simulation:
    world = load_world_json("content/examples/basic_map.json")
    return Simulation(world=world, seed=seed)


def _schedule_standard_events(sim: Simulation) -> None:
    sim.schedule_event_at(2, "noop", {"label": "first"})
    sim.schedule_event_at(2, "debug_marker", {"label": "second"})
    sim.schedule_event_at(4, "noop", {"label": "third"})
    sim.schedule_event_at(2, "noop", {"label": "fourth"})


def test_event_queue_determinism() -> None:
    sim_a = _build_sim(seed=777)
    sim_b = _build_sim(seed=777)

    _schedule_standard_events(sim_a)
    _schedule_standard_events(sim_b)

    sim_a.advance_ticks(6)
    sim_b.advance_ticks(6)

    assert sim_a.event_execution_trace() == sim_b.event_execution_trace()
    assert simulation_hash(sim_a) == simulation_hash(sim_b)


def test_event_queue_persistence(tmp_path: Path) -> None:
    sim_a = _build_sim(seed=991)
    sim_b = _build_sim(seed=991)
    _schedule_standard_events(sim_a)
    _schedule_standard_events(sim_b)

    save_path = tmp_path / "event_queue_save.json"
    save_game_json(save_path, sim_a.state.world, sim_a)

    _, loaded = load_game_json(save_path)
    loaded.advance_ticks(5)
    sim_b.advance_ticks(5)

    assert [event.to_dict() for event in loaded.pending_events()] == [
        event.to_dict() for event in sim_b.pending_events()
    ]
    assert loaded.event_execution_trace() == sim_b.event_execution_trace()
    assert simulation_hash(loaded) == simulation_hash(sim_b)


def test_ordering_same_tick() -> None:
    sim = _build_sim(seed=55)

    first = sim.schedule_event_at(3, "debug_marker", {"order": 1})
    second = sim.schedule_event_at(3, "debug_marker", {"order": 2})
    third = sim.schedule_event_at(3, "debug_marker", {"order": 3})

    sim.advance_ticks(4)

    assert sim.event_execution_trace() == (first, second, third)
