from pathlib import Path

from hexcrawler.content.io import load_game_json, load_world_json, save_game_json
from hexcrawler.sim.core import Simulation
from hexcrawler.sim.periodic import PeriodicScheduler


def _build_sim(seed: int = 123) -> Simulation:
    world = load_world_json("content/examples/basic_map.json")
    return Simulation(world=world, seed=seed)


def test_periodic_fires_expected_ticks() -> None:
    sim = _build_sim(seed=1)
    scheduler = PeriodicScheduler()
    observed_ticks: list[int] = []

    scheduler.register_task(task_name="t", interval_ticks=2, start_tick=0)
    scheduler.set_task_callback("t", lambda _sim, tick: observed_ticks.append(tick))
    sim.register_rule_module(scheduler)

    sim.advance_ticks(7)

    assert observed_ticks == [0, 2, 4, 6]


def test_periodic_persistence_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "save.json"

    sim = _build_sim(seed=2)
    scheduler = PeriodicScheduler()
    observed_before: list[int] = []
    observed_after: list[int] = []

    scheduler.register_task(task_name="t", interval_ticks=3, start_tick=0)
    scheduler.set_task_callback("t", lambda _sim, tick: observed_before.append(tick))
    sim.register_rule_module(scheduler)

    sim.advance_ticks(5)
    assert observed_before == [0, 3]

    save_game_json(path, sim.state.world, sim)
    _, loaded_sim = load_game_json(path)

    loaded_scheduler = PeriodicScheduler()
    loaded_sim.register_rule_module(loaded_scheduler)
    loaded_scheduler.set_task_callback("t", lambda _sim, tick: observed_after.append(tick))

    loaded_sim.advance_ticks(6)

    assert observed_after == [6, 9]


def test_periodic_ordering_same_tick() -> None:
    sim = _build_sim(seed=3)
    scheduler = PeriodicScheduler()
    observed: list[tuple[str, int]] = []

    scheduler.register_task(task_name="A", interval_ticks=5, start_tick=0)
    scheduler.register_task(task_name="B", interval_ticks=5, start_tick=0)
    scheduler.set_task_callback("A", lambda _sim, tick: observed.append(("A", tick)))
    scheduler.set_task_callback("B", lambda _sim, tick: observed.append(("B", tick)))
    sim.register_rule_module(scheduler)

    sim.advance_ticks(1)

    assert observed == [("A", 0), ("B", 0)]


def test_duplicate_task_rejected() -> None:
    scheduler = PeriodicScheduler()

    scheduler.register_task(task_name="t", interval_ticks=2, start_tick=0)

    try:
        scheduler.register_task(task_name="t", interval_ticks=2, start_tick=0)
        assert False, "expected duplicate task registration to fail"
    except ValueError:
        pass
