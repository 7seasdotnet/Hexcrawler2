from hexcrawler.sim.hash import world_hash
from hexcrawler.sim.world import HexCoord, WorldState


def test_same_seed_and_disk_topology_produce_identical_world_hash() -> None:
    world_a = WorldState.create_with_topology(
        master_seed=42,
        topology_type="hex_disk",
        topology_params={"radius": 4},
    )
    world_b = WorldState.create_with_topology(
        master_seed=42,
        topology_type="hex_disk",
        topology_params={"radius": 4},
    )

    assert world_hash(world_a) == world_hash(world_b)


def test_different_seed_changes_disk_world_hash() -> None:
    world_a = WorldState.create_with_topology(
        master_seed=42,
        topology_type="hex_disk",
        topology_params={"radius": 4},
    )
    world_b = WorldState.create_with_topology(
        master_seed=99,
        topology_type="hex_disk",
        topology_params={"radius": 4},
    )

    assert world_hash(world_a) != world_hash(world_b)


def test_rectangle_generation_is_consistent_and_bounded() -> None:
    width = 3
    height = 2
    world = WorldState.create_with_topology(
        master_seed=7,
        topology_type="hex_rectangle",
        topology_params={"width": width, "height": height},
    )

    assert len(world.hexes) == width * height

    expected_coords = {(q, r) for q in range(width) for r in range(height)}
    generated_coords = {(coord.q, coord.r) for coord in world.hexes}
    assert generated_coords == expected_coords


def test_world_membership_enforces_disk_bounds() -> None:
    radius = 2
    world = WorldState.create_with_topology(
        master_seed=5,
        topology_type="hex_disk",
        topology_params={"radius": radius},
    )

    assert world.get_hex_record(HexCoord(0, 0)) is not None
    assert world.get_hex_record(HexCoord(radius + 1, 0)) is None
