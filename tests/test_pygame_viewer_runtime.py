import pygame
from types import SimpleNamespace

from hexcrawler.cli.pygame_viewer import (
    FOLLOW_STATUS_INACTIVE,
    FOLLOW_STATUS_OFF,
    FOLLOW_STATUS_ON,
    HEX_SIZE,
    LOCAL_INTERPOLATION_SNAP_DISTANCE,
    PLAYER_ID,
    FollowSelectionState,
    RenderEntitySnapshot,
    _display_heading_angle_from_motion,
    _apply_follow_selected_camera,
    _build_viewer_simulation,
    compute_interpolation_alpha,
    _drain_sim_accumulator,
    _focus_camera_on_selected,
    interpolate_entity_position,
    _single_player_offer_pause,
    _selected_entity_lines,
)
from hexcrawler.sim.core import EntityState
from hexcrawler.sim.hash import simulation_hash, world_hash


def test_compute_interpolation_alpha_uses_eased_curve() -> None:
    alpha = compute_interpolation_alpha(elapsed_seconds=0.05, tick_duration_seconds=0.1)

    assert alpha == 0.5


def test_interpolate_entity_position_snaps_small_deltas_to_current() -> None:
    prev_snapshot = {"scout": SimpleNamespace(x=1.0, y=2.0)}
    curr_snapshot = {"scout": SimpleNamespace(x=1.0 + (LOCAL_INTERPOLATION_SNAP_DISTANCE * 0.5), y=2.0)}

    interpolated = interpolate_entity_position(prev_snapshot, curr_snapshot, "scout", alpha=0.1)

    assert interpolated == (curr_snapshot["scout"].x, curr_snapshot["scout"].y)


def test_display_heading_fallback_prevents_quantization_on_reentry_reset() -> None:
    prior_heading = 0.77
    snapshot = {"scout": RenderEntitySnapshot(x=4.0, y=5.0)}
    held = _display_heading_angle_from_motion(
        previous_snapshot=snapshot,
        current_snapshot=snapshot,
        entity_id="scout",
        fallback_angle=prior_heading,
    )
    assert held == prior_heading


def test_drain_sim_accumulator_handles_invalid_values() -> None:
    remaining, ticks = _drain_sim_accumulator(float('nan'), 0.1, paused=False)
    assert remaining == 0.0
    assert ticks == 0


def test_drain_sim_accumulator_running_batches_ticks() -> None:
    remaining, ticks = _drain_sim_accumulator(0.45, 0.1, paused=False)
    assert ticks == 4
    assert 0.049 <= remaining <= 0.051


def test_focus_camera_on_selected_centers_active_space_entity() -> None:
    sim = _build_viewer_simulation("content/examples/basic_map.json", with_encounters=False)
    entity = EntityState(entity_id="observer:focus", position_x=3.0, position_y=-2.0, space_id="overworld")
    sim.add_entity(entity)

    viewport = pygame.Rect(0, 0, 1000, 600)
    center, message = _focus_camera_on_selected(sim, entity.entity_id, viewport, zoom_scale=1.0)

    assert center == (500.0 - (3.0 * HEX_SIZE), 300.0 - (-2.0 * HEX_SIZE))
    assert message == "focus selected: observer:focus"


def test_follow_toggle_is_viewer_local_and_non_mutating() -> None:
    sim = _build_viewer_simulation("content/examples/basic_map.json", with_encounters=False)
    entity = EntityState(entity_id="observer:follow", position_x=1.0, position_y=1.0, space_id="overworld")
    sim.add_entity(entity)
    follow_state = FollowSelectionState(enabled=True)

    viewport = pygame.Rect(0, 0, 800, 500)
    world_before = world_hash(sim.state.world)
    sim_hash_before = simulation_hash(sim)
    input_before = len(sim.input_log)

    center, message = _apply_follow_selected_camera(
        sim,
        entity.entity_id,
        viewport,
        zoom_scale=1.0,
        follow_state=follow_state,
    )

    assert center is not None
    assert message is None
    assert follow_state.status == FOLLOW_STATUS_ON
    assert world_hash(sim.state.world) == world_before
    assert simulation_hash(sim) == sim_hash_before
    assert len(sim.input_log) == input_before


def test_follow_tracks_selected_entity_movement_in_active_space() -> None:
    sim = _build_viewer_simulation("content/examples/basic_map.json", with_encounters=False)
    entity = EntityState(entity_id="observer:track", position_x=0.0, position_y=0.0, space_id="overworld")
    sim.add_entity(entity)
    follow_state = FollowSelectionState(enabled=True)
    viewport = pygame.Rect(0, 0, 1000, 600)

    center_a, _ = _apply_follow_selected_camera(
        sim,
        entity.entity_id,
        viewport,
        zoom_scale=1.0,
        follow_state=follow_state,
    )
    entity.position_x = 4.0
    entity.position_y = 2.5
    center_b, _ = _apply_follow_selected_camera(
        sim,
        entity.entity_id,
        viewport,
        zoom_scale=1.0,
        follow_state=follow_state,
    )

    assert center_a != center_b
    assert center_b == (500.0 - (4.0 * HEX_SIZE), 300.0 - (2.5 * HEX_SIZE))


def test_follow_fails_soft_for_missing_or_out_of_space_selection() -> None:
    sim = _build_viewer_simulation("content/examples/basic_map.json", with_encounters=False)
    follow_state = FollowSelectionState(enabled=True)
    viewport = pygame.Rect(0, 0, 900, 700)

    center_missing, message_missing = _apply_follow_selected_camera(
        sim,
        "missing:entity",
        viewport,
        zoom_scale=1.0,
        follow_state=follow_state,
    )
    assert center_missing is None
    assert message_missing == "follow selected: inactive"
    assert follow_state.enabled is False
    assert follow_state.status == FOLLOW_STATUS_INACTIVE

    local_entity = EntityState(entity_id="observer:local", position_x=1.0, position_y=1.0, space_id="local:other")
    sim.add_entity(local_entity)
    follow_state.enabled = True
    center_other, message_other = _apply_follow_selected_camera(
        sim,
        local_entity.entity_id,
        viewport,
        zoom_scale=1.0,
        follow_state=follow_state,
    )
    assert center_other is None
    assert message_other == "follow selected: inactive"
    assert follow_state.status == FOLLOW_STATUS_INACTIVE


def test_follow_off_state_reports_off_without_camera_changes() -> None:
    sim = _build_viewer_simulation("content/examples/basic_map.json", with_encounters=False)
    follow_state = FollowSelectionState(enabled=False, status=FOLLOW_STATUS_ON)
    viewport = pygame.Rect(0, 0, 640, 360)

    center, message = _apply_follow_selected_camera(
        sim,
        PLAYER_ID,
        viewport,
        zoom_scale=1.0,
        follow_state=follow_state,
    )

    assert center is None
    assert message is None
    assert follow_state.status == FOLLOW_STATUS_OFF


def test_single_player_offer_pause_detects_pending_offer_state() -> None:
    sim = _build_viewer_simulation("content/examples/basic_map.json", with_encounters=True)
    assert _single_player_offer_pause(sim) is False

    state = sim.get_rules_state("campaign_danger")
    state["pending_offer_by_player"] = {
        PLAYER_ID: {
            "player_entity_id": PLAYER_ID,
            "danger_entity_id": "danger:test",
            "source_label": "test source",
            "encounter_label": "test encounter",
            "context": "campaign",
            "trigger": "contact",
            "category": "hostile",
            "table_id": "table",
            "entry_id": "entry",
            "suggested_local_template_id": "local_template_forest",
            "tick": 0,
            "roll": 1,
            "tags": [],
            "location": {
                "space_id": "overworld",
                "topology_type": "overworld_hex",
                "coord": {"q": 0, "r": 0},
            },
        }
    }
    sim.set_rules_state("campaign_danger", state)
    assert _single_player_offer_pause(sim) is True


def test_selected_entity_lines_show_explicit_incapacitated_state() -> None:
    sim = _build_viewer_simulation("content/examples/basic_map.json", with_encounters=False)
    player = sim.state.entities[PLAYER_ID]
    player.wounds = [
        {"severity": 1, "region": "torso"},
        {"severity": 1, "region": "leg"},
        {"severity": 1, "region": "arm"},
        {"severity": 1, "region": "head"},
    ]

    lines = _selected_entity_lines(sim, PLAYER_ID, follow_status=FOLLOW_STATUS_OFF)

    assert any("Incapacitated: YES" in line for line in lines)
    assert any("severity_total=4" in line for line in lines)
