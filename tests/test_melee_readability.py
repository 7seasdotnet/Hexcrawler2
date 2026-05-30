import copy

import pytest

import hexcrawler.cli.pygame_viewer as viewer_module
from hexcrawler.cli.pygame_viewer import PLAYER_ID
from hexcrawler.sim.combat import ATTACK_INTENT_COMMAND_TYPE, CombatExecutionModule
from hexcrawler.sim.core import EntityState, SimCommand, Simulation
from hexcrawler.sim.hash import simulation_hash, world_hash
from hexcrawler.sim.location import SQUARE_GRID_TOPOLOGY
from hexcrawler.sim.world import LOCAL_SPACE_ROLE, SpaceState, WorldState


def _local_sim() -> Simulation:
    world = WorldState()
    world.spaces["local:readability"] = SpaceState(
        space_id="local:readability",
        topology_type=SQUARE_GRID_TOPOLOGY,
        role=LOCAL_SPACE_ROLE,
        topology_params={"width": 4, "height": 3, "origin": {"x": 0, "y": 0}},
    )
    sim = Simulation(world=world, seed=17)
    sim.register_rule_module(CombatExecutionModule())
    player = EntityState(entity_id=PLAYER_ID, position_x=1.0, position_y=1.0, speed_per_tick=0.0, space_id="local:readability")
    target = EntityState(entity_id="hostile:dummy", position_x=2.0, position_y=1.0, speed_per_tick=0.0, space_id="local:readability")
    sim.add_entity(player)
    sim.add_entity(target)
    return sim


def test_slash_motion_grammar_samples_arc_from_attacker_to_target_edge() -> None:
    origin, contact, reaches_edge = viewer_module._melee_arc_anchor_points_local(
        attacker_position=(1.0, 1.0),
        target_position=(2.0, 1.0),
        committed_facing=(1.0, 0.0),
        target_source="target_id",
    )
    points = viewer_module._sample_melee_motion_points_local(
        arc_origin_local=origin,
        arc_contact_local=contact,
        committed_facing=(1.0, 0.0),
        motion_family="slash",
    )

    assert reaches_edge is True
    assert len(points) >= 7
    assert origin[0] == pytest.approx(1.24, abs=0.02)
    assert contact[0] == pytest.approx(1.78, abs=0.02)
    assert points[0] == pytest.approx(origin)
    assert points[-1] == pytest.approx(contact)
    assert max(y for _x, y in points) - min(y for _x, y in points) > 0.10


def test_slash_visible_phases_reveal_motion_without_changing_canonical_samples() -> None:
    origin, contact, _ = viewer_module._melee_arc_anchor_points_local(
        attacker_position=(1.0, 1.0),
        target_position=(2.0, 1.0),
        committed_facing=(1.0, 0.0),
        target_source="target_id",
    )
    full = viewer_module._sample_melee_motion_points_local(
        arc_origin_local=origin,
        arc_contact_local=contact,
        committed_facing=(1.0, 0.0),
        motion_family="slash",
    )

    assert len(viewer_module._phase_visible_motion_points(full, "windup")) < len(viewer_module._phase_visible_motion_points(full, "swing_mid_arc")) < len(full)
    assert viewer_module._phase_visible_motion_points(full, "impact") == full


def test_combat_cue_generation_is_viewer_local_and_hash_neutral() -> None:
    sim = _local_sim()
    sim.append_command(
        SimCommand(
            tick=0,
            entity_id=PLAYER_ID,
            command_type=ATTACK_INTENT_COMMAND_TYPE,
            params={
                "attacker_id": PLAYER_ID,
                "target_id": "hostile:dummy",
                "mode": "melee",
                "weapon_profile_id": "default_melee",
                "committed_aim": {"space_id": "local:readability", "x": 1.0, "y": 0.0, "facing": 0},
                "tags": ["test"],
            },
        )
    )
    sim.advance_ticks(3)
    sim_hash_before = simulation_hash(sim)
    world_hash_before = world_hash(sim.state.world)
    input_log_before = copy.deepcopy(sim.input_log)
    state = viewer_module.ViewerRuntimeState(sim=sim, map_path="m", with_encounters=False, current_save_path="s")

    viewer_module._refresh_combat_presentation_cues(sim, state)

    assert simulation_hash(sim) == sim_hash_before
    assert world_hash(sim.state.world) == world_hash_before
    assert sim.input_log == input_log_before
    assert state.combat_presentation_cues
    cue = state.combat_presentation_cues[-1]
    assert cue.presentation_target_source == "target_id"
    assert cue.arc_sample_count >= 7
    assert cue.arc_reaches_target_marker_edge is True


def test_default_melee_slash_motion_grammar_trace_and_phases() -> None:
    cue = viewer_module.CombatPresentationCue(
        attacker_id=PLAYER_ID,
        target_id="hostile:dummy",
        start_tick=10,
        impact_tick=12,
        outcome_label="WOUNDED",
        attacker_position=(1.0, 1.0),
        target_position=(2.0, 1.0),
        attack_vector_local=(1.0, 0.0),
        motion_family="slash",
        weapon_profile_id="default_melee",
        phase="swing_mid_arc",
        evidence_reason="resolved",
        evidence_applied=True,
        presentation_target_source="target_id",
        arc_origin_local=(1.24, 0.84),
        arc_contact_local=(1.78, 1.0),
        arc_sample_count=9,
        arc_reaches_target_marker_edge=True,
        cadence_tick_window=(10, 17),
    )
    trace = viewer_module._build_melee_motion_trace(cue, viewer_module.DEFAULT_WEAPON_MOTION_PROFILE)

    assert viewer_module.DEFAULT_MELEE_SLASH_GRAMMAR.motion_family == "slash"
    assert viewer_module.DEFAULT_MELEE_SLASH_GRAMMAR.phases == (
        "anticipation",
        "active",
        "contact",
        "follow_through",
        "recovery",
    )
    assert trace.phase == "active"
    assert trace.sample_count >= 9
    assert len(trace.active_edge_samples_local) == 2
    assert trace.presentation_target_source == "target_id"
    assert trace.cadence_tick_window == (10, 17)


def test_active_slash_reveal_fraction_increases_and_keeps_leading_edge() -> None:
    points = viewer_module._sample_melee_motion_points_local(
        arc_origin_local=(1.24, 0.84),
        arc_contact_local=(1.78, 1.0),
        committed_facing=(1.0, 0.0),
        motion_family="slash",
    )

    start = viewer_module._phase_visible_motion_points(points, "windup", start_tick=10, impact_tick=12, age_ticks=0)
    mid = viewer_module._phase_visible_motion_points(points, "swing_mid_arc", start_tick=10, impact_tick=12, age_ticks=1)
    contact = viewer_module._phase_visible_motion_points(points, "impact", start_tick=10, impact_tick=12, age_ticks=2)

    assert len(start) < len(mid) < len(contact)
    assert len(contact) == len(points)
    assert mid[-1] != points[-1]
    assert len(mid[-2:]) == 2


def test_threat_envelope_families_are_local_diagnostic_only_metadata() -> None:
    envelopes = {
        family: viewer_module.compute_melee_threat_envelope(
            (1.0, 1.0), (1.0, 0.0), family, reach=1.0, arc_degrees=90.0, sample_count=9
        )
        for family in ("slash", "thrust", "stab", "chop", "bash")
    }

    assert envelopes["slash"].envelope_kind == "front_sector_crescent"
    assert envelopes["thrust"].envelope_kind == "narrow_capsule"
    assert envelopes["stab"].envelope_kind == "narrow_capsule"
    assert envelopes["chop"].arc_degrees < envelopes["slash"].arc_degrees
    assert envelopes["bash"].reach == pytest.approx(1.0)
    assert all(len(envelope.samples_local) >= 2 for envelope in envelopes.values())
    assert viewer_module._point_inside_presentation_envelope((1.78, 1.0), envelopes["slash"]) is True


def test_contact_and_reaction_presentation_are_outcome_driven_and_bounded() -> None:
    cue = viewer_module.CombatPresentationCue(
        attacker_id=PLAYER_ID,
        target_id="hostile:dummy",
        start_tick=10,
        impact_tick=12,
        outcome_label="WOUNDED",
        attacker_position=(1.0, 1.0),
        target_position=(2.0, 1.0),
        attack_vector_local=(1.0, 0.0),
        motion_family="slash",
        weapon_profile_id="default_melee",
        phase="impact",
        evidence_reason="resolved",
        evidence_applied=True,
        presentation_target_source="target_id",
        arc_origin_local=(1.24, 0.84),
        arc_contact_local=(1.78, 1.0),
        arc_sample_count=9,
        arc_reaches_target_marker_edge=True,
    )
    points = viewer_module._sample_melee_motion_points_local(
        arc_origin_local=cue.arc_origin_local,
        arc_contact_local=cue.arc_contact_local,
        committed_facing=cue.attack_vector_local,
        motion_family="slash",
    )
    contact = viewer_module._contact_presentation_for_cue(cue, points)

    assert contact.contact_source == "target_edge"
    assert contact.contact_attached_to_arc is True
    assert contact.contact_dominates_cue is False
    assert viewer_module._target_reaction_type_for_outcome(reason="resolved", applied=True, neutralized=False) == "wound_pulse"
    assert viewer_module._target_reaction_type_for_outcome(reason="invalid_arc", applied=False, neutralized=False) == "block_deflect"
    assert viewer_module._target_reaction_type_for_outcome(reason="target_moved", applied=False, neutralized=False) == "miss_air"
    assert viewer_module._target_reaction_type_for_outcome(reason="cooldown_blocked", applied=False, neutralized=False) == "none"


def test_duplicate_rejected_input_produces_no_target_reaction() -> None:
    sim = _local_sim()
    state = viewer_module.ViewerRuntimeState(sim=sim, map_path="m", with_encounters=False, current_save_path="s")
    sim.append_command(
        SimCommand(
            tick=0,
            entity_id=PLAYER_ID,
            command_type=ATTACK_INTENT_COMMAND_TYPE,
            params={
                "attacker_id": PLAYER_ID,
                "target_id": "hostile:dummy",
                "mode": "melee",
                "weapon_profile_id": "default_melee",
                "committed_aim": {"space_id": "local:readability", "x": 1.0, "y": 0.0, "facing": 0},
            },
        )
    )
    sim.append_command(
        SimCommand(
            tick=0,
            entity_id=PLAYER_ID,
            command_type=ATTACK_INTENT_COMMAND_TYPE,
            params={
                "attacker_id": PLAYER_ID,
                "target_id": "hostile:dummy",
                "mode": "melee",
                "weapon_profile_id": "default_melee",
                "committed_aim": {"space_id": "local:readability", "x": 1.0, "y": 0.0, "facing": 0},
            },
        )
    )
    sim.advance_ticks(3)
    viewer_module._refresh_combat_presentation_cues(sim, state)

    applied_outcomes = [row for row in sim.state.combat_log if row.get("applied") is True]
    assert len(applied_outcomes) == 1
    assert len(state.target_reactions) == 1
    assert state.target_reactions[0].reaction_source_outcome_id.endswith(":resolved:1:0")
    assert state.last_combat_cue_refresh_diagnostics["reactions_generated_count"] == 1
    assert viewer_module.TargetReactionPresentation.__name__ not in str(sim.state.__dict__)


def _append_viewer_combat_log_outcome(
    sim: Simulation,
    *,
    tick: int,
    target_id: str = "hostile:dummy",
    reason: str = "resolved",
    applied: bool = True,
    neutralized: bool = False,
) -> None:
    sim.state.combat_log.append(
        {
            "tick": tick,
            "attacker_id": PLAYER_ID,
            "target_id": target_id,
            "reason": reason,
            "applied": applied,
            "neutralized": neutralized,
            "weapon_profile_id": "default_melee",
            "committed_aim": {"space_id": "local:readability", "x": 1.0, "y": 0.0, "facing": 0},
        }
    )


def test_repeated_cue_refresh_does_not_duplicate_target_reactions_for_same_outcome() -> None:
    sim = _local_sim()
    sim.state.tick = 3
    _append_viewer_combat_log_outcome(sim, tick=2)
    state = viewer_module.ViewerRuntimeState(sim=sim, map_path="m", with_encounters=False, current_save_path="s")

    viewer_module._refresh_combat_presentation_cues(sim, state)
    assert len(state.target_reactions) == 1
    first_source = state.target_reactions[0].reaction_source_outcome_id

    # Force a pathological re-read of the same authoritative evidence.  The
    # reaction key, not only the normal combat-log cursor, must suppress dupes.
    state.combat_cue_combat_log_cursor = 0
    state.seen_combat_cue_keys.clear()
    viewer_module._refresh_combat_presentation_cues(sim, state)

    assert len(state.target_reactions) == 1
    assert state.target_reactions[0].reaction_source_outcome_id == first_source
    assert state.last_combat_cue_refresh_diagnostics["duplicate_reactions_suppressed_count"] == 1


def test_distinct_authoritative_outcomes_may_spawn_distinct_target_reactions() -> None:
    sim = _local_sim()
    sim.state.tick = 4
    _append_viewer_combat_log_outcome(sim, tick=2, reason="resolved", applied=True)
    _append_viewer_combat_log_outcome(sim, tick=3, reason="invalid_arc", applied=False)
    state = viewer_module.ViewerRuntimeState(sim=sim, map_path="m", with_encounters=False, current_save_path="s")

    viewer_module._refresh_combat_presentation_cues(sim, state)

    assert [reaction.reaction_type for reaction in state.target_reactions] == ["wound_pulse", "block_deflect"]
    assert len({reaction.reaction_source_outcome_id for reaction in state.target_reactions}) == 2


def test_target_reaction_cap_and_lifetime_pruning_are_bounded() -> None:
    sim = _local_sim()
    state = viewer_module.ViewerRuntimeState(sim=sim, map_path="m", with_encounters=False, current_save_path="s")
    # All outcomes are within lifetime, so cap pruning should keep only the newest bounded window.
    sim.state.tick = 20
    for index in range(viewer_module.TARGET_REACTION_MAX + 3):
        _append_viewer_combat_log_outcome(sim, tick=20, target_id=f"hostile:dummy:{index}", reason="resolved", applied=True)

    viewer_module._refresh_combat_presentation_cues(sim, state)

    assert len(state.target_reactions) == viewer_module.TARGET_REACTION_MAX
    assert len(state.seen_target_reaction_keys) <= viewer_module.TARGET_REACTION_MAX * 4

    # Advance beyond the presentation lifetime; refresh should prune active viewer-only reactions.
    sim.state.tick = 40
    viewer_module._refresh_combat_presentation_cues(sim, state)

    assert state.target_reactions == []
    assert state.last_combat_cue_refresh_diagnostics["reaction_count_after_prune"] == 0


def test_target_reaction_state_stays_out_of_hash_input_log_and_replay_payloads() -> None:
    sim = _local_sim()
    sim.state.tick = 3
    _append_viewer_combat_log_outcome(sim, tick=2)
    input_log_before = copy.deepcopy(sim.input_log)
    payload_before = copy.deepcopy(sim.simulation_payload())
    sim_hash_before = simulation_hash(sim)
    world_hash_before = world_hash(sim.state.world)
    state = viewer_module.ViewerRuntimeState(sim=sim, map_path="m", with_encounters=False, current_save_path="s")

    viewer_module._refresh_combat_presentation_cues(sim, state)

    assert len(state.target_reactions) == 1
    assert sim.input_log == input_log_before
    assert sim.simulation_payload() == payload_before
    assert simulation_hash(sim) == sim_hash_before
    assert world_hash(sim.state.world) == world_hash_before
    assert "TargetReactionPresentation" not in str(sim.simulation_payload())
