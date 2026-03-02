from pathlib import Path

import pytest

from hexcrawler.cli.pygame_viewer import (
    PLAYER_ID,
    RumorPanelState,
    SimulationController,
    _consume_rumor_outcome,
    _refresh_rumor_query,
    _build_parser,
    _build_viewer_simulation,
    MarkerRecord,
    _find_entity_at_pixel,
    _find_world_marker_at_pixel,
    _find_world_marker_candidates_at_pixel,
    _marker_cell_from_location,
    _slot_markers_for_hex,
    _load_viewer_simulation,
    _save_viewer_simulation,
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
from hexcrawler.sim.world import HexCoord, RumorRecord, SiteRecord


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
