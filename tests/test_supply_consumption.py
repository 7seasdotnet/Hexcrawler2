from __future__ import annotations

from pathlib import Path

from hexcrawler.content.io import load_game_json, load_world_json, save_game_json
from hexcrawler.sim.core import EntityState, Simulation
from hexcrawler.sim.hash import simulation_hash
from hexcrawler.sim.supplies import SUPPLY_OUTCOME_EVENT_TYPE, SupplyConsumptionModule
from hexcrawler.sim.world import HexCoord


def _make_sim(seed: int = 5) -> Simulation:
    sim = Simulation(world=load_world_json("content/examples/basic_map.json"), seed=seed)
    sim.add_entity(EntityState.from_hex(entity_id="scout", hex_coord=HexCoord(0, 0)))
    inv = sim.state.entities["scout"].inventory_container_id
    assert inv is not None
    sim.state.world.containers[inv].items.update({"rations": 4, "water": 4, "torch": 4})
    sim.register_rule_module(SupplyConsumptionModule())
    return sim


def _supply_outcomes(sim: Simulation) -> list[dict[str, object]]:
    return [entry for entry in sim.get_event_trace() if entry.get("event_type") == SUPPLY_OUTCOME_EVENT_TYPE]


def test_supply_consumption_determinism_same_seed_same_hash() -> None:
    def run_once() -> str:
        sim = _make_sim(seed=41)
        sim.advance_ticks(180)
        return simulation_hash(sim)

    assert run_once() == run_once()


def test_supply_consumption_save_load_stable_without_double_consume(tmp_path: Path) -> None:
    sim = _make_sim(seed=99)
    sim.advance_ticks(90)
    save_path = tmp_path / "supply_save.json"
    save_game_json(save_path, sim.state.world, sim)

    _, loaded = load_game_json(save_path)
    loaded.register_rule_module(SupplyConsumptionModule())

    sim.advance_ticks(90)
    loaded.advance_ticks(90)

    assert simulation_hash(sim) == simulation_hash(loaded)


def test_supply_consumption_never_goes_negative() -> None:
    sim = _make_sim()
    inv = sim.state.entities["scout"].inventory_container_id
    assert inv is not None
    sim.state.world.containers[inv].items["water"] = 0

    sim.advance_ticks(120)

    assert sim.state.world.containers[inv].items.get("water", 0) >= 0


def test_supply_insufficient_emits_outcome_and_preserves_inventory() -> None:
    sim = _make_sim()
    inv = sim.state.entities["scout"].inventory_container_id
    assert inv is not None
    sim.state.world.containers[inv].items["water"] = 0

    before = dict(sim.state.world.containers[inv].items)
    sim.advance_ticks(61)
    after = dict(sim.state.world.containers[inv].items)

    outcomes = _supply_outcomes(sim)
    assert outcomes
    assert any(entry["params"]["outcome"] == "insufficient_supply" for entry in outcomes)
    assert before == after or (before.keys() == after.keys() and after.get("water", 0) == 0)


def test_supply_scheduler_does_not_duplicate_chains_after_load(tmp_path: Path) -> None:
    sim = _make_sim()
    initial_tasks = [
        event
        for event in sim.pending_events()
        if event.event_type == "periodic_tick" and str(event.params.get("task", "")).startswith("supply.consume:")
    ]
    assert len(initial_tasks) == 3

    save_path = tmp_path / "periodic_supply_save.json"
    save_game_json(save_path, sim.state.world, sim)
    _, loaded = load_game_json(save_path)
    loaded.register_rule_module(SupplyConsumptionModule())

    loaded_tasks = [
        event
        for event in loaded.pending_events()
        if event.event_type == "periodic_tick" and str(event.params.get("task", "")).startswith("supply.consume:")
    ]
    assert len(loaded_tasks) == 3
