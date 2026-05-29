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
