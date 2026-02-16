import pytest
from pathlib import Path

from hexcrawler.content.io import load_game_json, load_world_json, save_game_json
from hexcrawler.sim.core import MAX_EVENTS_PER_TICK, Simulation
from hexcrawler.sim.hash import simulation_hash

from hexcrawler.sim.rules import RuleModule


class _SameTickScheduler(RuleModule):
    name = "same_tick_scheduler"

    def on_event_executed(self, sim: Simulation, event) -> None:
        if event.event_type == "first":
            sim.schedule_event_at(sim.state.tick, "second", {"via": "module"})


class _InfiniteSameTickScheduler(RuleModule):
    name = "infinite_same_tick_scheduler"

    def on_event_executed(self, sim: Simulation, event) -> None:
        sim.schedule_event_at(sim.state.tick, "loop", {"source": event.event_id})

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


def test_same_tick_event_scheduled_during_execution_is_drained() -> None:
    sim = _build_sim(seed=101)
    sim.register_rule_module(_SameTickScheduler())

    first_event_id = sim.schedule_event_at(0, "first", {})
    sim.advance_ticks(1)

    trace_event_ids = [entry["event_id"] for entry in sim.get_event_trace()]
    assert trace_event_ids[0] == int(first_event_id.split("-")[1])
    trace_types = [entry["event_type"] for entry in sim.get_event_trace()]
    assert trace_types == ["first", "second"]


def test_same_tick_event_guard_fails_deterministically() -> None:
    sim = _build_sim(seed=202)
    sim.register_rule_module(_InfiniteSameTickScheduler())

    sim.schedule_event_at(0, "loop", {})

    with pytest.raises(RuntimeError, match="MAX_EVENTS_PER_TICK"):
        sim.advance_ticks(1)

    assert len(sim.get_event_trace()) == min(MAX_EVENTS_PER_TICK, 256)
