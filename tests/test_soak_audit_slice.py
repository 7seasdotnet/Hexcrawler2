from __future__ import annotations

from hexcrawler.cli.pygame_viewer import (
    DebugFilterState,
    DebugPanelRenderCache,
    RumorPanelState,
    _build_viewer_simulation,
    build_debug_panel_render_cache,
    collect_soak_metrics,
)
from hexcrawler.content.io import load_world_json
from hexcrawler.sim.core import Simulation
from hexcrawler.sim.world import MAX_SIGNALS, MAX_SPAWN_DESCRIPTORS, MAX_TRACKS


def _saturate_world_records(sim: Simulation) -> None:
    for index in range(MAX_SIGNALS + 64):
        sim.state.world.upsert_signal({"signal_uid": f"sig:{index}", "template_id": "signal.test", "location": {"space_id": "overworld", "topology_type": "overworld_hex", "coord": {"q": 0, "r": 0}}, "created_tick": index, "params": {}})
    for index in range(MAX_TRACKS + 64):
        sim.state.world.upsert_track({"track_uid": f"trk:{index}", "template_id": "track.test", "location": {"space_id": "overworld", "topology_type": "overworld_hex", "coord": {"q": 0, "r": 0}}, "created_tick": index, "params": {}})
    for index in range(MAX_SPAWN_DESCRIPTORS + 64):
        sim.state.world.append_spawn_descriptor({"action_uid": f"spawn:{index}", "template_id": "spawn.test", "location": {"space_id": "overworld", "topology_type": "overworld_hex", "coord": {"q": 0, "r": 0}}, "quantity": 1, "created_tick": index, "params": {}})


def test_collect_soak_metrics_stays_bounded_headless_after_tick_run() -> None:
    sim = Simulation(world=load_world_json("content/examples/basic_map.json"), seed=331)
    _saturate_world_records(sim)
    sim.advance_ticks(1500)

    metrics = collect_soak_metrics(sim)

    assert metrics["signals"] == MAX_SIGNALS
    assert metrics["tracks"] == MAX_TRACKS
    assert metrics["spawn_descriptors"] == MAX_SPAWN_DESCRIPTORS
    assert metrics["pending_events"] >= 0
    assert metrics["event_trace"] >= 0


def test_collect_soak_metrics_viewer_path_matches_bounded_headless_counts() -> None:
    headless = Simulation(world=load_world_json("content/examples/basic_map.json"), seed=332)
    viewer = _build_viewer_simulation("content/examples/basic_map.json", with_encounters=True)

    _saturate_world_records(headless)
    _saturate_world_records(viewer)

    headless.advance_ticks(120)
    viewer.advance_ticks(120)

    for _ in range(6):
        build_debug_panel_render_cache(
            viewer,
            rumor_state=RumorPanelState(),
            debug_filter_state=DebugFilterState(),
            cache=DebugPanelRenderCache(),
        )

    headless_metrics = collect_soak_metrics(headless)
    viewer_metrics = collect_soak_metrics(viewer)

    assert headless_metrics["signals"] == viewer_metrics["signals"] == MAX_SIGNALS
    assert headless_metrics["tracks"] == viewer_metrics["tracks"] == MAX_TRACKS
    assert headless_metrics["spawn_descriptors"] == viewer_metrics["spawn_descriptors"] == MAX_SPAWN_DESCRIPTORS
