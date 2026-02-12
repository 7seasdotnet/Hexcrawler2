from hexcrawler.content.io import load_world_json
from hexcrawler.sim.core import EntityState, Simulation
from hexcrawler.sim.hash import simulation_hash
from hexcrawler.sim.world import HexCoord


def _build_sim(seed: int) -> Simulation:
    world = load_world_json("content/examples/basic_map.json")
    sim = Simulation(world=world, seed=seed)
    sim.add_entity(EntityState.from_hex(entity_id="runner", hex_coord=HexCoord(0, 0), speed_per_tick=0.17))
    return sim


def _run_scripted_commands(sim: Simulation) -> None:
    sim.set_entity_move_vector("runner", 1.0, 1.0)
    sim.advance_ticks(8)
    sim.set_entity_move_vector("runner", 0.0, 0.0)
    sim.set_entity_destination("runner", HexCoord(1, -1))
    sim.advance_ticks(10)
    sim.advance_days(1)


def test_deterministic_seed_and_commands_produce_identical_hash() -> None:
    sim_a = _build_sim(seed=42)
    sim_b = _build_sim(seed=42)

    _run_scripted_commands(sim_a)
    _run_scripted_commands(sim_b)

    assert simulation_hash(sim_a) == simulation_hash(sim_b)
