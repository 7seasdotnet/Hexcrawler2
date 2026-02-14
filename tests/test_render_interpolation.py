from hexcrawler.cli.pygame_viewer import (
    RenderEntitySnapshot,
    clamp01,
    extract_render_snapshot,
    interpolate_entity_position,
    lerp,
)
from hexcrawler.content.io import load_world_json
from hexcrawler.sim.core import EntityState, Simulation
from hexcrawler.sim.world import HexCoord


def test_clamp01_and_lerp() -> None:
    assert clamp01(-0.5) == 0.0
    assert clamp01(0.25) == 0.25
    assert clamp01(1.5) == 1.0
    assert lerp(2.0, 10.0, 0.25) == 4.0


def test_extract_render_snapshot_is_immutable_copy_of_positions() -> None:
    world = load_world_json("content/examples/basic_map.json")
    sim = Simulation(world=world, seed=3)
    sim.add_entity(EntityState.from_hex(entity_id="runner", hex_coord=HexCoord(0, 0), speed_per_tick=0.2))

    snapshot = extract_render_snapshot(sim)
    assert snapshot["runner"].x == 0.0
    assert snapshot["runner"].y == 0.0

    sim.set_entity_move_vector("runner", 1.0, 0.0)
    sim.advance_ticks(1)

    # Existing snapshots must not be mutated by later simulation ticks.
    assert snapshot["runner"].x == 0.0
    assert snapshot["runner"].y == 0.0


def test_interpolate_entity_position_missing_entity_cases() -> None:
    prev_snapshot = {"runner": RenderEntitySnapshot(x=0.0, y=0.0)}
    curr_snapshot = {"runner": RenderEntitySnapshot(x=1.0, y=1.0)}

    assert interpolate_entity_position(prev_snapshot, curr_snapshot, "runner", 0.5) == (0.5, 0.5)
    assert interpolate_entity_position({}, curr_snapshot, "runner", 0.5) == (1.0, 1.0)
    assert interpolate_entity_position(prev_snapshot, {}, "runner", 0.5) == (0.0, 0.0)
    assert interpolate_entity_position({}, {}, "runner", 0.5) is None
