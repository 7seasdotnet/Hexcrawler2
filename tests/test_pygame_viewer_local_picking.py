from hexcrawler.cli.pygame_viewer import _world_to_local_cell
from hexcrawler.sim.location import SQUARE_GRID_TOPOLOGY
from hexcrawler.sim.world import LOCAL_SPACE_ROLE, SpaceState


def _local_space() -> SpaceState:
    return SpaceState(
        space_id='local:test',
        topology_type=SQUARE_GRID_TOPOLOGY,
        role=LOCAL_SPACE_ROLE,
        topology_params={'width': 10, 'height': 10, 'origin': {'x': 0, 'y': 0}},
    )


def test_world_to_local_cell_accepts_all_valid_regions() -> None:
    local_space = _local_space()

    assert _world_to_local_cell(0.0, 0.01, active_space=local_space) == {'x': 0, 'y': 0}
    assert _world_to_local_cell(9.99, 0.05, active_space=local_space) == {'x': 9, 'y': 0}
    assert _world_to_local_cell(1.05, 8.95, active_space=local_space) == {'x': 1, 'y': 8}


def test_world_to_local_cell_rejects_out_of_bounds() -> None:
    local_space = _local_space()

    assert _world_to_local_cell(-0.1, 0.0, active_space=local_space) is None
    assert _world_to_local_cell(0.0, -0.1, active_space=local_space) is None
    assert _world_to_local_cell(10.0, 5.0, active_space=local_space) is None
    assert _world_to_local_cell(5.0, 10.0, active_space=local_space) is None
