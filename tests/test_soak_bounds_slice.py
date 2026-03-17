from __future__ import annotations

from hexcrawler.cli.pygame_viewer import (
    DebugFilterState,
    DebugPanelRenderCache,
    PANEL_SECTION_ENTRY_LIMIT,
    RumorPanelState,
    build_debug_panel_render_cache,
)
from hexcrawler.content.io import load_world_json
from hexcrawler.sim.core import Simulation
from hexcrawler.sim.world import MAX_SIGNALS, MAX_SPAWN_DESCRIPTORS, MAX_TRACKS, WorldState


def test_long_run_world_records_remain_bounded_for_headless_simulation() -> None:
    sim = Simulation(world=load_world_json("content/examples/basic_map.json"), seed=121)

    for index in range(MAX_SIGNALS + 40):
        sim.state.world.upsert_signal(
            {
                "signal_uid": f"sig:{index}",
                "template_id": "signal.test",
                "location": {"space_id": "overworld", "topology_type": "overworld_hex", "coord": {"q": 0, "r": 0}},
                "created_tick": index,
                "params": {},
            }
        )
    for index in range(MAX_TRACKS + 40):
        sim.state.world.upsert_track(
            {
                "track_uid": f"trk:{index}",
                "template_id": "track.test",
                "location": {"space_id": "overworld", "topology_type": "overworld_hex", "coord": {"q": 0, "r": 0}},
                "created_tick": index,
                "params": {},
            }
        )
    for index in range(MAX_SPAWN_DESCRIPTORS + 40):
        sim.state.world.append_spawn_descriptor(
            {
                "action_uid": f"spawn:{index}",
                "template_id": "spawn.test",
                "location": {"space_id": "overworld", "topology_type": "overworld_hex", "coord": {"q": 0, "r": 0}},
                "quantity": 1,
                "created_tick": index,
            }
        )

    assert len(sim.state.world.signals) == MAX_SIGNALS
    assert len(sim.state.world.tracks) == MAX_TRACKS
    assert len(sim.state.world.spawn_descriptors) == MAX_SPAWN_DESCRIPTORS


def test_world_load_truncates_legacy_oversized_track_and_spawn_lists() -> None:
    payload = load_world_json("content/examples/basic_map.json").to_dict()
    payload["tracks"] = [{"track_uid": f"trk:{index}"} for index in range(MAX_TRACKS + 20)]
    payload["spawn_descriptors"] = [{"action_uid": f"spawn:{index}"} for index in range(MAX_SPAWN_DESCRIPTORS + 20)]

    restored = WorldState.from_dict(payload)

    assert len(restored.tracks) == MAX_TRACKS
    assert len(restored.spawn_descriptors) == MAX_SPAWN_DESCRIPTORS


def test_viewer_debug_rows_stay_bounded_after_long_run_record_accumulation() -> None:
    sim = Simulation(world=load_world_json("content/examples/basic_map.json"), seed=122)
    for index in range(MAX_SIGNALS + MAX_TRACKS + MAX_SPAWN_DESCRIPTORS):
        sim.state.world.upsert_signal({"signal_uid": f"sig:{index}"})
        sim.state.world.upsert_track({"track_uid": f"trk:{index}"})
        sim.state.world.append_spawn_descriptor({"action_uid": f"spawn:{index}"})

    rows = build_debug_panel_render_cache(
        sim,
        rumor_state=RumorPanelState(),
        debug_filter_state=DebugFilterState(),
        cache=DebugPanelRenderCache(),
    )

    assert len(rows["encounters"]) <= PANEL_SECTION_ENTRY_LIMIT
