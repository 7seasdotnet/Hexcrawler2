from hexcrawler.content.io import load_world_json
from hexcrawler.sim.core import Simulation
from hexcrawler.sim.hash import simulation_hash
from hexcrawler.sim.rng import derive_stream_seed


def test_derived_stream_seed_is_stable_for_same_master_seed() -> None:
    seed_a = derive_stream_seed(master_seed=12345, stream_name="rng_sim")
    seed_b = derive_stream_seed(master_seed=12345, stream_name="rng_sim")

    assert seed_a == seed_b


def test_derived_stream_seed_changes_with_stream_name() -> None:
    sim_seed = derive_stream_seed(master_seed=12345, stream_name="rng_sim")
    worldgen_seed = derive_stream_seed(master_seed=12345, stream_name="rng_worldgen")

    assert sim_seed != worldgen_seed


def test_worldgen_draws_do_not_perturb_sim_stream() -> None:
    world = load_world_json("content/examples/basic_map.json")

    sim_a = Simulation(world=world, seed=987)
    sim_b = Simulation(world=world, seed=987)

    values_before = [sim_a.rng_sim.random() for _ in range(3)]

    for _ in range(100):
        sim_b.rng_worldgen.random()

    values_after = [sim_b.rng_sim.random() for _ in range(3)]

    assert values_before == values_after


def test_named_rng_stream_state_round_trips_through_save_payload() -> None:
    world = load_world_json("content/examples/basic_map.json")
    sim = Simulation(world=world, seed=222)

    bandit_stream = sim.rng_stream("bandit_ai")
    _ = [bandit_stream.random() for _ in range(5)]

    reloaded = Simulation.from_simulation_payload(sim.simulation_payload())
    reloaded_bandit_stream = reloaded.rng_stream("bandit_ai")

    assert reloaded_bandit_stream.random() == bandit_stream.random()
    assert simulation_hash(reloaded) == simulation_hash(sim)
