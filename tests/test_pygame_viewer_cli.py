from pathlib import Path

import hexcrawler.cli.pygame_viewer as viewer_module
import pytest

from hexcrawler.cli.runtime_profiles import CORE_PLAYABLE, EXPERIMENTAL_WORLD
from hexcrawler.cli.pygame_viewer import (
    CAMPAIGN_RENDER_LAYER_ORDER,
    CORE_PLAYABLE_DEFAULT_PATROL_ID,
    CORE_PLAYABLE_DEFAULT_PATROL_TEMPLATE,
    CORE_PLAYABLE_MAJOR_SITE_IDS,
    CONTEXT_MENU_ROW_HEIGHT,
    PLAYER_ID,
    DebugFilterState,
    MarkerPlacement,
    MarkerRecord,
    PENDING_OFFER_DECISION_TICK_CAP,
    RumorPanelState,
    SimulationController,
    ViewerRuntimeController,
    ViewerRuntimeState,
    _build_debug_filter_trace_rows,
    _build_parser,
    _build_viewer_simulation,
    _calendar_presentation,
    _consume_rumor_outcome,
    _context_menu_item_index_at_pixel,
    _context_menu_layout,
    _cycle_debug_event_type_filter,
    _cycle_debug_filter_mode,
    _debug_filter_label,
    _debug_rows_by_section,
    _event_trace_entry_mentions_entity,
    _find_entity_at_pixel,
    _find_safe_site_status,
    _find_world_marker_at_pixel,
    _find_world_marker_candidates_at_pixel,
    _format_debug_trace_row,
    _home_panel_buttons_for_click,
    _home_panel_lines,
    _load_viewer_simulation,
    _marker_cell_center,
    _marker_cell_from_location,
    _marker_payload_id,
    _major_campaign_site_projections,
    _major_site_edge_indicators,
    _major_site_label_offset,
    _major_site_visibility_diagnostic_rows,
    _nearest_lootable_hostile_for_player,
    _player_feedback_lines,
    _player_facing_hud_lines,
    _queue_local_attack_for_click,
    _queue_selection_command_for_click,
    _refresh_rumor_query,
    _save_viewer_simulation,
    _selected_entity_for_click,
    _selected_entity_lines,
    _selected_entity_recent_trace_rows,
    _slot_markers_for_hex,
    _spatial_context_actions,
    _campaign_site_diagnostic_rows,
    _campaign_authoring_edit_items,
    _campaign_authoring_placement_items,
    _campaign_authored_object_at_world,
    _campaign_patrol_anchor_at_world,
    _campaign_patrol_route_points,
    _campaign_patrol_path_needed_count,
    _site_campaign_anchor_world,
    _use_campaign_site,
    _supported_viewer_topology,
    _viewer_topology_diagnostic,
    _world_marker_placements,
)
from hexcrawler.sim.combat import ATTACK_INTENT_COMMAND_TYPE
from hexcrawler.sim.core import EntityState, SimCommand
from hexcrawler.sim.campaign_danger import ACCEPT_ENCOUNTER_OFFER_INTENT, FLEE_ENCOUNTER_OFFER_INTENT, CampaignDangerModule
from hexcrawler.sim.encounters import (
    ENCOUNTER_ACTION_OUTCOME_EVENT_TYPE,
    LOCAL_ENCOUNTER_BEGIN_EVENT_TYPE,
    LOCAL_ENCOUNTER_HOSTILE_TEMPLATE_ID,
    LOCAL_ENCOUNTER_REWARD_EVENT_TYPE,
    LOCAL_ENCOUNTER_RETURN_EVENT_TYPE,
    EncounterActionExecutionModule,
    EncounterActionModule,
    EncounterCheckModule,
    EncounterSelectionModule,
    SELECT_RUMORS_INTENT,
    SpawnMaterializationModule,
)
from hexcrawler.sim.exploration import ENTER_SAFE_HUB_INTENT_COMMAND_TYPE
from hexcrawler.sim.hash import simulation_hash, world_hash
from hexcrawler.sim.location import OVERWORLD_HEX_TOPOLOGY
from hexcrawler.sim.local_hostiles import HOSTILE_TEMPLATE_ID
from hexcrawler.sim.movement import square_grid_cell_to_world_xy
from hexcrawler.sim.world import (
    CampaignPatrolRecord,
    EvidenceRecord,
    HexCoord,
    LOCAL_SPACE_ROLE,
    RumorRecord,
    SitePressureRecord,
    SiteRecord,
    SiteWorldState,
    SpaceState,
)
from hexcrawler.content.io import load_world_json


def test_viewer_parser_runtime_profile_defaults_to_core_playable() -> None:
    parser = _build_parser()
    args = parser.parse_args([])

    assert args.runtime_profile == "core_playable"
    assert args.map_path == "content/examples/viewer_map.json"
    assert args.save_path == "saves/session_save.json"
    assert args.load_save is None


def test_viewer_parser_runtime_profile_can_be_selected() -> None:
    parser = _build_parser()
    args = parser.parse_args(["--runtime-profile", "experimental_world", "--save-path", "saves/dev.json", "--load-save", "saves/dev.json"])

    assert args.runtime_profile == "experimental_world"
    assert args.save_path == "saves/dev.json"
    assert args.load_save == "saves/dev.json"


def test_core_playable_viewer_map_contains_visible_safe_home_town() -> None:
    world = load_world_json("content/examples/viewer_map.json")
    site = world.sites.get("home_greybridge")
    assert site is not None
    assert site.site_type == "town"
    assert "safe" in site.tags
    assert site.location.get("space_id") == "overworld"
    assert site.name == "Greybridge Home"


def test_world_markers_include_generic_town_and_dungeon_site_markers() -> None:
    sim = _build_viewer_simulation("content/examples/viewer_map.json", with_encounters=False)

    markers = _world_marker_placements(sim, center=(640.0, 360.0), zoom_scale=1.0)
    town_markers = [placement.marker for placement in markers if placement.marker.marker_kind == "site" and placement.marker.marker_id == "site:home_greybridge"]
    dungeon_markers = [
        placement.marker
        for placement in markers
        if placement.marker.marker_kind == "site" and placement.marker.marker_id == "site:demo_dungeon_entrance"
    ]

    assert town_markers
    assert dungeon_markers
    assert town_markers[0].radius > dungeon_markers[0].radius
    assert town_markers[0].color == (80, 160, 255)
    assert dungeon_markers[0].color == (210, 85, 85)


def test_core_playable_default_scene_is_sparse_and_contains_single_patrol() -> None:
    sim = _build_viewer_simulation("content/examples/viewer_map.json", runtime_profile=CORE_PLAYABLE)

    assert tuple(sorted(sim.state.world.sites.keys())) == tuple(sorted(CORE_PLAYABLE_MAJOR_SITE_IDS))
    patrols = [entity for entity in sim.state.entities.values() if entity.template_id == CORE_PLAYABLE_DEFAULT_PATROL_TEMPLATE]
    assert len(patrols) == 1
    assert patrols[0].stats.get("role") == "patrol"
    home_anchor = _site_campaign_anchor_world(sim.state.world.sites["home_greybridge"])
    dungeon_anchor = _site_campaign_anchor_world(sim.state.world.sites["demo_dungeon_entrance"])
    assert home_anchor is not None
    assert dungeon_anchor is not None
    assert patrols[0].position_x == pytest.approx(-2.60)
    assert patrols[0].position_y == pytest.approx(1.90)
    assert ((home_anchor[0] - dungeon_anchor[0]) ** 2 + (home_anchor[1] - dungeon_anchor[1]) ** 2) ** 0.5 >= 3.0
    assert ((home_anchor[0] - patrols[0].position_x) ** 2 + (home_anchor[1] - patrols[0].position_y) ** 2) ** 0.5 >= 2.5


def test_core_playable_campaign_marker_surface_omits_incidental_world_records() -> None:
    sim = _build_viewer_simulation("content/examples/viewer_map.json", runtime_profile=CORE_PLAYABLE)
    sim.state.world.signals.append(
        {
            "signal_uid": "sig:test",
            "location": {"space_id": "overworld", "topology_type": "overworld_hex", "coord": {"q": 0, "r": 0}},
        }
    )
    sim.state.world.tracks.append(
        {
            "track_uid": "trk:test",
            "location": {"space_id": "overworld", "topology_type": "overworld_hex", "coord": {"q": 0, "r": 0}},
        }
    )
    sim.state.world.append_spawn_descriptor(
        {
            "action_uid": "spawn:test",
            "location": {"space_id": "overworld", "topology_type": "overworld_hex", "coord": {"q": 0, "r": 0}},
        }
    )

    markers = _world_marker_placements(sim, center=(640.0, 360.0), zoom_scale=1.0, include_incidental_records=False)
    marker_kinds = {placement.marker.marker_kind for placement in markers}

    assert "site" in marker_kinds
    assert "entity" in marker_kinds
    assert "signal" not in marker_kinds
    assert "track" not in marker_kinds
    assert "spawn_desc" not in marker_kinds


def test_campaign_render_layer_order_is_explicit_and_stable() -> None:
    assert CAMPAIGN_RENDER_LAYER_ORDER == (
        "map_base",
        "site_icons",
        "site_labels",
        "actors",
        "overlays_selection",
        "hud_panels_modals",
    )


def test_campaign_authoring_empty_space_menu_exposes_right_click_placement_actions() -> None:
    items = _campaign_authoring_placement_items(2.0, -1.0)
    labels = [item.label for item in items]

    assert "Place Town Here" in labels
    assert "Place Dungeon Entrance Here" in labels
    assert "Place Patrol Here" in labels
    town_payload = next(item.payload for item in items if item.label == "Place Town Here")
    assert isinstance(town_payload, dict)
    assert town_payload["kind"] == "town"
    assert town_payload["position"] == {"x": 2.0, "y": -1.0}


def test_campaign_authoring_existing_object_menu_exposes_move_delete_actions() -> None:
    target = {"kind": "site", "id": "authoring_town_0_0", "label": "Authored Town"}

    items = _campaign_authoring_edit_items(target)
    labels = [item.label for item in items]

    assert "Move" in labels
    assert "Delete" in labels
    move_item = next(item for item in items if item.action == "campaign_author_move")
    assert move_item.payload == target


def test_campaign_authoring_patrol_edit_menu_exposes_edit_path_entry() -> None:
    items = _campaign_authoring_edit_items({"kind": "patrol", "id": "patrol:alpha", "label": "Alpha Patrol"})
    labels = [item.label for item in items]

    assert "Edit Path" in labels


def test_campaign_authoring_target_detection_prefers_clicked_authored_site_or_patrol() -> None:
    sim = _build_viewer_simulation("content/examples/viewer_map.json", runtime_profile=CORE_PLAYABLE)
    sim.state.world.sites["authoring_town_0_0"] = SiteRecord(
        site_id="authoring_town_0_0",
        site_type="town",
        location={
            "space_id": "overworld",
            "topology_type": OVERWORLD_HEX_TOPOLOGY,
            "coord": {"q": 0, "r": 0},
            "campaign_anchor": {"x": 0.25, "y": 0.25},
        },
        name="Authored Town",
        tags=["authored", "town"],
    )
    sim.state.world.campaign_patrols["patrol:authoring_demo"] = CampaignPatrolRecord(
        patrol_id="patrol:authoring_demo",
        template_id=CORE_PLAYABLE_DEFAULT_PATROL_TEMPLATE,
        space_id="overworld",
        spawn_position={"x": -1.5, "y": 0.5},
        route_anchors=[{"x": -1.0, "y": 0.5}],
        label="Authored Patrol",
        tags=["authoring"],
    )

    town = _campaign_authored_object_at_world(sim, world_x=0.2, world_y=0.2)
    patrol = _campaign_authored_object_at_world(sim, world_x=-1.5, world_y=0.5)
    nothing = _campaign_authored_object_at_world(sim, world_x=8.0, world_y=8.0)

    assert town is not None and town["kind"] == "site" and town["id"] == "authoring_town_0_0"
    assert patrol is not None and patrol["kind"] == "patrol" and patrol["id"] == "patrol:authoring_demo"
    assert nothing is None


def test_campaign_patrol_anchor_hit_detection_enables_move_or_delete_actions() -> None:
    sim = _build_viewer_simulation("content/examples/viewer_map.json", runtime_profile=CORE_PLAYABLE)
    sim.state.world.campaign_patrols["patrol:anchor_hit"] = CampaignPatrolRecord(
        patrol_id="patrol:anchor_hit",
        template_id=CORE_PLAYABLE_DEFAULT_PATROL_TEMPLATE,
        space_id="overworld",
        spawn_position={"x": 2.0, "y": 2.0},
        route_anchors=[{"x": 3.0, "y": 2.0}],
        label="Anchor Hit Patrol",
        tags=["authoring"],
    )

    anchor_index = _campaign_patrol_anchor_at_world(
        sim,
        patrol_id="patrol:anchor_hit",
        world_x=3.02,
        world_y=2.01,
    )
    assert anchor_index == 0


def test_campaign_patrol_path_needed_count_detects_missing_route_anchor() -> None:
    sim = _build_viewer_simulation("content/examples/viewer_map.json", runtime_profile=CORE_PLAYABLE)
    baseline = _campaign_patrol_path_needed_count(sim)
    sim.state.world.campaign_patrols["patrol:path_needed"] = CampaignPatrolRecord(
        patrol_id="patrol:path_needed",
        template_id=CORE_PLAYABLE_DEFAULT_PATROL_TEMPLATE,
        space_id="overworld",
        spawn_position={"x": -5.0, "y": -5.0},
        route_anchors=[],
        label="Path Needed Patrol",
        tags=["authoring"],
    )

    assert _campaign_patrol_path_needed_count(sim) == baseline + 1


def test_campaign_patrol_route_points_include_spawn_as_anchor_zero_then_authored_order() -> None:
    patrol = CampaignPatrolRecord(
        patrol_id="patrol:route_points",
        template_id=CORE_PLAYABLE_DEFAULT_PATROL_TEMPLATE,
        space_id="overworld",
        spawn_position={"x": -2.0, "y": 1.0},
        route_anchors=[{"x": -1.5, "y": 1.0}, {"x": -1.0, "y": 0.5}],
        label="Route Points Patrol",
        tags=["authoring"],
    )
    assert _campaign_patrol_route_points(patrol) == [(-2.0, 1.0), (-1.5, 1.0), (-1.0, 0.5)]


def test_run_pygame_viewer_right_click_campaign_map_does_not_raise_name_error(monkeypatch: pytest.MonkeyPatch) -> None:
    import pygame

    events = [
        pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"button": 3, "pos": (100, 100)}),
        pygame.event.Event(pygame.QUIT, {}),
    ]

    def _event_get() -> list[pygame.event.Event]:
        nonlocal events
        if events:
            queued = events
            events = []
            return queued
        return []

    monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
    monkeypatch.setattr(pygame.event, "get", _event_get)

    exit_code = viewer_module.run_pygame_viewer(
        map_path="content/examples/viewer_map.json",
        runtime_profile=CORE_PLAYABLE,
        headless=False,
    )

    assert exit_code == 0


def test_campaign_right_click_patrol_placement_creates_authored_patrol_and_runtime_entity() -> None:
    sim = _build_viewer_simulation("content/examples/viewer_map.json", runtime_profile=CORE_PLAYABLE, seed=13)
    controller = SimulationController(sim=sim, entity_id=PLAYER_ID)

    controller.campaign_author_intent(
        "create_or_update_patrol",
        patrol_id="patrol:authoring_right_click",
        template_id=CORE_PLAYABLE_DEFAULT_PATROL_TEMPLATE,
        label="Authored Patrol",
        position={"x": 1.25, "y": -0.75},
        route_anchors=[{"x": 2.0, "y": -0.75}],
        tags=["authoring"],
    )
    sim.advance_ticks(2)

    patrol = sim.state.world.campaign_patrols.get("patrol:authoring_right_click")
    assert patrol is not None
    assert patrol.spawn_position == {"x": 1.25, "y": -0.75}
    assert "patrol:authoring_right_click" in sim.state.entities
    assert sim.state.entities["patrol:authoring_right_click"].position_x > 1.25
    assert sim.state.entities["patrol:authoring_right_click"].position_y == pytest.approx(-0.75)


def test_campaign_authoring_move_delete_are_uniform_for_seeded_and_new_objects() -> None:
    sim = _build_viewer_simulation("content/examples/viewer_map.json", runtime_profile=CORE_PLAYABLE, seed=17)
    controller = SimulationController(sim=sim, entity_id=PLAYER_ID)
    baseline_hash = simulation_hash(sim)
    seeded_dungeon_site_id = next(
        site_id for site_id, site in sorted(sim.state.world.sites.items()) if site.site_type == "dungeon_entrance"
    )
    assert "home_greybridge" in sim.state.world.sites
    assert seeded_dungeon_site_id in sim.state.world.sites
    assert CORE_PLAYABLE_DEFAULT_PATROL_ID in sim.state.world.campaign_patrols

    controller.campaign_author_intent(
        "create_or_update_site",
        site_id="authoring_town_right_click",
        site_kind="town",
        label="Authored Town",
        position={"x": 0.5, "y": 2.5},
    )
    controller.campaign_author_intent(
        "create_or_update_site",
        site_id="authoring_dungeon_right_click",
        site_kind="dungeon_entrance",
        label="Authored Dungeon Entrance",
        position={"x": 2.0, "y": 1.5},
    )
    controller.campaign_author_intent(
        "create_or_update_patrol",
        patrol_id="patrol:authoring_right_click_unified",
        template_id=CORE_PLAYABLE_DEFAULT_PATROL_TEMPLATE,
        label="Authored Patrol",
        position={"x": -1.5, "y": 1.5},
        route_anchors=[{"x": -0.5, "y": 1.5}],
        tags=["authoring"],
    )
    sim.advance_ticks(2)
    assert "authoring_town_right_click" in sim.state.world.sites
    assert "authoring_dungeon_right_click" in sim.state.world.sites
    assert "patrol:authoring_right_click_unified" in sim.state.world.campaign_patrols

    controller.campaign_author_intent("move_site", site_id="home_greybridge", position={"x": 4.0, "y": -4.0})
    controller.campaign_author_intent("move_site", site_id=seeded_dungeon_site_id, position={"x": 5.0, "y": -5.0})
    controller.campaign_author_intent(
        "move_patrol_spawn",
        patrol_id=CORE_PLAYABLE_DEFAULT_PATROL_ID,
        position={"x": -4.0, "y": 0.0},
    )
    controller.campaign_author_intent("move_site", site_id="authoring_town_right_click", position={"x": 0.0, "y": 3.0})
    controller.campaign_author_intent("move_site", site_id="authoring_dungeon_right_click", position={"x": 3.5, "y": 2.0})
    controller.campaign_author_intent(
        "move_patrol_spawn",
        patrol_id="patrol:authoring_right_click_unified",
        position={"x": -3.0, "y": 2.25},
    )
    sim.advance_ticks(2)

    assert sim.state.world.sites["home_greybridge"].location.get("campaign_anchor") == {"x": 4.0, "y": -4.0}
    assert sim.state.world.sites[seeded_dungeon_site_id].location.get("campaign_anchor") == {"x": 5.0, "y": -5.0}
    assert sim.state.world.campaign_patrols[CORE_PLAYABLE_DEFAULT_PATROL_ID].spawn_position == {"x": -4.0, "y": 0.0}
    assert sim.state.world.sites["authoring_town_right_click"].location.get("campaign_anchor") == {"x": 0.0, "y": 3.0}
    assert sim.state.world.sites["authoring_dungeon_right_click"].location.get("campaign_anchor") == {"x": 3.5, "y": 2.0}
    assert sim.state.world.campaign_patrols["patrol:authoring_right_click_unified"].spawn_position == {"x": -3.0, "y": 2.25}

    controller.campaign_author_intent("delete_site", site_id="home_greybridge")
    controller.campaign_author_intent("delete_site", site_id=seeded_dungeon_site_id)
    controller.campaign_author_intent("delete_patrol", patrol_id=CORE_PLAYABLE_DEFAULT_PATROL_ID)
    controller.campaign_author_intent("delete_site", site_id="authoring_town_right_click")
    controller.campaign_author_intent("delete_site", site_id="authoring_dungeon_right_click")
    controller.campaign_author_intent("delete_patrol", patrol_id="patrol:authoring_right_click_unified")
    sim.advance_ticks(2)

    assert "home_greybridge" not in sim.state.world.sites
    assert seeded_dungeon_site_id not in sim.state.world.sites
    assert CORE_PLAYABLE_DEFAULT_PATROL_ID not in sim.state.world.campaign_patrols
    assert "authoring_town_right_click" not in sim.state.world.sites
    assert "authoring_dungeon_right_click" not in sim.state.world.sites
    assert "patrol:authoring_right_click_unified" not in sim.state.world.campaign_patrols
    assert simulation_hash(sim) != baseline_hash


def test_site_marker_uses_campaign_anchor_position_instead_of_hex_center() -> None:
    sim = _build_viewer_simulation("content/examples/viewer_map.json", with_encounters=False)
    world_center = (640.0, 360.0)
    site = sim.state.world.sites["home_greybridge"]
    anchor = _site_campaign_anchor_world(site)
    assert anchor is not None
    expected_x, expected_y = viewer_module._world_to_pixel(anchor[0], anchor[1], world_center, 1.0)
    markers = _world_marker_placements(sim, center=world_center, zoom_scale=1.0)
    placement = next(current for current in markers if current.marker.marker_id == "site:home_greybridge")

    assert placement.x == int(round(expected_x))
    assert placement.y == int(round(expected_y))


def test_site_marker_falls_back_to_hex_center_when_campaign_anchor_missing() -> None:
    sim = _build_viewer_simulation("content/examples/viewer_map.json", with_encounters=False)
    world_center = (640.0, 360.0)
    site = sim.state.world.sites["home_greybridge"]
    site.location.pop("campaign_anchor", None)
    home_cell = _marker_cell_from_location(site.location, OVERWORLD_HEX_TOPOLOGY)
    assert home_cell is not None
    expected_x, expected_y = _marker_cell_center(home_cell, world_center, zoom_scale=1.0)
    markers = _world_marker_placements(sim, center=world_center, zoom_scale=1.0)
    placement = next(current for current in markers if current.marker.marker_id == "site:home_greybridge")
    assert placement.x == int(round(expected_x))
    assert placement.y == int(round(expected_y))


def test_safe_site_detection_resolves_home_town_for_player() -> None:
    sim = _build_viewer_simulation("content/examples/viewer_map.json", with_encounters=False)
    player = sim.state.entities[PLAYER_ID]

    is_safe, site_id, site_type = _find_safe_site_status(sim, player)

    assert is_safe is True
    assert site_id == "home_greybridge"
    assert site_type == "town"


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


def test_simulation_controller_appends_attack_intent_command() -> None:
    sim = _build_viewer_simulation("content/examples/basic_map.json", with_encounters=False)
    controller = SimulationController(sim=sim, entity_id=PLAYER_ID)

    controller.attack_entity("target")

    assert sim.input_log[-1].command_type == ATTACK_INTENT_COMMAND_TYPE
    assert sim.input_log[-1].entity_id == PLAYER_ID
    assert sim.input_log[-1].params == {
        "attacker_id": PLAYER_ID,
        "target_id": "target",
        "mode": "melee",
        "tags": ["viewer_local_attack"],
    }


def test_enter_or_e_generic_site_use_opens_town_services_via_generic_path() -> None:
    sim = _build_viewer_simulation("content/examples/viewer_map.json", with_encounters=False)
    controller = SimulationController(sim=sim, entity_id=PLAYER_ID)
    player = sim.state.entities[PLAYER_ID]

    message, selected_site_id, open_site_panel = _use_campaign_site(
        sim,
        controller,
        player=player,
        selected_site_id="home_greybridge",
    )

    assert selected_site_id == "home_greybridge"
    assert open_site_panel is False
    assert "entering Greybridge hub" in message
    assert sim.input_log[-1].command_type == "enter_safe_hub_intent"


def test_enter_or_e_generic_site_use_accepts_greybridge_from_prompt_range() -> None:
    sim = _build_viewer_simulation("content/examples/viewer_map.json", runtime_profile=CORE_PLAYABLE)
    controller = SimulationController(sim=sim, entity_id=PLAYER_ID)
    player = sim.state.entities[PLAYER_ID]
    home_anchor = _site_campaign_anchor_world(sim.state.world.sites["home_greybridge"])
    assert home_anchor is not None
    player.position_x = home_anchor[0] + 1.1
    player.position_y = home_anchor[1]

    message, selected_site_id, _ = _use_campaign_site(
        sim,
        controller,
        player=player,
        selected_site_id=None,
    )

    assert selected_site_id == "home_greybridge"
    assert "entering Greybridge hub" in message
    assert sim.input_log[-1].command_type == "enter_safe_hub_intent"


def test_enter_or_e_generic_site_use_reaches_dungeon_entrance_path() -> None:
    sim = _build_viewer_simulation("content/examples/viewer_map.json", with_encounters=False)
    controller = SimulationController(sim=sim, entity_id=PLAYER_ID)
    player = sim.state.entities[PLAYER_ID]
    dungeon_site = sim.state.world.sites["demo_dungeon_entrance"]
    anchor = _site_campaign_anchor_world(dungeon_site)
    assert anchor is not None
    player.position_x = anchor[0]
    player.position_y = anchor[1]

    message, selected_site_id, open_site_panel = _use_campaign_site(
        sim,
        controller,
        player=player,
        selected_site_id="demo_dungeon_entrance",
    )

    assert selected_site_id == "demo_dungeon_entrance"
    assert open_site_panel is False
    assert "entering site" in message
    assert sim.input_log[-1].command_type == "enter_site"
    assert sim.input_log[-1].params == {"site_id": "demo_dungeon_entrance"}


def test_enter_or_e_generic_site_use_uses_legacy_hex_fallback_when_anchor_missing() -> None:
    sim = _build_viewer_simulation("content/examples/viewer_map.json", with_encounters=False)
    controller = SimulationController(sim=sim, entity_id=PLAYER_ID)
    player = sim.state.entities[PLAYER_ID]
    dungeon_site = sim.state.world.sites["demo_dungeon_entrance"]
    dungeon_site.location.pop("campaign_anchor", None)
    fallback_anchor = _site_campaign_anchor_world(dungeon_site)
    assert fallback_anchor is not None
    player.position_x = fallback_anchor[0]
    player.position_y = fallback_anchor[1]

    message, selected_site_id, open_site_panel = _use_campaign_site(
        sim,
        controller,
        player=player,
        selected_site_id="demo_dungeon_entrance",
    )

    assert selected_site_id == "demo_dungeon_entrance"
    assert open_site_panel is False
    assert "entering site" in message
    assert sim.input_log[-1].command_type == "enter_site"
    assert sim.input_log[-1].params == {"site_id": "demo_dungeon_entrance"}


def test_campaign_site_diagnostics_report_loaded_sites_and_are_bounded() -> None:
    class ClipRect:
        def collidepoint(self, point: tuple[int, int]) -> bool:
            x, y = point
            return 0 <= x <= 1280 and 0 <= y <= 720

    sim = _build_viewer_simulation("content/examples/viewer_map.json", with_encounters=False)
    rows = _campaign_site_diagnostic_rows(
        sim,
        center=(640.0, 360.0),
        zoom_scale=1.0,
        clip_rect=ClipRect(),
        max_rows=1,
    )

    assert rows[0].startswith("campaign_sites loaded=2 visible=2 showing=1")
    assert len(rows) == 2
    assert "site id=" in rows[1]
    assert "world=(" in rows[1]
    assert "screen=(" in rows[1]
    assert "on_screen=yes" in rows[1]


def test_major_campaign_site_projection_contains_core_playable_sites() -> None:
    class ClipRect:
        def collidepoint(self, point: tuple[int, int]) -> bool:
            x, y = point
            return 0 <= x <= 1280 and 0 <= y <= 720

    sim = _build_viewer_simulation("content/examples/viewer_map.json", with_encounters=False)
    rows = _major_campaign_site_projections(sim, center=(640.0, 360.0), zoom_scale=1.0, clip_rect=ClipRect())
    ids = {row.site_id for row in rows}

    assert "home_greybridge" in ids
    assert "demo_dungeon_entrance" in ids


def test_major_campaign_projection_is_not_hardcoded_to_core_site_ids() -> None:
    sim = _build_viewer_simulation("content/examples/viewer_map.json", with_encounters=False)
    sim.state.world.sites["outpost:stonewatch"] = SiteRecord(
        site_id="outpost:stonewatch",
        site_type="town",
        location={
            "space_id": "overworld",
            "topology_type": "overworld_hex",
            "coord": {"q": 1, "r": 0},
            "campaign_anchor": {"x": 1.2, "y": 0.4},
        },
        name="Stonewatch",
        tags=[],
    )

    projected = _major_campaign_site_projections(sim, center=(640.0, 360.0), zoom_scale=1.0)
    projected_ids = {row.site_id for row in projected}

    assert "outpost:stonewatch" in projected_ids


def test_major_site_markers_bypass_scatter_slotting_path() -> None:
    sim = _build_viewer_simulation("content/examples/viewer_map.json", with_encounters=False)
    center = (640.0, 360.0)
    site = sim.state.world.sites["home_greybridge"]
    anchor = _site_campaign_anchor_world(site)
    assert anchor is not None
    expected_x, expected_y = viewer_module._world_to_pixel(anchor[0], anchor[1], center, 1.0)

    original_slotter = viewer_module._slot_markers_for_hex
    viewer_module._slot_markers_for_hex = lambda *_args, **_kwargs: ([], 0)  # type: ignore[assignment]
    try:
        placements = _world_marker_placements(sim, center=center, zoom_scale=1.0)
    finally:
        viewer_module._slot_markers_for_hex = original_slotter  # type: ignore[assignment]

    placement = next(current for current in placements if current.marker.marker_id == "site:home_greybridge")
    assert placement.x == int(round(expected_x))
    assert placement.y == int(round(expected_y))


def test_major_site_visibility_diagnostics_include_player_and_required_sites() -> None:
    class ClipRect:
        def collidepoint(self, point: tuple[int, int]) -> bool:
            x, y = point
            return 0 <= x <= 1280 and 0 <= y <= 720

    sim = _build_viewer_simulation("content/examples/viewer_map.json", with_encounters=False)
    rows = _major_site_visibility_diagnostic_rows(
        sim,
        center=(640.0, 360.0),
        zoom_scale=1.0,
        clip_rect=ClipRect(),
    )

    assert rows[0].startswith("campaign_major_sites player_world=")
    assert "player_hex=" in rows[0]
    assert any("major_site id=home_greybridge" in row and "screen=(" in row and "on_screen=yes" in row for row in rows[1:])
    assert any("major_site id=demo_dungeon_entrance" in row and "screen=(" in row and "on_screen=yes" in row for row in rows[1:])
    assert any("major_site_focus id=home_greybridge" in row for row in rows)
    assert any("major_site_focus id=demo_dungeon_entrance" in row for row in rows)


def test_major_site_render_and_use_share_identity() -> None:
    sim = _build_viewer_simulation("content/examples/viewer_map.json", with_encounters=False)
    controller = SimulationController(sim=sim, entity_id=PLAYER_ID)
    player = sim.state.entities[PLAYER_ID]
    projected = _major_campaign_site_projections(sim, center=(640.0, 360.0), zoom_scale=1.0)
    projected_ids = {row.site_id for row in projected}
    assert "demo_dungeon_entrance" in projected_ids

    dungeon_anchor = _site_campaign_anchor_world(sim.state.world.sites["demo_dungeon_entrance"])
    assert dungeon_anchor is not None
    player.position_x = dungeon_anchor[0]
    player.position_y = dungeon_anchor[1]

    message, selected_site_id, open_site_panel = _use_campaign_site(
        sim,
        controller,
        player=player,
        selected_site_id="demo_dungeon_entrance",
    )

    assert "entering site" in message
    assert open_site_panel is False
    assert selected_site_id in projected_ids
    assert sim.input_log[-1].params == {"site_id": selected_site_id}


def test_major_site_label_offset_switches_to_overlap_safe_offset_when_player_colocated() -> None:
    offset_x, offset_y, overlaps_player = _major_site_label_offset((640, 360), (642, 358))

    assert overlaps_player is True
    assert (offset_x, offset_y) == (22, -34)

    far_x, far_y, far_overlap = _major_site_label_offset((640, 360), (780, 500))

    assert far_overlap is False
    assert (far_x, far_y) == (12, -16)


def test_major_site_offscreen_indicator_rows_exist_for_hidden_major_sites() -> None:
    class ClipRect:
        left = 0
        right = 1280
        top = 0
        bottom = 720
        centerx = 640
        centery = 360

        def collidepoint(self, point: tuple[int, int]) -> bool:
            x, y = point
            return self.left <= x <= self.right and self.top <= y <= self.bottom

    sim = _build_viewer_simulation("content/examples/viewer_map.json", with_encounters=False)
    indicators = _major_site_edge_indicators(
        sim,
        _major_campaign_site_projections(sim, center=(-800.0, -600.0), zoom_scale=1.0, clip_rect=ClipRect()),
        clip_rect=ClipRect(),
    )

    assert indicators
    assert all("↗" in row.label for row in indicators)


def test_viewer_runtime_controller_new_simulation_preserves_core_playable_patrol_and_sites() -> None:
    sim = _build_viewer_simulation("content/examples/viewer_map.json", runtime_profile=CORE_PLAYABLE, seed=7)
    runtime_state = ViewerRuntimeState(
        sim=sim,
        map_path="content/examples/viewer_map.json",
        with_encounters=True,
        current_save_path="saves/session_save.json",
        runtime_profile=CORE_PLAYABLE,
    )
    runtime = ViewerRuntimeController(runtime_state)

    replaced = runtime.new_simulation(seed=55)

    assert tuple(sorted(replaced.state.world.sites.keys())) == tuple(sorted(CORE_PLAYABLE_MAJOR_SITE_IDS))
    patrol_ids = sorted(
        entity.entity_id for entity in replaced.state.entities.values() if entity.template_id == CORE_PLAYABLE_DEFAULT_PATROL_TEMPLATE
    )
    assert len(patrol_ids) == 1
    patrol = replaced.state.entities[patrol_ids[0]]
    home_anchor = _site_campaign_anchor_world(replaced.state.world.sites["home_greybridge"])
    dungeon_anchor = _site_campaign_anchor_world(replaced.state.world.sites["demo_dungeon_entrance"])
    assert home_anchor is not None
    assert dungeon_anchor is not None
    assert patrol.position_x == pytest.approx(-2.60)
    assert patrol.position_y == pytest.approx(1.90)
    assert ((home_anchor[0] - dungeon_anchor[0]) ** 2 + (home_anchor[1] - dungeon_anchor[1]) ** 2) ** 0.5 >= 3.0


def test_load_simulation_preserves_saved_patrol_composition_without_core_scene_normalization(tmp_path: Path) -> None:
    sim = _build_viewer_simulation("content/examples/viewer_map.json", runtime_profile=CORE_PLAYABLE, seed=7)
    sim.add_entity(
        EntityState(
            entity_id="patrol:extra_saved",
            position_x=1.8,
            position_y=0.7,
            template_id=CORE_PLAYABLE_DEFAULT_PATROL_TEMPLATE,
            stats={"faction_id": "hostile", "role": "patrol"},
        )
    )
    save_path = tmp_path / "custom_scene_save.json"
    _save_viewer_simulation(sim, str(save_path))

    loaded = _load_viewer_simulation(str(save_path), runtime_profile=CORE_PLAYABLE)
    patrol_ids = sorted(
        entity.entity_id for entity in loaded.state.entities.values() if entity.template_id == CORE_PLAYABLE_DEFAULT_PATROL_TEMPLATE
    )

    assert patrol_ids == ["danger:raider_patrol_alpha", "patrol:extra_saved"]


def test_queue_local_attack_for_click_routes_to_authoritative_attack_intent(monkeypatch: pytest.MonkeyPatch) -> None:
    sim = _build_viewer_simulation("content/examples/basic_map.json", with_encounters=False)
    controller = SimulationController(sim=sim, entity_id=PLAYER_ID)
    local_space_id = "local:test"
    sim.state.world.spaces[local_space_id] = SpaceState(
        space_id=local_space_id,
        topology_type="square_grid",
        role=LOCAL_SPACE_ROLE,
        topology_params={"width": 6, "height": 6, "origin": {"x": 0, "y": 0}},
    )
    player_x, player_y = square_grid_cell_to_world_xy(1, 1)
    sim.state.entities[PLAYER_ID].space_id = local_space_id
    sim.state.entities[PLAYER_ID].position_x = player_x
    sim.state.entities[PLAYER_ID].position_y = player_y

    hostile_x, hostile_y = square_grid_cell_to_world_xy(2, 1)
    sim.add_entity(
        EntityState(
            entity_id="hostile:test",
            position_x=hostile_x,
            position_y=hostile_y,
            space_id=local_space_id,
            template_id=LOCAL_ENCOUNTER_HOSTILE_TEMPLATE_ID,
        )
    )

    monkeypatch.setattr(viewer_module, "_selected_entity_for_click", lambda *args, **kwargs: "hostile:test")
    status = _queue_local_attack_for_click(
        sim,
        controller,
        pixel_pos=(0, 0),
        center=(0.0, 0.0),
        zoom_scale=1.0,
    )

    assert status == "attack queued -> hostile:test"
    assert sim.input_log[-2].command_type == ATTACK_INTENT_COMMAND_TYPE
    assert sim.input_log[-2].params["target_id"] == "hostile:test"
    assert sim.input_log[-1].command_type == "set_selected_entity"
    assert sim.input_log[-1].params["selected_entity_id"] == "hostile:test"


def test_calendar_presentation_uses_master_tick_axis() -> None:
    sim = _build_viewer_simulation("content/examples/basic_map.json", with_encounters=False)
    sim.state.time.ticks_per_day = 240
    sim.state.time.epoch_tick = 0
    sim.state.tick = 0

    assert _calendar_presentation(sim) == {
        "day": 1,
        "hour": 0,
        "minute": 0,
        "day_night": "night",
        "month_name": "Deepfrost",
        "day_of_month": 1,
        "moon_phase": "new",
    }

    sim.state.tick = 240
    next_day = _calendar_presentation(sim)
    assert next_day["day"] == 2
    assert next_day["hour"] == 0
    assert next_day["day_of_month"] == 2
    assert next_day["month_name"] == "Deepfrost"


def test_simulation_controller_appends_encounter_offer_commands() -> None:
    sim = _build_viewer_simulation("content/examples/basic_map.json", with_encounters=False)
    controller = SimulationController(sim=sim, entity_id=PLAYER_ID)

    controller.accept_encounter_offer()
    controller.flee_encounter_offer()

    assert sim.input_log[-2].command_type == ACCEPT_ENCOUNTER_OFFER_INTENT
    assert sim.input_log[-2].params == {"entity_id": PLAYER_ID}
    assert sim.input_log[-1].command_type == FLEE_ENCOUNTER_OFFER_INTENT
    assert sim.input_log[-1].params == {"entity_id": PLAYER_ID}


def test_simulation_controller_appends_home_service_commands() -> None:
    sim = _build_viewer_simulation("content/examples/viewer_map.json", with_encounters=False)
    controller = SimulationController(sim=sim, entity_id=PLAYER_ID)

    controller.safe_recovery_intent()
    controller.turn_in_reward_token_intent()

    assert sim.input_log[-2].command_type == "safe_recovery_intent"
    assert sim.input_log[-2].entity_id == PLAYER_ID
    assert sim.input_log[-1].command_type == "turn_in_reward_token_intent"
    assert sim.input_log[-1].entity_id == PLAYER_ID


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

    monkeypatch.setattr(viewer_module, "_find_entity_at_pixel", lambda *_args, **_kwargs: None)
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


def test_world_marker_placements_do_not_include_player_entity_marker_dot() -> None:
    sim = _build_viewer_simulation("content/examples/basic_map.json", with_encounters=False)

    placements = _world_marker_placements(sim, (200.0, 200.0), zoom_scale=1.0)

    assert all(placement.marker.marker_id != f"entity:{PLAYER_ID}" for placement in placements)

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




def test_viewer_runtime_pending_offer_decision_accept_resolves_while_auto_advance_paused() -> None:
    sim = _build_viewer_simulation("content/examples/basic_map.json", with_encounters=True, seed=77)
    state = ViewerRuntimeState(
        sim=sim,
        map_path="content/examples/basic_map.json",
        with_encounters=True,
        current_save_path="saves/session_save.json",
        paused=True,
    )
    runtime = ViewerRuntimeController(state)

    danger = sim.state.entities["danger:raider_patrol_alpha"]
    player = sim.state.entities[PLAYER_ID]
    player.position_x = danger.position_x
    player.position_y = danger.position_y
    sim.advance_ticks(2)

    assert viewer_module._single_player_offer_pause(sim) is True
    runtime.controller.accept_encounter_offer()
    advanced = runtime.resolve_pending_offer_decision()

    control = sim.get_rules_state("campaign_danger").get("encounter_control_by_player", {}).get(PLAYER_ID, {})
    assert advanced >= 1
    assert viewer_module._single_player_offer_pause(sim) is False
    assert control.get("state") in {"accepted_loading", "in_local"}


def test_viewer_runtime_pending_offer_decision_flee_resolves_without_retrigger() -> None:
    sim = _build_viewer_simulation("content/examples/basic_map.json", with_encounters=True, seed=78)
    state = ViewerRuntimeState(
        sim=sim,
        map_path="content/examples/basic_map.json",
        with_encounters=True,
        current_save_path="saves/session_save.json",
        paused=True,
    )
    runtime = ViewerRuntimeController(state)

    danger = sim.state.entities["danger:raider_patrol_alpha"]
    player = sim.state.entities[PLAYER_ID]
    player.position_x = danger.position_x
    player.position_y = danger.position_y
    sim.advance_ticks(2)

    assert viewer_module._single_player_offer_pause(sim) is True
    runtime.controller.flee_encounter_offer()
    advanced = runtime.resolve_pending_offer_decision()

    state_after = sim.get_rules_state("campaign_danger")
    control = state_after.get("encounter_control_by_player", {}).get(PLAYER_ID, {})
    assert advanced >= 1
    assert viewer_module._single_player_offer_pause(sim) is False
    assert control.get("state") == "post_encounter_cooldown"
    assert state_after.get("pending_offer_by_player", {}).get(PLAYER_ID) is None


def test_viewer_runtime_pending_offer_decision_step_is_bounded() -> None:
    sim = _build_viewer_simulation("content/examples/basic_map.json", with_encounters=True, seed=79)
    state = ViewerRuntimeState(
        sim=sim,
        map_path="content/examples/basic_map.json",
        with_encounters=True,
        current_save_path="saves/session_save.json",
    )
    runtime = ViewerRuntimeController(state)

    danger = sim.state.entities["danger:raider_patrol_alpha"]
    player = sim.state.entities[PLAYER_ID]
    player.position_x = danger.position_x
    player.position_y = danger.position_y
    sim.advance_ticks(2)
    assert viewer_module._single_player_offer_pause(sim) is True

    advanced = runtime.resolve_pending_offer_decision(tick_cap=3)

    assert advanced == 3
    assert viewer_module._single_player_offer_pause(sim) is True
    control = sim.get_rules_state(CampaignDangerModule.name).get("encounter_control_by_player", {}).get(PLAYER_ID, {})
    assert control.get("state") == "pending_offer"
    assert PENDING_OFFER_DECISION_TICK_CAP >= 3



def test_viewer_runtime_local_contact_and_return_smoke_slice() -> None:
    sim = _build_viewer_simulation("content/examples/basic_map.json", with_encounters=True, seed=91)
    state = ViewerRuntimeState(
        sim=sim,
        map_path="content/examples/basic_map.json",
        with_encounters=True,
        current_save_path="saves/session_save.json",
        paused=True,
    )
    runtime = ViewerRuntimeController(state)

    danger = sim.state.entities["danger:raider_patrol_alpha"]
    player = sim.state.entities[PLAYER_ID]
    player.position_x = danger.position_x
    player.position_y = danger.position_y
    sim.advance_ticks(2)

    runtime.controller.accept_encounter_offer()
    advanced = runtime.resolve_pending_offer_decision()
    assert advanced >= 1

    begin_events = [
        entry for entry in sim.get_event_trace() if entry.get("event_type") == LOCAL_ENCOUNTER_BEGIN_EVENT_TYPE
    ]
    for _ in range(20):
        if begin_events:
            break
        runtime.advance_ticks(1)
        begin_events = [
            entry for entry in sim.get_event_trace() if entry.get("event_type") == LOCAL_ENCOUNTER_BEGIN_EVENT_TYPE
        ]
    assert begin_events
    begin = begin_events[-1]["params"]
    local_space_id = str(begin["to_space_id"])

    hostile_id = next(
        entity_id
        for entity_id, entity in sorted(sim.state.entities.items())
        if entity.space_id == local_space_id and entity.template_id == HOSTILE_TEMPLATE_ID
    )
    hostile = sim.state.entities[hostile_id]
    player = sim.state.entities[PLAYER_ID]
    hostile.position_x = player.position_x + 1.0
    hostile.position_y = player.position_y
    start_x = player.position_x

    for _ in range(10):
        runtime.controller.set_move_vector(1.0, 0.0)
        runtime.advance_ticks(1)

    assert sim.state.entities[PLAYER_ID].position_x > start_x
    assert any(
        row.get("attacker_id") == hostile_id and row.get("intent") == ATTACK_INTENT_COMMAND_TYPE
        for row in sim.state.combat_log
    )

    return_exit = begin["return_exit_coord"]
    exit_x, exit_y = square_grid_cell_to_world_xy(return_exit["x"], return_exit["y"])
    player = sim.state.entities[PLAYER_ID]
    player.position_x = exit_x
    player.position_y = exit_y
    hostile.position_x = player.position_x + 4.0
    hostile.position_y = player.position_y

    expected_origin_coord = dict(begin["from_location"]["coord"])
    runtime.controller.end_local_encounter()
    runtime.advance_ticks(4)

    return_events = [
        entry for entry in sim.get_event_trace() if entry.get("event_type") == LOCAL_ENCOUNTER_RETURN_EVENT_TYPE
    ]
    assert return_events
    assert return_events[-1]["params"]["applied"] is True
    assert sim._entity_location_ref(sim.state.entities[PLAYER_ID]).coord == expected_origin_coord


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


def test_viewer_runtime_controller_new_simulation_preserves_viewer_map_site_anchor_visibility() -> None:
    sim = _build_viewer_simulation("content/examples/viewer_map.json", with_encounters=False, seed=55)
    state = ViewerRuntimeState(
        sim=sim,
        map_path="content/examples/viewer_map.json",
        with_encounters=False,
        current_save_path="saves/session_save.json",
    )
    runtime = ViewerRuntimeController(state)
    center = (640.0, 360.0)

    before_ids = sorted(
        placement.marker.marker_id
        for placement in _world_marker_placements(state.sim, center=center, zoom_scale=1.0)
        if placement.marker.marker_kind == "site"
    )

    runtime.new_simulation(seed=55)

    after_ids = sorted(
        placement.marker.marker_id
        for placement in _world_marker_placements(state.sim, center=center, zoom_scale=1.0)
        if placement.marker.marker_kind == "site"
    )
    assert before_ids == after_ids
    assert "site:home_greybridge" in after_ids
    assert "site:demo_dungeon_entrance" in after_ids

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




def test_selected_entity_lines_include_loop_legibility_fields() -> None:
    sim = _build_viewer_simulation("content/examples/basic_map.json", with_encounters=False)
    scout = sim.state.entities[PLAYER_ID]
    scout.wounds = [{"severity": 1, "region": "torso"}]
    container_id = scout.inventory_container_id
    assert container_id is not None
    sim.state.world.containers[container_id].items["proof_token"] = 2
    sim.state.world.containers[container_id].items["rations"] = 3

    sim.state.world.sites["town:test"] = SiteRecord(
        site_id="town:test",
        site_type="town",
        location={"space_id": scout.space_id, "topology_type": OVERWORLD_HEX_TOPOLOGY, "coord": scout.hex_coord.to_dict()},
        tags=["safe"],
    )

    lines = _selected_entity_lines(sim, PLAYER_ID)

    assert any("Condition: slowed" in line for line in lines)
    assert any("Movement multiplier:" in line for line in lines)
    assert any("Safe site: yes" in line for line in lines)
    assert any("Inventory: proof_token=2 rations=3" in line for line in lines)


def test_player_feedback_lines_show_proof_gain_turn_in_and_attack_resolution() -> None:
    sim = _build_viewer_simulation("content/examples/basic_map.json", with_encounters=False)
    scout = sim.state.entities[PLAYER_ID]
    hostile = EntityState(entity_id="hostile:test", position_x=1.0, position_y=0.0, space_id=scout.space_id, template_id=HOSTILE_TEMPLATE_ID)
    hostile.wounds = [{"severity": 4, "region": "torso"}]
    sim.add_entity(hostile)

    sim.schedule_event_at(
        tick=sim.state.tick,
        event_type=LOCAL_ENCOUNTER_REWARD_EVENT_TYPE,
        params={
            "entity_id": PLAYER_ID,
            "applied": True,
            "reason": "token_granted",
            "details": {"quantity": 1, "incapacitated_hostiles": 1},
        },
    )
    sim.schedule_event_at(
        tick=sim.state.tick,
        event_type="reward_turn_in_outcome",
        params={
            "entity_id": PLAYER_ID,
            "applied": True,
            "reason": "reward_turned_in",
            "details": {"granted_item_id": "rations", "granted_quantity": 1},
        },
    )
    sim.schedule_event_at(
        tick=sim.state.tick,
        event_type="combat_outcome",
        params={
            "attacker_id": PLAYER_ID,
            "target_id": hostile.entity_id,
            "applied": True,
            "reason": "resolved",
        },
    )
    sim.advance_ticks(1)

    lines = _player_feedback_lines(sim, entity=scout)

    assert any("melee_state=ready" in line for line in lines)
    assert any("attack_available_in_ticks=0" in line for line in lines)
    assert any("PROOF TOKEN LOOTED +1" in line for line in lines)
    assert any("RATIONS GAINED +1" in line for line in lines)
    assert any("attack_feedback=HIT" in line and "neutralized=yes" in line for line in lines)


def test_player_feedback_lines_surface_target_moved_and_recovery_block_reasons() -> None:
    sim = _build_viewer_simulation("content/examples/basic_map.json", with_encounters=False)
    scout = sim.state.entities[PLAYER_ID]

    sim.schedule_event_at(
        tick=sim.state.tick,
        event_type="combat_outcome",
        params={
            "tick": sim.state.tick,
            "attacker_id": PLAYER_ID,
            "target_id": "hostile:test",
            "applied": False,
            "reason": "target_moved",
        },
    )
    sim.advance_ticks(1)

    lines = _player_feedback_lines(sim, entity=scout)
    assert any("attack_feedback=MISS" in line and "target_moved_before_strike" in line for line in lines)

    sim.schedule_event_at(
        tick=sim.state.tick,
        event_type="combat_outcome",
        params={
            "tick": sim.state.tick,
            "attacker_id": PLAYER_ID,
            "target_id": "hostile:test",
            "applied": False,
            "reason": "cooldown_blocked",
        },
    )
    sim.advance_ticks(1)

    lines = _player_feedback_lines(sim, entity=scout)
    assert any("attack_feedback=BLOCKED" in line and "reason=cooldown_blocked" in line for line in lines)


def test_player_feedback_lines_include_enemy_loop_line_in_local_space() -> None:
    sim = _build_viewer_simulation("content/examples/basic_map.json", with_encounters=False)
    scout = sim.state.entities[PLAYER_ID]
    local_space_id = "local:test_loop"
    sim.state.world.spaces[local_space_id] = SpaceState(
        space_id=local_space_id,
        topology_type="square_grid",
        role=LOCAL_SPACE_ROLE,
        topology_params={"width": 8, "height": 8, "origin": {"x": 0, "y": 0}},
    )
    scout.space_id = local_space_id
    scout.position_x = 1.0
    scout.position_y = 1.0

    hostile = EntityState(
        entity_id="hostile:nearby",
        position_x=3.0,
        position_y=1.0,
        space_id=local_space_id,
        template_id=HOSTILE_TEMPLATE_ID,
    )
    sim.add_entity(hostile)

    lines = _player_feedback_lines(sim, entity=scout)

    assert any("enemy_loop=approach enemy=hostile:nearby distance=2.00" in line for line in lines)


def test_context_menu_layout_wraps_long_rows_and_click_index_maps_correctly() -> None:
    viewer_module._ensure_pygame_imported()
    viewer_module.pygame.font.init()
    font = viewer_module.pygame.font.SysFont("consolas", 18)
    menu_state = viewer_module.ContextMenuState(
        pixel_x=24,
        pixel_y=24,
        items=(
            viewer_module.ContextMenuItem(
                label="Note: this is a minimal service panel; full town interior is not implemented yet.",
                action="noop",
            ),
            viewer_module.ContextMenuItem(label="Enter/Use Home Node", action="open_home_panel", payload="home_greybridge"),
        ),
    )
    viewport = viewer_module.pygame.Rect(0, 0, 1024, 768)

    _menu_rect, rows = _context_menu_layout(menu_state, font, viewport)

    assert len(rows) == 2
    assert rows[0].row_rect.height > CONTEXT_MENU_ROW_HEIGHT
    assert len(rows[0].lines) >= 2
    first_item_point = (rows[0].row_rect.x + 4, rows[0].row_rect.y + 4)
    second_item_point = (rows[1].row_rect.x + 4, rows[1].row_rect.y + 4)
    assert _context_menu_item_index_at_pixel(menu_state, font, viewport, first_item_point) == 0
    assert _context_menu_item_index_at_pixel(menu_state, font, viewport, second_item_point) == 1


def test_home_panel_lines_are_honest_and_show_home_service_availability() -> None:
    sim = _build_viewer_simulation("content/examples/viewer_map.json", with_encounters=False)
    player = sim.state.entities[PLAYER_ID]
    container_id = player.inventory_container_id
    assert container_id is not None
    sim.state.world.containers[container_id].items["proof_token"] = 1
    player.wounds = [{"severity": 1, "region": "arm"}]

    lines = _home_panel_lines(sim, entity=player)

    assert any("Greybridge Home Services (minimal node panel)" in line for line in lines)
    assert any("recover=AVAILABLE" in line for line in lines)
    assert any("turn_in_proof=AVAILABLE" in line for line in lines)
    assert any("town_interior=NOT_IMPLEMENTED" in line for line in lines)


def test_home_panel_button_rects_are_bounded_and_exposed() -> None:
    viewer_module._ensure_pygame_imported()
    sim = _build_viewer_simulation("content/examples/viewer_map.json", with_encounters=False)
    viewport = viewer_module.pygame.Rect(0, 0, 1280, 720)

    buttons = _home_panel_buttons_for_click(sim, viewport)

    assert set(buttons) == {"recover", "turn_in", "close"}
    assert all(viewport.contains(rect) for rect in buttons.values())


def test_pending_offer_modal_uses_source_and_title_fields() -> None:
    sim = _build_viewer_simulation("content/examples/basic_map.json", with_encounters=True)
    state = dict(sim.get_rules_state(CampaignDangerModule.name))
    state["pending_offer_by_player"] = {
        PLAYER_ID: {
            "player_entity_id": PLAYER_ID,
            "danger_entity_id": "danger:raider_patrol_alpha",
            "source_label": "raider patrol alpha",
            "encounter_label": "ambush at the creek",
            "context": "travel",
            "trigger": "contact",
            "category": "hostile",
            "table_id": "enc_table_primary",
            "entry_id": "wolves_1",
            "suggested_local_template_id": "local_square_test",
            "tick": sim.state.tick,
            "roll": 12,
            "tags": ["hostile"],
            "location": {"space_id": "overworld", "topology_type": OVERWORLD_HEX_TOPOLOGY, "coord": {"q": 0, "r": 0}},
        }
    }
    sim.set_rules_state(CampaignDangerModule.name, state)

    offer = viewer_module._pending_encounter_offer(sim)
    assert offer is not None
    assert offer["source_label"] == "raider patrol alpha"
    assert offer["encounter_label"] == "ambush at the creek"

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


def test_player_facing_hud_lines_are_compact_and_exclude_world_projection_diagnostics() -> None:
    sim = _build_viewer_simulation("content/examples/viewer_map.json", runtime_profile=CORE_PLAYABLE)
    runtime_state = ViewerRuntimeState(
        sim=sim,
        map_path="content/examples/viewer_map.json",
        with_encounters=True,
        current_save_path=None,
        runtime_profile=CORE_PLAYABLE,
    )

    lines = _player_facing_hud_lines(sim, entity=sim.state.entities[PLAYER_ID], runtime_state=runtime_state)

    assert any(line.startswith("condition=") for line in lines)
    assert any(line.startswith("melee_state=") for line in lines)
    assert any("OUTSIDE Greybridge on campaign map" in line for line in lines)
    assert any("proof_token=" in line and "rations=" in line for line in lines)
    assert any(line.startswith("time ") for line in lines)
    assert all("player_world=" not in line for line in lines)
    assert all("screen=(" not in line for line in lines)
    assert all("campaign_sites loaded=" not in line for line in lines)


def test_hub_markers_include_explicit_watch_hall_and_infirmary_labels() -> None:
    sim = _build_viewer_simulation("content/examples/viewer_map.json", runtime_profile=CORE_PLAYABLE)
    sim.append_command(SimCommand(tick=sim.state.tick, entity_id=PLAYER_ID, command_type=ENTER_SAFE_HUB_INTENT_COMMAND_TYPE, params={"site_id": "home_greybridge"}))
    sim.advance_ticks(1)

    placements = _world_marker_placements(sim, center=(640.0, 360.0), zoom_scale=1.0)
    labels = {row.marker.label for row in placements if row.marker.marker_kind == "interactable"}
    assert any("Watch Hall" in label for label in labels)
    assert any("Inn/Infirmary" in label for label in labels)
    assert any("Gate" in label for label in labels)


def test_nearest_lootable_hostile_only_returns_incapacitated_unlooted_target() -> None:
    sim = _build_viewer_simulation("content/examples/basic_map.json", with_encounters=False)
    local_space_id = "local:test"
    sim.state.world.spaces[local_space_id] = SpaceState(
        space_id=local_space_id,
        topology_type="square_grid",
        role=LOCAL_SPACE_ROLE,
        topology_params={"width": 8, "height": 8, "origin": {"x": 0, "y": 0}},
    )
    player = sim.state.entities[PLAYER_ID]
    player.space_id = local_space_id
    player.position_x, player.position_y = square_grid_cell_to_world_xy(1, 1)

    loot_x, loot_y = square_grid_cell_to_world_xy(2, 1)
    sim.add_entity(
        EntityState(
                entity_id="hostile:lootable",
            position_x=loot_x,
            position_y=loot_y,
            space_id=local_space_id,
            template_id=LOCAL_ENCOUNTER_HOSTILE_TEMPLATE_ID,
                wounds=[{"severity": 4, "region": "torso"}],
            stats={},
        )
    )
    spent_x, spent_y = square_grid_cell_to_world_xy(1, 2)
    sim.add_entity(
        EntityState(
            entity_id="hostile:spent",
            position_x=spent_x,
            position_y=spent_y,
            space_id=local_space_id,
                template_id=LOCAL_ENCOUNTER_HOSTILE_TEMPLATE_ID,
                wounds=[{"severity": 4, "region": "torso"}],
            stats={"proof_looted": True},
        )
    )

    selected = _nearest_lootable_hostile_for_player(sim, entity=player)
    assert selected is not None
    assert selected.entity_id == "hostile:lootable"


def test_spatial_context_actions_expose_loot_and_hub_interactions_as_intents() -> None:
    sim = _build_viewer_simulation("content/examples/viewer_map.json", runtime_profile=CORE_PLAYABLE)
    sim.append_command(SimCommand(tick=sim.state.tick, entity_id=PLAYER_ID, command_type=ENTER_SAFE_HUB_INTENT_COMMAND_TYPE, params={"site_id": "home_greybridge"}))
    sim.advance_ticks(1)
    player = sim.state.entities[PLAYER_ID]

    player.position_x, player.position_y = square_grid_cell_to_world_xy(10, 3)
    actions = _spatial_context_actions(sim, player=player)
    assert any(row.action == "home_turn_in" for row in actions)

    player.position_x, player.position_y = square_grid_cell_to_world_xy(10, 7)
    actions = _spatial_context_actions(sim, player=player)
    assert any(row.action == "home_recover" for row in actions)

    player.position_x, player.position_y = square_grid_cell_to_world_xy(1, 5)
    actions = _spatial_context_actions(sim, player=player)
    assert any(row.action == "exit_safe_hub" for row in actions)

    local_space_id = "local:test_loot_actions"
    sim.state.world.spaces[local_space_id] = SpaceState(
        space_id=local_space_id,
        topology_type="square_grid",
        role=LOCAL_SPACE_ROLE,
        topology_params={"width": 6, "height": 6, "origin": {"x": 0, "y": 0}},
    )
    player.space_id = local_space_id
    player.position_x, player.position_y = square_grid_cell_to_world_xy(1, 1)
    loot_x, loot_y = square_grid_cell_to_world_xy(2, 1)
    sim.add_entity(
        EntityState(
            entity_id="hostile:loot-menu",
            position_x=loot_x,
            position_y=loot_y,
            space_id=local_space_id,
            template_id=LOCAL_ENCOUNTER_HOSTILE_TEMPLATE_ID,
            wounds=[{"severity": 4, "region": "torso"}],
            stats={},
        )
    )
    actions = _spatial_context_actions(sim, player=player)
    assert any(row.action == "loot_local_proof" for row in actions)


def test_debug_sites_rows_include_major_site_and_patrol_scene_diagnostics() -> None:
    sim = _build_viewer_simulation("content/examples/viewer_map.json", runtime_profile=CORE_PLAYABLE)

    rows = _debug_rows_by_section(sim, RumorPanelState(), DebugFilterState())
    sites_rows = rows["sites"]

    assert any(row.startswith("campaign_player world=") for row in sites_rows)
    assert any("campaign_major_site id=home_greybridge" in row for row in sites_rows)
    assert any("campaign_major_site id=demo_dungeon_entrance" in row for row in sites_rows)
    assert any("campaign_patrol id=" in row and "template=campaign_danger_patrol" in row for row in sites_rows)


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
    assert any("pressure_summary total=4 dominant=faction:ash dominant_strength=4 records=1" in row for row in rows["sites"])
    assert any("pressure_records=1 showing_recent=1" in row for row in rows["sites"])
    assert any(
        "pressure faction=faction:ash type=raid strength=4 tick=12 source=evt-12" in row
        for row in rows["sites"]
    )




def test_debug_sites_pressure_summary_row_is_stable_for_empty_sites() -> None:
    sim = _build_viewer_simulation("content/examples/basic_map.json", with_encounters=False)
    player = sim.state.entities[PLAYER_ID]
    sim.state.world.sites["empty-pressure-site"] = SiteRecord(
        site_id="empty-pressure-site",
        site_type="town",
        location={"space_id": player.space_id, "coord": {"x": 0, "y": 0}},
        site_state=SiteWorldState(),
    )
    rumor_state = RumorPanelState()
    debug_filter_state = DebugFilterState()

    rows = _debug_rows_by_section(sim, rumor_state, debug_filter_state)

    assert any("site_id=empty-pressure-site" in row for row in rows["sites"])
    assert any("pressure_summary total=0 dominant=none dominant_strength=0 records=0" in row for row in rows["sites"])


def test_debug_sites_pressure_summary_row_uses_deterministic_dominance_tie_break() -> None:
    sim = _build_viewer_simulation("content/examples/basic_map.json", with_encounters=False)
    player = sim.state.entities[PLAYER_ID]
    sim.state.world.sites["pressure-summary-site"] = SiteRecord(
        site_id="pressure-summary-site",
        site_type="town",
        location={"space_id": player.space_id, "coord": {"x": 0, "y": 0}},
        site_state=SiteWorldState(
            pressure_records=[
                SitePressureRecord(faction_id="faction:zeta", pressure_type="claim", strength=3, tick=1),
                SitePressureRecord(faction_id="faction:alpha", pressure_type="claim", strength=3, tick=2),
            ]
        ),
    )
    rumor_state = RumorPanelState()
    debug_filter_state = DebugFilterState()

    rows = _debug_rows_by_section(sim, rumor_state, debug_filter_state)

    assert any("pressure_summary total=6 dominant=faction:alpha dominant_strength=3 records=2" in row for row in rows["sites"])

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


def test_debug_sites_rows_include_site_evidence_expression() -> None:
    sim = _build_viewer_simulation("content/examples/basic_map.json", with_encounters=False)
    player = sim.state.entities[PLAYER_ID]
    sim.state.world.sites["evidence-site"] = SiteRecord(
        site_id="evidence-site",
        site_type="town",
        location={"space_id": player.space_id, "coord": {"x": 0, "y": 0}},
        site_state=SiteWorldState(
            evidence_records=[
                EvidenceRecord(
                    evidence_type="tracks",
                    strength=3,
                    tick=14,
                    faction_id="faction:ash",
                    source_event_id="evt-14",
                )
            ]
        ),
    )
    rumor_state = RumorPanelState()
    debug_filter_state = DebugFilterState()

    rows = _debug_rows_by_section(sim, rumor_state, debug_filter_state)

    assert any("site_id=evidence-site" in row for row in rows["sites"])
    assert any("evidence_records=1 showing_recent=1" in row for row in rows["sites"])
    assert any(
        "evidence type=tracks strength=3 tick=14 faction=faction:ash source=evt-14" in row
        for row in rows["sites"]
    )


def test_debug_sites_evidence_rows_use_deterministic_recent_tail_order() -> None:
    sim = _build_viewer_simulation("content/examples/basic_map.json", with_encounters=False)
    player = sim.state.entities[PLAYER_ID]
    sim.state.world.sites["evidence-order-site"] = SiteRecord(
        site_id="evidence-order-site",
        site_type="town",
        location={"space_id": player.space_id, "coord": {"x": 0, "y": 0}},
        site_state=SiteWorldState(
            evidence_records=[
                EvidenceRecord(
                    evidence_type=f"type:{i}",
                    strength=i,
                    tick=i,
                    faction_id=(None if i % 2 == 0 else f"faction:{i}"),
                    source_event_id=(None if i % 3 else f"evt-{i}"),
                )
                for i in range(7)
            ]
        ),
    )
    rumor_state = RumorPanelState()
    debug_filter_state = DebugFilterState()

    rows = _debug_rows_by_section(sim, rumor_state, debug_filter_state)
    evidence_rows = [row for row in rows["sites"] if row.startswith("evidence type=")]

    assert any("evidence_records=7 showing_recent=5" in row for row in rows["sites"])
    assert evidence_rows == [
        "evidence type=type:6 strength=6 tick=6 faction=- source=evt-6",
        "evidence type=type:5 strength=5 tick=5 faction=faction:5 source=-",
        "evidence type=type:4 strength=4 tick=4 faction=- source=-",
        "evidence type=type:3 strength=3 tick=3 faction=faction:3 source=evt-3",
        "evidence type=type:2 strength=2 tick=2 faction=- source=-",
    ]


def test_debug_sites_evidence_expression_does_not_mutate_simulation() -> None:
    sim = _build_viewer_simulation("content/examples/basic_map.json", with_encounters=False)
    player = sim.state.entities[PLAYER_ID]
    sim.state.world.sites["evidence-safe-site"] = SiteRecord(
        site_id="evidence-safe-site",
        site_type="town",
        location={"space_id": player.space_id, "coord": {"x": 0, "y": 0}},
        site_state=SiteWorldState(
            evidence_records=[
                EvidenceRecord(evidence_type="burns", strength=2, tick=9),
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


def test_world_marker_placements_do_not_duplicate_local_hostile_marker_dot() -> None:
    sim = _build_viewer_simulation("content/examples/basic_map.json", with_encounters=False)
    sim.state.entities["hostile:test"] = EntityState(
        entity_id="hostile:test",
        position_x=sim.state.entities[PLAYER_ID].position_x + 1.0,
        position_y=sim.state.entities[PLAYER_ID].position_y,
        space_id=sim.state.entities[PLAYER_ID].space_id,
        template_id="encounter_hostile_v1",
    )

    placements = _world_marker_placements(sim, (200.0, 200.0), zoom_scale=1.0)

    assert all(placement.marker.marker_id != "entity:hostile:test" for placement in placements)


def test_viewer_runtime_controller_new_sim_uses_runtime_profile_bootstrap_parity() -> None:
    sim = _build_viewer_simulation("content/examples/basic_map.json", runtime_profile=EXPERIMENTAL_WORLD, seed=91)
    state = ViewerRuntimeState(
        sim=sim,
        map_path="content/examples/basic_map.json",
        with_encounters=False,
        current_save_path="saves/session_save.json",
        runtime_profile=EXPERIMENTAL_WORLD,
    )
    runtime = ViewerRuntimeController(state)

    replaced = runtime.new_simulation(seed=91)

    assert replaced.get_rule_module(EncounterCheckModule.name) is not None


def test_viewer_runtime_controller_load_uses_runtime_profile_bootstrap_parity(tmp_path: Path) -> None:
    baseline = _build_viewer_simulation("content/examples/basic_map.json", runtime_profile=CORE_PLAYABLE, seed=77)
    save_path = tmp_path / "runtime_profile_parity_load.json"
    _save_viewer_simulation(baseline, str(save_path))

    state = ViewerRuntimeState(
        sim=_build_viewer_simulation("content/examples/basic_map.json", runtime_profile=EXPERIMENTAL_WORLD, seed=78),
        map_path="content/examples/basic_map.json",
        with_encounters=False,
        current_save_path=str(save_path),
        runtime_profile=CORE_PLAYABLE,
    )
    runtime = ViewerRuntimeController(state)

    loaded = runtime.load_simulation(str(save_path))

    assert loaded.get_rule_module(EncounterCheckModule.name) is not None
