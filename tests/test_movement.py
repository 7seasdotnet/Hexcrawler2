from hexcrawler.content.io import load_world_json
from hexcrawler.sim.core import EntityState, Simulation
from hexcrawler.sim.world import HexCoord


def test_derived_hex_tracks_continuous_position() -> None:
    world = load_world_json("content/examples/basic_map.json")
    sim = Simulation(world=world, seed=1)
    sim.add_entity(EntityState.from_hex(entity_id="runner", hex_coord=HexCoord(0, 0), speed_per_tick=0.2))

    sim.set_entity_destination("runner", HexCoord(1, -1))
    sim.advance_ticks(20)

    entity = sim.state.entities["runner"]
    assert entity.hex_coord == HexCoord(1, -1)
    assert entity.target_position is None


def test_world_bounds_block_movement_outside_defined_hexes() -> None:
    world = load_world_json("content/examples/basic_map.json")
    sim = Simulation(world=world, seed=1)
    sim.add_entity(EntityState.from_hex(entity_id="runner", hex_coord=HexCoord(0, 0), speed_per_tick=0.3))

    sim.set_entity_move_vector("runner", -1.0, 0.0)
    sim.advance_ticks(50)

    entity = sim.state.entities["runner"]
    assert sim.state.world.get_hex_record(entity.hex_coord) is not None


def test_target_outside_world_is_ignored() -> None:
    world = load_world_json("content/examples/basic_map.json")
    sim = Simulation(world=world, seed=1)
    sim.add_entity(EntityState.from_hex(entity_id="runner", hex_coord=HexCoord(0, 0), speed_per_tick=0.2))

    sim.set_entity_destination("runner", HexCoord(-1, 0))
    sim.advance_ticks(10)

    entity = sim.state.entities["runner"]
    assert entity.target_position is None
    assert entity.hex_coord == HexCoord(0, 0)
