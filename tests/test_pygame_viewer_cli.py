from pathlib import Path

import hexcrawler.cli.pygame_viewer as viewer_module
import pytest

from hexcrawler.cli.pygame_viewer import (
    PLAYER_ID,
    DebugFilterState,
    RumorPanelState,
    SimulationController,
    ViewerRuntimeController,
    ViewerRuntimeState,
    _consume_rumor_outcome,
    _refresh_rumor_query,
    _build_parser,
    _build_viewer_simulation,
    MarkerPlacement,
    MarkerRecord,
    _find_entity_at_pixel,
    _find_world_marker_at_pixel,
    _find_world_marker_candidates_at_pixel,
    _marker_cell_from_location,
    _marker_payload_id,
    _slot_markers_for_hex,
    _load_viewer_simulation,
    _save_viewer_simulation,
    _queue_selection_command_for_click,
    _selected_entity_for_click,
    _selected_entity_lines,
    _selected_entity_recent_trace_rows,
    _supported_viewer_topology,
    _viewer_topology_diagnostic,
    _world_marker_placements,
    _event_trace_entry_mentions_entity,
    _build_debug_filter_trace_rows,
    _cycle_debug_event_type_filter,
    _cycle_debug_filter_mode,
    _debug_filter_label,
    _debug_rows_by_section,
    _format_debug_trace_row,
)
from hexcrawler.sim.core import EntityState
from hexcrawler.sim.encounters import (
    ENCOUNTER_ACTION_OUTCOME_EVENT_TYPE,
    EncounterActionExecutionModule,
    EncounterActionModule,
    EncounterCheckModule,
    EncounterSelectionModule,
    SELECT_RUMORS_INTENT,
    SpawnMaterializationModule,
)
from hexcrawler.sim.hash import simulation_hash, world_hash
from hexcrawler.sim.location import OVERWORLD_HEX_TOPOLOGY
from hexcrawler.sim.world import HexCoord, LOCAL_SPACE_ROLE, RumorRecord, SitePressureRecord, SiteRecord, SiteWorldState, SpaceState


def test_viewer_parser_with_encounters_flag_defaults_to_disabled() -> None:
    parser = _build_parser()
    args = parser.parse_args([])

    assert args.with_encounters is False
    assert args.map_path == "content/examples/viewer_map.json"
    assert args.save_path == "saves/session_save.json"
    assert args.load_save is None


def test_viewer_parser_with_encounters_flag_can_be_enabled() -> None:
    parser = _build_parser()
    args = parser.parse_args(["--with-encounters", "--save-path", "saves/dev.json", "--load-save", "saves/dev.json"])

    assert args.with_encounters is True
    assert args.save_path == "saves/dev.json"
    assert args.load_save == "saves/dev.json"


def test_viewer_simulation_registers_encounter_modules_only_when_enabled() -> None:
    neutral_sim = _build_viewer_simulation(
        "content/examples/basic_map.json",
        with_encounters=False,
    )
    enabled_sim = _build_viewer_simulation(
        "content/examples/basic_map.json",
        with_encounters=True,
    )

    assert neutral_sim.get_rule_module(EncounterCheckModule.name) is None
    assert neutral_sim.get_rule_module(EncounterSelectionModule.name) is None
    assert neutral_sim.get_rule_module(EncounterActionModule.name) is None
    assert neutral_sim.get_rule_module(EncounterActionExecutionModule.name) is None
    assert neutral_sim.get_rule_module(SpawnMaterializationModule.name) is None
    assert enabled_sim.get_rule_module(EncounterCheckModule.name) is not None
    assert enabled_sim.get_rule_module(EncounterSelectionModule.name) is not None
    assert enabled_sim.get_rule_module(EncounterActionModule.name) is not None
    assert enabled_sim.get_rule_module(EncounterActionExecutionModule.name) is not None
    assert enabled_sim.get_rule_module(SpawnMaterializationModule.name) is not None




def test_viewer_player_receives_default_supply_profile() -> None:
    sim = _build_viewer_simulation("content/examples/basic_map.json", with_encounters=False)

    assert sim.state.entities[PLAYER_ID].supply_profile_id == "player_default"

def test_simulation_controller_appends_move_vector_command() -> None:
    sim = _build_viewer_simulation("content/examples/basic_map.json", with_encounters=False)
    controller = SimulationController(sim=sim, entity_id=PLAYER_ID)

    controller.set_move_vector(1.0, -1.0)

    assert sim.input_log[-1].command_type == "set_move_vector"
    assert sim.input_log[-1].tick == sim.state.tick
    assert sim.input_log[-1].entity_id == PLAYER_ID
    assert sim.input_log[-1].params == {"x": 1.0, "y": -1.0}




def test_simulation_controller_appends_selection_commands() -> None:
    sim = _build_viewer_simulation("content/examples/basic_map.json", with_encounters=False)
    controller = SimulationController(sim=sim, entity_id=PLAYER_ID)

    controller.set_selected_entity(PLAYER_ID)
    controller.clear_selected_entity()

    assert sim.input_log[-2].command_type == "set_selected_entity"
    assert sim.input_log[-2].params == {"selected_entity_id": PLAYER_ID}
    assert sim.input_log[-1].command_type == "clear_selected_entity"
    assert sim.input_log[-1].params == {}


def test_rumor_panel_queries_outcomes_without_mutating_world_hash() -> None:
    sim = _build_viewer_simulation("content/examples/basic_map.json", with_encounters=True)
    sim.state.world.append_rumor(RumorRecord(rumor_id="r-02", kind="site_claim", created_tick=3, group_id="beta", consumed=False))
    sim.state.world.append_rumor(RumorRecord(rumor_id="r-01", kind="group_arrival", created_tick=5, group_id="alpha", consumed=True))
    controller = SimulationController(sim=sim, entity_id=PLAYER_ID)
    rumor_state = RumorPanelState(limit=1)

    world_hash_before = world_hash(sim.state.world)
    rules_before = dict(sim.state.rules_state)
    rumors_before = list(sim.state.world.rumors)
    _refresh_rumor_query(controller, rumor_state)
    command = sim.input_log[-1]
    sim._execute_command(command, command_index=len(sim.input_log) - 1)
    _consume_rumor_outcome(sim, rumor_state)

    assert rumor_state.outcome == "ok"
    assert [row["rumor_id"] for row in rumor_state.rows] == ["r-01"]
    assert isinstance(rumor_state.next_cursor, str)
    assert world_hash(sim.state.world) == world_hash_before
    assert sim.state.world.rumors == rumors_before
    assert sim.state.rules_state == rules_before


def test_rumor_panel_cursor_uses_returned_next_cursor_deterministically() -> None:
    sim = _build_viewer_simulation("content/examples/basic_map.json", with_encounters=True)
    sim.state.world.append_rumor(RumorRecord(rumor_id="r-03", kind="site_claim", created_tick=1, group_id="c", consumed=False))
    sim.state.world.append_rumor(RumorRecord(rumor_id="r-02", kind="group_arrival", created_tick=2, group_id="b", consumed=False))
    sim.state.world.append_rumor(RumorRecord(rumor_id="r-01", kind="claim_opportunity", created_tick=3, group_id="a", consumed=False))
    controller = SimulationController(sim=sim, entity_id=PLAYER_ID)
    rumor_state = RumorPanelState(limit=2)

    _refresh_rumor_query(controller, rumor_state)
    sim.advance_ticks(1)
    _consume_rumor_outcome(sim, rumor_state)
    assert [row["rumor_id"] for row in rumor_state.rows] == ["r-01", "r-02"]
    assert isinstance(rumor_state.next_cursor, str)

    rumor_state.cursor_stack.append(rumor_state.cursor)
    rumor_state.cursor = rumor_state.next_cursor
    rumor_state.refresh_needed = True
    _refresh_rumor_query(controller, rumor_state)
    sim.advance_ticks(1)
    _consume_rumor_outcome(sim, rumor_state)

    assert [row["rumor_id"] for row in rumor_state.rows] == ["r-03"]


def test_rumor_panel_top_mode_issues_select_rumors_intent_with_seed_tag_top() -> None:
    sim = _build_viewer_simulation("content/examples/basic_map.json", with_encounters=True)
    controller = SimulationController(sim=sim, entity_id=PLAYER_ID)
    rumor_state = RumorPanelState(mode="top", top_k=20)

    _refresh_rumor_query(controller, rumor_state)

    command = sim.input_log[-1]
    assert command.command_type == SELECT_RUMORS_INTENT
    assert command.params["seed_tag"] == "top"
    assert command.params["k"] == 20


def test_rumor_panel_top_mode_query_only_changes_selection_decision_substrate() -> None:
    sim = _build_viewer_simulation("content/examples/basic_map.json", with_encounters=True)
    sim.state.world.append_rumor(RumorRecord(rumor_id="r-01", kind="group_arrival", created_tick=5, group_id="alpha", consumed=False))
    sim.state.world.append_rumor(RumorRecord(rumor_id="r-02", kind="claim_opportunity", created_tick=6, group_id="beta", consumed=False))
    controller = SimulationController(sim=sim, entity_id=PLAYER_ID)
    rumor_state = RumorPanelState(mode="top", top_k=1)

    rumors_before = list(sim.state.world.rumors)
    decision_order_before = list(sim.state.world.rumor_selection_decision_order)
    _refresh_rumor_query(controller, rumor_state)
    sim.advance_ticks(1)
    _consume_rumor_outcome(sim, rumor_state)

    assert rumor_state.outcome == "ok"
    assert sim.state.world.rumors == rumors_before
    assert len(sim.state.world.rumor_selection_decision_order) == len(decision_order_before) + 1


def test_rumor_panel_mode_toggle_restores_all_mode_list_query() -> None:
    sim = _build_viewer_simulation("content/examples/basic_map.json", with_encounters=True)
    controller = SimulationController(sim=sim, entity_id=PLAYER_ID)
    rumor_state = RumorPanelState(mode="top", top_k=10)

    _refresh_rumor_query(controller, rumor_state)
    assert sim.input_log[-1].command_type == SELECT_RUMORS_INTENT
    sim.advance_ticks(1)
    _consume_rumor_outcome(sim, rumor_state)

    rumor_state.mode = "all"
    rumor_state.refresh_needed = True
    _refresh_rumor_query(controller, rumor_state)
    assert sim.input_log[-1].command_type == "list_rumors_intent"


def test_rumor_panel_ignores_stale_outcome_when_newer_request_pending() -> None:
    sim = _build_viewer_simulation("content/examples/basic_map.json", with_encounters=True)
    sim.state.world.append_rumor(RumorRecord(rumor_id="r-02", kind="site_claim", created_tick=3, group_id="beta", consumed=False))
    sim.state.world.append_rumor(RumorRecord(rumor_id="r-01", kind="group_arrival", created_tick=5, group_id="alpha", consumed=False))
    controller = SimulationController(sim=sim, entity_id=PLAYER_ID)
    rumor_state = RumorPanelState(limit=1)

    _refresh_rumor_query(controller, rumor_state)
    stale_command = sim.input_log[-1]
    sim._execute_command(stale_command, command_index=0)

    rumor_state.kind_filter = "site_claim"
    rumor_state.refresh_needed = True
    rumor_state.request_pending = False
    _refresh_rumor_query(controller, rumor_state)

    _consume_rumor_outcome(sim, rumor_state)

    assert rumor_state.request_pending is True
    assert rumor_state.pending_action_uid == "0:1"


def test_rumor_panel_consumes_matching_pending_outcome_by_action_uid() -> None:
    sim = _build_viewer_simulation("content/examples/basic_map.json", with_encounters=True)
    sim.state.world.append_rumor(RumorRecord(rumor_id="r-02", kind="site_claim", created_tick=3, group_id="beta", consumed=False))
    sim.state.world.append_rumor(RumorRecord(rumor_id="r-01", kind="group_arrival", created_tick=5, group_id="alpha", consumed=False))
    controller = SimulationController(sim=sim, entity_id=PLAYER_ID)
    rumor_state = RumorPanelState(limit=1)

    _refresh_rumor_query(controller, rumor_state)
    stale_command = sim.input_log[-1]
    sim._execute_command(stale_command, command_index=0)

    rumor_state.kind_filter = "site_claim"
    rumor_state.refresh_needed = True
    rumor_state.request_pending = False
    _refresh_rumor_query(controller, rumor_state)
    current_command = sim.input_log[-1]
    sim._execute_command(current_command, command_index=1)

    _consume_rumor_outcome(sim, rumor_state)

    assert rumor_state.request_pending is False
    assert rumor_state.pending_action_uid is None
    assert [row.get("rumor_id") for row in rumor_state.rows] == ["r-02"]

def test_main_help_prints_usage_without_starting_viewer(capsys: pytest.CaptureFixture[str]) -> None:
    from hexcrawler.cli.pygame_viewer import main

    with pytest.raises(SystemExit) as result:
        main(["--help"])

    captured = capsys.readouterr()
    assert result.value.code == 0
    assert "usage:" in captured.out
    assert "--headless" in captured.out


def test_main_headless_mode_exits_cleanly_and_warns(capsys: pytest.CaptureFixture[str]) -> None:
    from hexcrawler.cli.pygame_viewer import main

    with pytest.raises(SystemExit) as result:
        main(["--headless"])

    captured = capsys.readouterr()
    assert result.value.code == 0
    assert "headless mode active" in captured.out


def test_viewer_save_load_round_trip_preserves_tick_log_hash_and_artifacts(tmp_path: Path) -> None:
    sim = _build_viewer_simulation("content/examples/basic_map.json", with_encounters=True)
    sim.advance_ticks(160)
    sim.state.world.upsert_signal(
        {
            "signal_uid": "sig-test",
            "created_tick": sim.state.tick,
            "template_id": "smoke_column",
            "location": {"topology_type": "hex", "coord": {"q": 1, "r": 0}},
            "expires_tick": sim.state.tick + 100,
        }
    )
    sim.state.world.upsert_track(
        {
            "track_uid": "trk-test",
            "created_tick": sim.state.tick,
            "template_id": "wolf_tracks",
            "location": {"topology_type": "hex", "coord": {"q": 1, "r": 1}},
            "expires_tick": sim.state.tick + 100,
        }
    )
    sim.schedule_event_at(
        sim.state.tick,
        ENCOUNTER_ACTION_OUTCOME_EVENT_TYPE,
        {
            "action_uid": "outcome-test",
            "action_type": "signal_intent",
            "outcome": "applied",
            "template_id": "smoke_column",
        },
    )
    sim.advance_ticks(1)

    save_path = tmp_path / "viewer_round_trip.json"
    _save_viewer_simulation(sim, str(save_path))
    loaded = _load_viewer_simulation(str(save_path), with_encounters=True)

    assert loaded.state.tick == sim.state.tick
    assert len(loaded.input_log) == len(sim.input_log)
    assert simulation_hash(loaded) == simulation_hash(sim)
    assert loaded.state.world.signals == sim.state.world.signals
    assert loaded.state.world.tracks == sim.state.world.tracks
    assert loaded.get_event_trace() == sim.get_event_trace()


def test_find_entity_at_pixel_uses_deterministic_tie_break() -> None:
    sim = _build_viewer_simulation("content/examples/basic_map.json", with_encounters=False)
    sim.add_entity(EntityState.from_hex(entity_id="alpha", hex_coord=HexCoord(0, 0)))
    sim.add_entity(EntityState.from_hex(entity_id="beta", hex_coord=HexCoord(0, 0)))

    hit = _find_entity_at_pixel(sim, (0, 0), (0.0, 0.0), radius_px=20.0)

    assert hit == "alpha"


def test_slot_markers_for_hex_is_deterministic_for_same_inputs() -> None:
    markers = [
        MarkerRecord(priority=0, marker_id="site:a", marker_kind="site", color=(1, 1, 1), radius=4, label="a"),
        MarkerRecord(priority=0, marker_id="site:b", marker_kind="site", color=(1, 1, 1), radius=4, label="b"),
        MarkerRecord(priority=0, marker_id="site:c", marker_kind="site", color=(1, 1, 1), radius=4, label="c"),
    ]
    cell = _marker_cell_from_location({"space_id": "overworld", "coord": {"q": 0, "r": 0}}, "overworld_hex")
    assert cell is not None

    first, overflow_first = _slot_markers_for_hex(100.0, 100.0, markers, cell)
    second, overflow_second = _slot_markers_for_hex(100.0, 100.0, markers, cell)

    assert overflow_first == 0
    assert overflow_second == 0
    assert [(placement.marker.marker_id, placement.x, placement.y) for placement in first] == [
        (placement.marker.marker_id, placement.x, placement.y) for placement in second
    ]


def test_slot_markers_for_hex_separates_markers_in_same_cell() -> None:
    markers = [
        MarkerRecord(priority=0, marker_id=f"site:{index:02d}", marker_kind="site", color=(1, 1, 1), radius=4, label=str(index))
        for index in range(8)
    ]
    cell = _marker_cell_from_location({"space_id": "overworld", "coord": {"q": 0, "r": 0}}, "overworld_hex")
    assert cell is not None

    placements, overflow = _slot_markers_for_hex(0.0, 0.0, markers, cell)

    assert overflow == 0
    assert len(placements) == len(markers)
    unique_points = {(placement.x, placement.y) for placement in placements}
    assert len(unique_points) == len(markers)


def test_marker_payload_id_soft_fails_for_malformed_ids() -> None:
    marker = MarkerRecord(priority=0, marker_id="entity", marker_kind="entity", color=(1, 1, 1), radius=4, label="bad")

    assert _marker_payload_id(marker, expected_kind="entity") is None
    assert _marker_payload_id(marker, expected_kind="site") is None


def test_selected_entity_for_click_soft_fails_on_malformed_marker_id(monkeypatch: pytest.MonkeyPatch) -> None:
    sim = _build_viewer_simulation("content/examples/basic_map.json", with_encounters=False)

    def _bad_candidates(*args: object, **kwargs: object) -> list[MarkerRecord]:
        return [MarkerRecord(priority=0, marker_id="entity", marker_kind="entity", color=(1, 1, 1), radius=4, label="broken")]

    monkeypatch.setattr(viewer_module, "_find_world_marker_candidates_at_pixel", _bad_candidates)

    selected = _selected_entity_for_click(sim, (100, 100), (100.0, 100.0), radius_px=24.0)

    assert selected is None




def test_campaign_hex_topologies_route_to_overworld_projection() -> None:
    sim = _build_viewer_simulation("content/examples/basic_map.json", with_encounters=False)
    hex_space = SpaceState(
        space_id="campaign:hex_disk",
        topology_type="hex_disk",
        role="campaign",
        topology_params={"radius": 2},
    )
    sim.state.world.spaces[hex_space.space_id] = hex_space
    sim.state.entities[PLAYER_ID].space_id = hex_space.space_id
    sim.state.world.sites["hex-site"] = SiteRecord(
        site_id="hex-site",
        site_type="town",
        location={"space_id": hex_space.space_id, "topology_type": OVERWORLD_HEX_TOPOLOGY, "coord": {"q": 0, "r": 0}},
    )

    supported = _supported_viewer_topology(hex_space)
    placements = _world_marker_placements(sim, (200.0, 200.0), zoom_scale=1.0)

    assert supported == OVERWORLD_HEX_TOPOLOGY
    assert _viewer_topology_diagnostic(hex_space) is None
    assert any(placement.marker.marker_id == "site:hex-site" for placement in placements)

def test_world_marker_placements_skip_unsupported_topology_with_diagnostic() -> None:
    sim = _build_viewer_simulation("content/examples/basic_map.json", with_encounters=False)
    unsupported_space = SpaceState(
        space_id="local:unsupported",
        topology_type="triangle_grid",
        role=LOCAL_SPACE_ROLE,
        topology_params={"width": 5, "height": 5},
    )
    sim.state.world.spaces[unsupported_space.space_id] = unsupported_space
    sim.state.entities[PLAYER_ID].space_id = unsupported_space.space_id
    sim.state.entities[PLAYER_ID].position_x = 1.0
    sim.state.entities[PLAYER_ID].position_y = 1.0
    sim.state.world.sites["unsupported-site"] = SiteRecord(
        site_id="unsupported-site",
        site_type="town",
        location={"space_id": unsupported_space.space_id, "topology_type": OVERWORLD_HEX_TOPOLOGY, "coord": {"q": 0, "r": 0}},
    )

    placements = _world_marker_placements(sim, (200.0, 200.0), zoom_scale=1.0)
    diagnostic = _viewer_topology_diagnostic(unsupported_space)

    assert placements == []
    assert diagnostic == "unsupported_topology=triangle_grid (viewer projection disabled)"


def test_world_marker_candidates_are_deterministically_ordered() -> None:
    sim = _build_viewer_simulation("content/examples/basic_map.json", with_encounters=False)
    sim.state.world.sites["site-alpha"] = SiteRecord(
        site_id="site-alpha",
        site_type="town",
        location={"space_id": "overworld", "coord": {"q": 0, "r": 0}},
    )
    sim.state.world.sites["site-beta"] = SiteRecord(
        site_id="site-beta",
        site_type="town",
        location={"space_id": "overworld", "coord": {"q": 0, "r": 0}},
    )

    first = _find_world_marker_candidates_at_pixel(sim, (100, 100), (100.0, 100.0), radius_px=40.0)
    second = _find_world_marker_candidates_at_pixel(sim, (100, 100), (100.0, 100.0), radius_px=40.0)

    assert len(first) >= 2
    assert [marker.marker_id for marker in first] == [marker.marker_id for marker in second]


def test_find_world_marker_at_pixel_uses_same_positions_as_rendering_pipeline() -> None:
    sim = _build_viewer_simulation("content/examples/basic_map.json", with_encounters=False)
    sim.state.world.sites["site-alpha"] = SiteRecord(
        site_id="site-alpha",
        site_type="town",
        location={"space_id": "overworld", "coord": {"q": 0, "r": 0}},
    )

    marker = _find_world_marker_at_pixel(sim, (100, 100), (100.0, 100.0), radius_px=30.0)

    assert marker is not None
    assert marker.marker_id == "site:site-alpha"


def test_viewer_runtime_controller_new_simulation_replaces_state_deterministically() -> None:
    sim = _build_viewer_simulation("content/examples/basic_map.json", with_encounters=False, seed=42)
    state = ViewerRuntimeState(
        sim=sim,
        map_path="content/examples/basic_map.json",
        with_encounters=False,
        current_save_path="saves/session_save.json",
    )
    runtime = ViewerRuntimeController(state)

    original_hash = simulation_hash(state.sim)
    runtime.advance_ticks(17)
    runtime.new_simulation(seed=42)

    assert state.sim.state.tick == 0
    assert state.sim.seed == 42
    assert simulation_hash(state.sim) == original_hash


def test_viewer_runtime_controller_load_replaces_state(tmp_path: Path) -> None:
    baseline = _build_viewer_simulation("content/examples/basic_map.json", with_encounters=True, seed=13)
    baseline.advance_ticks(12)
    save_path = tmp_path / "runtime_load.json"
    _save_viewer_simulation(baseline, str(save_path))

    current = _build_viewer_simulation("content/examples/basic_map.json", with_encounters=False, seed=99)
    state = ViewerRuntimeState(
        sim=current,
        map_path="content/examples/basic_map.json",
        with_encounters=True,
        current_save_path=str(save_path),
    )
    runtime = ViewerRuntimeController(state)

    loaded = runtime.load_simulation(str(save_path))

    assert state.sim is loaded
    assert loaded.state.tick == 12
    assert simulation_hash(loaded) == simulation_hash(baseline)


def test_viewer_runtime_controller_save_uses_canonical_path(tmp_path: Path) -> None:
    sim = _build_viewer_simulation("content/examples/basic_map.json", with_encounters=False, seed=5)
    sim.advance_ticks(3)
    save_path = tmp_path / "runtime_save.json"
    state = ViewerRuntimeState(
        sim=sim,
        map_path="content/examples/basic_map.json",
        with_encounters=False,
        current_save_path=str(save_path),
    )
    runtime = ViewerRuntimeController(state)

    written_path = runtime.save_simulation()
    loaded = _load_viewer_simulation(written_path, with_encounters=False)

    assert written_path == str(save_path)
    assert loaded.state.tick == sim.state.tick
    assert simulation_hash(loaded) == simulation_hash(sim)


def test_viewer_runtime_controller_advance_controls_apply_expected_tick_deltas() -> None:
    sim = _build_viewer_simulation("content/examples/basic_map.json", with_encounters=False)
    state = ViewerRuntimeState(
        sim=sim,
        map_path="content/examples/basic_map.json",
        with_encounters=False,
        current_save_path="saves/session_save.json",
    )
    runtime = ViewerRuntimeController(state)

    runtime.advance_ticks(10)
    runtime.advance_ticks(100)
    runtime.advance_ticks(1000)

    assert state.sim.state.tick == 1110


def test_viewer_runtime_controller_pause_resume_toggle() -> None:
    sim = _build_viewer_simulation("content/examples/basic_map.json", with_encounters=False)
    state = ViewerRuntimeState(
        sim=sim,
        map_path="content/examples/basic_map.json",
        with_encounters=False,
        current_save_path="saves/session_save.json",
    )
    runtime = ViewerRuntimeController(state)

    assert state.paused is False
    assert runtime.toggle_pause() is True
    assert state.paused is True
    assert runtime.toggle_pause() is False
    assert state.paused is False


def test_viewer_runtime_controller_replacement_updates_command_adapter_reference() -> None:
    sim_a = _build_viewer_simulation("content/examples/basic_map.json", with_encounters=False, seed=7)
    state = ViewerRuntimeState(
        sim=sim_a,
        map_path="content/examples/basic_map.json",
        with_encounters=False,
        current_save_path="saves/session_save.json",
    )
    runtime = ViewerRuntimeController(state)

    sim_b = runtime.new_simulation(seed=11)
    runtime.controller.set_move_vector(0.25, -0.75)

    assert state.sim is sim_b
    assert runtime.controller.sim is sim_b
    assert sim_b.input_log[-1].params == {"x": 0.25, "y": -0.75}
    assert sim_a.input_log == []


def test_viewer_runtime_controller_new_simulation_same_seed_and_commands_is_deterministic() -> None:
    sim = _build_viewer_simulation("content/examples/basic_map.json", with_encounters=False, seed=123)
    state = ViewerRuntimeState(
        sim=sim,
        map_path="content/examples/basic_map.json",
        with_encounters=False,
        current_save_path="saves/session_save.json",
    )
    runtime = ViewerRuntimeController(state)

    runtime.new_simulation(seed=222)
    runtime.controller.set_move_vector(1.0, 0.0)
    runtime.advance_ticks(5)
    first_hash = simulation_hash(runtime.sim)

    runtime.new_simulation(seed=222)
    runtime.controller.set_move_vector(1.0, 0.0)
    runtime.advance_ticks(5)
    second_hash = simulation_hash(runtime.sim)

    assert first_hash == second_hash


def test_selected_entity_for_click_returns_entity_marker_hit() -> None:
    sim = _build_viewer_simulation("content/examples/basic_map.json", with_encounters=False)

    player = sim.state.entities[PLAYER_ID]
    player.position_x = 0.0
    player.position_y = 0.0

    picked = _selected_entity_for_click(sim, (100, 100), (100.0, 100.0), zoom_scale=1.0, radius_px=40.0)

    assert picked == PLAYER_ID


def test_selected_entity_for_click_returns_none_when_no_hit() -> None:
    sim = _build_viewer_simulation("content/examples/basic_map.json", with_encounters=False)

    picked = _selected_entity_for_click(sim, (5, 5), (300.0, 300.0), zoom_scale=1.0, radius_px=8.0)

    assert picked is None


def test_selected_entity_lines_include_minimal_observability_fields() -> None:
    sim = _build_viewer_simulation("content/examples/basic_map.json", with_encounters=False)
    investigator = EntityState(entity_id="investigator:test", position_x=1.0, position_y=2.0, space_id="overworld")
    investigator.template_id = "faction_investigator"
    investigator.stats = {
        "faction_id": "red_fang",
        "role": "investigator",
        "source_belief_id": "belief:123",
        "target_location": {"topology_type": "overworld_hex", "coord": {"q": 2, "r": 1}},
    }
    sim.add_entity(investigator)

    lines = _selected_entity_lines(sim, investigator.entity_id)

    assert any("Entity ID: investigator:test" in line for line in lines)
    assert any("Faction: red_fang" in line for line in lines)
    assert any("Role: investigator" in line for line in lines)
    assert any("Source belief: belief:123" in line for line in lines)
    assert any("Target location: overworld_hex:2,1" in line for line in lines)


def test_selection_commands_do_not_mutate_world_state_until_sim_step() -> None:
    sim = _build_viewer_simulation("content/examples/basic_map.json", with_encounters=False)
    controller = SimulationController(sim=sim, entity_id=PLAYER_ID)

    world_before = world_hash(sim.state.world)
    selected_before = sim.selected_entity_id(owner_entity_id=PLAYER_ID)
    input_before = len(sim.input_log)
    controller.set_selected_entity(PLAYER_ID)
    controller.clear_selected_entity()

    assert world_hash(sim.state.world) == world_before
    assert sim.selected_entity_id(owner_entity_id=PLAYER_ID) == selected_before
    assert len(sim.input_log) == input_before + 2


def test_world_marker_candidate_sort_is_deterministic_with_equal_distance(monkeypatch: pytest.MonkeyPatch) -> None:
    sim = _build_viewer_simulation("content/examples/basic_map.json", with_encounters=False)

    placements = [
        MarkerPlacement(
            marker=MarkerRecord(priority=1, marker_id="entity:zeta", marker_kind="entity", color=(1, 1, 1), radius=5, label="z"),
            x=100,
            y=100,
        ),
        MarkerPlacement(
            marker=MarkerRecord(priority=1, marker_id="entity:alpha", marker_kind="entity", color=(1, 1, 1), radius=5, label="a"),
            x=100,
            y=100,
        ),
    ]

    monkeypatch.setattr(viewer_module, "_world_marker_placements", lambda *_args, **_kwargs: placements)

    candidates = viewer_module._find_world_marker_candidates_at_pixel(sim, (100, 100), (100.0, 100.0), zoom_scale=1.0, radius_px=12.0)

    assert [candidate.marker_id for candidate in candidates] == ["entity:alpha", "entity:zeta"]


def test_queue_selection_command_for_click_uses_command_seam_end_to_end() -> None:
    sim = _build_viewer_simulation("content/examples/basic_map.json", with_encounters=False)
    controller = SimulationController(sim=sim, entity_id=PLAYER_ID)

    pending_before = len(sim.input_log)
    selected_before = sim.selected_entity_id(owner_entity_id=PLAYER_ID)

    status = _queue_selection_command_for_click(
        sim,
        controller,
        (100, 100),
        (100.0, 100.0),
        zoom_scale=1.0,
        radius_px=40.0,
    )

    assert status == f"selected {PLAYER_ID}"
    assert len(sim.input_log) == pending_before + 1
    assert sim.selected_entity_id(owner_entity_id=PLAYER_ID) == selected_before

    sim.advance_ticks(1)

    assert sim.selected_entity_id(owner_entity_id=PLAYER_ID) == PLAYER_ID


def test_selected_entity_trace_filter_matches_known_fields_and_excludes_irrelevant() -> None:
    sim = _build_viewer_simulation("content/examples/basic_map.json", with_encounters=False)
    selected_entity_id = "investigator:test"

    sim.schedule_event_at(
        sim.state.tick,
        "viewer_trace_match",
        {"entity_id": selected_entity_id, "action_uid": "a-1"},
    )
    sim.schedule_event_at(
        sim.state.tick,
        "viewer_trace_match_target",
        {"target": {"kind": "entity", "id": selected_entity_id}, "source_action_uid": "s-2"},
    )
    sim.schedule_event_at(
        sim.state.tick,
        "viewer_trace_irrelevant",
        {"entity_id": "other:1", "action_uid": "a-3"},
    )
    sim.advance_ticks(1)

    rows = _selected_entity_recent_trace_rows(sim, selected_entity_id)

    assert any("event=viewer_trace_match" in row for row in rows)
    assert any("event=viewer_trace_match_target" in row for row in rows)
    assert all("viewer_trace_irrelevant" not in row for row in rows)


def test_selected_entity_trace_rows_are_deterministic_most_recent_first() -> None:
    sim = _build_viewer_simulation("content/examples/basic_map.json", with_encounters=False)
    selected_entity_id = "investigator:test"

    for index in range(3):
        sim.schedule_event_at(
            sim.state.tick,
            f"viewer_trace_{index}",
            {"entity_id": selected_entity_id, "action_uid": f"uid-{index}"},
        )
    sim.advance_ticks(1)

    rows = _selected_entity_recent_trace_rows(sim, selected_entity_id)

    assert ["event=viewer_trace_2" in rows[0], "event=viewer_trace_1" in rows[1], "event=viewer_trace_0" in rows[2]] == [True, True, True]


def test_selected_entity_lines_include_trace_section_and_source_action_uid() -> None:
    sim = _build_viewer_simulation("content/examples/basic_map.json", with_encounters=False)
    investigator = EntityState(entity_id="investigator:test", position_x=1.0, position_y=2.0, space_id="overworld")
    investigator.source_action_uid = "source-action-77"
    sim.add_entity(investigator)

    sim.schedule_event_at(
        sim.state.tick,
        "viewer_trace_line",
        {"actor_id": investigator.entity_id, "action_uid": "trace-action-11"},
    )
    sim.advance_ticks(1)

    lines = _selected_entity_lines(sim, investigator.entity_id)

    assert any("Space ID: overworld" in line for line in lines)
    assert any("Source action UID: source-action-77" in line for line in lines)
    assert any(line == "RECENT EVENTS" for line in lines)
    assert any("event=viewer_trace_line" in line for line in lines)


def test_selected_entity_lines_include_follow_status_indicator() -> None:
    sim = _build_viewer_simulation("content/examples/basic_map.json", with_encounters=False)
    investigator = EntityState(entity_id="investigator:follow", position_x=1.0, position_y=1.0, space_id="overworld")
    sim.add_entity(investigator)

    lines = _selected_entity_lines(sim, investigator.entity_id, follow_status="inactive")

    assert any(line == "Follow status: inactive" for line in lines)


def test_event_trace_entry_mentions_entity_checks_known_fields_only() -> None:
    entry = {
        "event_type": "viewer_known_fields",
        "tick": 3,
        "params": {
            "source_entity_id": "entity:a",
            "target": {"kind": "entity", "id": "entity:b"},
            "nested": {"entity_id": "entity:c"},
        },
    }

    assert _event_trace_entry_mentions_entity(entry, "entity:a") is True
    assert _event_trace_entry_mentions_entity(entry, "entity:b") is True
    assert _event_trace_entry_mentions_entity(entry, "entity:c") is False


def test_debug_filter_selected_entity_includes_relevant_rows_only() -> None:
    sim = _build_viewer_simulation("content/examples/basic_map.json", with_encounters=False)
    selected_entity_id = "investigator:test"
    investigator = EntityState(entity_id=selected_entity_id, position_x=1.0, position_y=1.0, space_id="overworld")
    sim.add_entity(investigator)

    sim.schedule_event_at(sim.state.tick, "relevant", {"entity_id": selected_entity_id, "action_uid": "a-1"})
    sim.schedule_event_at(sim.state.tick, "irrelevant", {"entity_id": "other:1", "action_uid": "a-2"})
    sim.advance_ticks(1)

    rows = _build_debug_filter_trace_rows(
        sim,
        selected_entity_id=selected_entity_id,
        selected_context_filters={},
        event_type_filter=None,
        mode="selected_entity",
    )

    assert any(entry.get("event_type") == "relevant" for entry in rows)
    assert all(entry.get("event_type") != "irrelevant" for entry in rows)


def test_debug_filter_event_type_cycle_and_rows_are_deterministic() -> None:
    sim = _build_viewer_simulation("content/examples/basic_map.json", with_encounters=False)
    sim.schedule_event_at(sim.state.tick, "bbb", {"action_uid": "a-1"})
    sim.schedule_event_at(sim.state.tick, "aaa", {"action_uid": "a-2"})
    sim.advance_ticks(1)

    debug_filter_state = DebugFilterState()
    _cycle_debug_event_type_filter(sim, debug_filter_state)
    assert debug_filter_state.event_type_filter == "aaa"
    _cycle_debug_event_type_filter(sim, debug_filter_state)
    assert debug_filter_state.event_type_filter == "bbb"

    rows = _build_debug_filter_trace_rows(
        sim,
        selected_entity_id=None,
        selected_context_filters={},
        event_type_filter=debug_filter_state.event_type_filter,
        mode="all",
    )
    assert rows
    assert all(entry.get("event_type") == "bbb" for entry in rows)


def test_debug_filter_preserves_stable_ordering_under_filtering() -> None:
    sim = _build_viewer_simulation("content/examples/basic_map.json", with_encounters=False)
    selected_entity_id = "investigator:test"
    investigator = EntityState(entity_id=selected_entity_id, position_x=0.0, position_y=0.0, space_id="overworld")
    sim.add_entity(investigator)

    for index in range(3):
        sim.schedule_event_at(sim.state.tick, f"ev_{index}", {"entity_id": selected_entity_id, "action_uid": f"uid-{index}"})
    sim.advance_ticks(1)

    rows = _build_debug_filter_trace_rows(
        sim,
        selected_entity_id=selected_entity_id,
        selected_context_filters={},
        event_type_filter=None,
        mode="selected_entity",
    )

    assert [entry.get("event_type") for entry in rows] == ["ev_0", "ev_1", "ev_2"]


def test_debug_filter_state_does_not_mutate_world_or_sim_hash() -> None:
    sim = _build_viewer_simulation("content/examples/basic_map.json", with_encounters=False)
    world_before = world_hash(sim.state.world)
    sim_hash_before = simulation_hash(sim)
    debug_filter_state = DebugFilterState()

    _cycle_debug_filter_mode(debug_filter_state)
    _cycle_debug_event_type_filter(sim, debug_filter_state)

    assert world_hash(sim.state.world) == world_before
    assert simulation_hash(sim) == sim_hash_before


def test_debug_filter_render_rows_are_bounded_and_stable() -> None:
    sim = _build_viewer_simulation("content/examples/basic_map.json", with_encounters=False)
    selected_entity_id = "investigator:test"
    investigator = EntityState(entity_id=selected_entity_id, position_x=1.0, position_y=1.0, space_id="overworld")
    investigator.source_action_uid = "ctx-7"
    sim.add_entity(investigator)
    controller = SimulationController(sim=sim, entity_id=PLAYER_ID)
    controller.set_selected_entity(selected_entity_id)
    sim.schedule_event_at(sim.state.tick, "ctx_match", {"entity_id": selected_entity_id, "action_uid": "ctx-7"})
    sim.schedule_event_at(sim.state.tick, "ctx_miss", {"entity_id": selected_entity_id, "action_uid": "ctx-8"})
    sim.advance_ticks(1)

    rumor_state = RumorPanelState()
    debug_filter_state = DebugFilterState(mode="selected_context")
    rows = _debug_rows_by_section(sim, rumor_state, debug_filter_state)

    assert set(rows) == {"encounters", "outcomes", "rumors", "supplies", "sites", "entities"}
    assert len(rows["encounters"]) <= 30
    assert any("action_uid=ctx-7" in row for row in rows["encounters"])
    assert all("action_uid=ctx-8" not in row for row in rows["encounters"])


def test_debug_sites_rows_include_site_pressure_expression() -> None:
    sim = _build_viewer_simulation("content/examples/basic_map.json", with_encounters=False)
    player = sim.state.entities[PLAYER_ID]
    sim.state.world.sites["pressure-site"] = SiteRecord(
        site_id="pressure-site",
        site_type="town",
        location={"space_id": player.space_id, "coord": {"x": 0, "y": 0}},
        site_state=SiteWorldState(
            pressure_records=[
                SitePressureRecord(
                    faction_id="faction:ash",
                    pressure_type="raid",
                    strength=4,
                    tick=12,
                    source_event_id="evt-12",
                )
            ]
        ),
    )
    rumor_state = RumorPanelState()
    debug_filter_state = DebugFilterState()

    rows = _debug_rows_by_section(sim, rumor_state, debug_filter_state)

    assert any("site_id=pressure-site" in row for row in rows["sites"])
    assert any("pressure_records=1 showing_recent=1" in row for row in rows["sites"])
    assert any(
        "pressure faction=faction:ash type=raid strength=4 tick=12 source=evt-12" in row
        for row in rows["sites"]
    )


def test_debug_sites_pressure_rows_use_deterministic_recent_tail_order() -> None:
    sim = _build_viewer_simulation("content/examples/basic_map.json", with_encounters=False)
    player = sim.state.entities[PLAYER_ID]
    sim.state.world.sites["pressure-order-site"] = SiteRecord(
        site_id="pressure-order-site",
        site_type="town",
        location={"space_id": player.space_id, "coord": {"x": 0, "y": 0}},
        site_state=SiteWorldState(
            pressure_records=[
                SitePressureRecord(faction_id=f"faction:{i}", pressure_type="claim", strength=i, tick=i)
                for i in range(7)
            ]
        ),
    )
    rumor_state = RumorPanelState()
    debug_filter_state = DebugFilterState()

    rows = _debug_rows_by_section(sim, rumor_state, debug_filter_state)
    pressure_rows = [row for row in rows["sites"] if "pressure faction=" in row]

    assert any("pressure_records=7 showing_recent=5" in row for row in rows["sites"])
    assert pressure_rows == [
        "pressure faction=faction:6 type=claim strength=6 tick=6 source=-",
        "pressure faction=faction:5 type=claim strength=5 tick=5 source=-",
        "pressure faction=faction:4 type=claim strength=4 tick=4 source=-",
        "pressure faction=faction:3 type=claim strength=3 tick=3 source=-",
        "pressure faction=faction:2 type=claim strength=2 tick=2 source=-",
    ]


def test_debug_sites_pressure_expression_does_not_mutate_simulation() -> None:
    sim = _build_viewer_simulation("content/examples/basic_map.json", with_encounters=False)
    player = sim.state.entities[PLAYER_ID]
    sim.state.world.sites["pressure-safe-site"] = SiteRecord(
        site_id="pressure-safe-site",
        site_type="town",
        location={"space_id": player.space_id, "coord": {"x": 0, "y": 0}},
        site_state=SiteWorldState(
            pressure_records=[
                SitePressureRecord(faction_id="faction:red", pressure_type="threat", strength=2, tick=8)
            ]
        ),
    )
    rumor_state = RumorPanelState()
    debug_filter_state = DebugFilterState()
    sim_hash_before = simulation_hash(sim)
    world_hash_before = world_hash(sim.state.world)

    _debug_rows_by_section(sim, rumor_state, debug_filter_state)

    assert simulation_hash(sim) == sim_hash_before
    assert world_hash(sim.state.world) == world_hash_before


def test_debug_selected_context_filter_is_key_scoped_not_cross_field() -> None:
    sim = _build_viewer_simulation("content/examples/basic_map.json", with_encounters=False)
    sim.schedule_event_at(sim.state.tick, "ctx_source_event", {"source_event_id": "ctx-22"})
    sim.schedule_event_at(sim.state.tick, "ctx_action_overlap", {"action_uid": "ctx-22"})
    sim.advance_ticks(1)

    rows = _build_debug_filter_trace_rows(
        sim,
        selected_entity_id=None,
        selected_context_filters={"source_event_id": frozenset({"ctx-22"})},
        event_type_filter=None,
        mode="selected_context",
    )

    assert any(entry.get("event_type") == "ctx_source_event" for entry in rows)
    assert all(entry.get("event_type") != "ctx_action_overlap" for entry in rows)


def test_debug_filter_label_uses_readable_status_prefix() -> None:
    label = _debug_filter_label(DebugFilterState(mode="selected_entity", event_type_filter="encounter_action_outcome"))

    assert label == "debug filter: mode=selected_entity event_type=encounter_action_outcome"


def test_format_debug_trace_row_uses_bounded_pipe_separators() -> None:
    row = _format_debug_trace_row(
        {
            "tick": 7,
            "event_type": "viewer_event",
            "params": {
                "action_uid": "a-1",
                "source_action_uid": "a-0",
                "source_event_id": "e-1",
                "request_event_id": "e-0",
            },
        }
    )

    assert row == (
        "tick=7 | event=viewer_event | action_uid=a-1 | source_action_uid=a-0 | "
        "source_event_id=e-1 | request_event_id=e-0"
    )
