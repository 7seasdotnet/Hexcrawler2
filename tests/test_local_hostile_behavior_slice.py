from __future__ import annotations

from hexcrawler.content.io import load_world_json
from hexcrawler.sim.combat import ATTACK_INTENT_COMMAND_TYPE, CombatExecutionModule
from hexcrawler.sim.core import DEFAULT_PLAYER_ENTITY_ID, EntityState, SimCommand, Simulation
from hexcrawler.sim.encounters import (
    END_LOCAL_ENCOUNTER_INTENT,
    ENCOUNTER_RESOLVE_REQUEST_EVENT_TYPE,
    LOCAL_ENCOUNTER_BEGIN_EVENT_TYPE,
    LOCAL_ENCOUNTER_RETURN_EVENT_TYPE,
    LocalEncounterInstanceModule,
    LocalEncounterRequestModule,
)
from hexcrawler.sim.hash import simulation_hash
from hexcrawler.sim.local_hostiles import HOSTILE_TEMPLATE_ID, LocalHostileBehaviorModule
from hexcrawler.sim.location import SQUARE_GRID_TOPOLOGY
from hexcrawler.sim.movement import square_grid_cell_to_world_xy, world_xy_to_square_grid_cell
from hexcrawler.sim.world import CAMPAIGN_SPACE_ROLE, SpaceState
from hexcrawler.sim.wounds import movement_multiplier_from_wounds

CAMPAIGN_SPACE_ID = "campaign_plane_beta"


def _build_handoff_sim(seed: int = 77) -> Simulation:
    world = load_world_json("content/examples/basic_map.json")
    world.spaces[CAMPAIGN_SPACE_ID] = SpaceState(
        space_id=CAMPAIGN_SPACE_ID,
        topology_type=SQUARE_GRID_TOPOLOGY,
        role=CAMPAIGN_SPACE_ROLE,
        topology_params={"width": 6, "height": 6, "origin": {"x": 10, "y": 20}},
    )
    sim = Simulation(world=world, seed=seed)
    scout_x, scout_y = square_grid_cell_to_world_xy(12, 21)
    sim.add_entity(EntityState(entity_id=DEFAULT_PLAYER_ENTITY_ID, position_x=scout_x, position_y=scout_y, space_id=CAMPAIGN_SPACE_ID))
    sim.register_rule_module(LocalEncounterRequestModule())
    sim.register_rule_module(LocalEncounterInstanceModule())
    sim.register_rule_module(LocalHostileBehaviorModule())
    sim.register_rule_module(CombatExecutionModule())
    return sim


def _schedule_request(sim: Simulation) -> None:
    sim.schedule_event_at(
        tick=0,
        event_type=ENCOUNTER_RESOLVE_REQUEST_EVENT_TYPE,
        params={
            "tick": 0,
            "context": "global",
            "trigger": "travel",
            "location": {
                "space_id": CAMPAIGN_SPACE_ID,
                "topology_type": SQUARE_GRID_TOPOLOGY,
                "coord": {"x": 12, "y": 21},
            },
            "roll": 48,
            "category": "hostile",
            "table_id": "enc_table_primary",
            "entry_id": "wolves_1",
        },
    )


def _trace_by_type(sim: Simulation, event_type: str) -> list[dict]:
    return [entry for entry in sim.get_event_trace() if entry["event_type"] == event_type]


def test_local_handoff_spawns_hostile_and_behavior_is_deterministic() -> None:
    sim_a = _build_handoff_sim(seed=401)
    sim_b = _build_handoff_sim(seed=401)
    _schedule_request(sim_a)
    _schedule_request(sim_b)

    sim_a.advance_ticks(12)
    sim_b.advance_ticks(12)

    begin = _trace_by_type(sim_a, LOCAL_ENCOUNTER_BEGIN_EVENT_TYPE)[0]["params"]
    local_space_id = begin["to_space_id"]

    hostile_ids = sorted(
        entity_id
        for entity_id, entity in sim_a.state.entities.items()
        if entity.space_id == local_space_id and entity.template_id == HOSTILE_TEMPLATE_ID
    )
    assert hostile_ids

    assert simulation_hash(sim_a) == simulation_hash(sim_b)
    assert sim_a.state.combat_log == sim_b.state.combat_log


def test_hostile_engages_via_combat_seam_and_wounds_player() -> None:
    sim = _build_handoff_sim(seed=402)
    _schedule_request(sim)

    sim.advance_ticks(3)
    begin = _trace_by_type(sim, LOCAL_ENCOUNTER_BEGIN_EVENT_TYPE)[0]["params"]
    local_space_id = begin["to_space_id"]
    hostile_id = sorted(
        entity_id
        for entity_id, entity in sim.state.entities.items()
        if entity.space_id == local_space_id and entity.template_id == HOSTILE_TEMPLATE_ID
    )[0]
    hostile = sim.state.entities[hostile_id]
    player = sim.state.entities[DEFAULT_PLAYER_ENTITY_ID]
    hostile.position_x = player.position_x + 1.0
    hostile.position_y = player.position_y

    sim.advance_ticks(3)

    assert sim.state.combat_log
    first = sim.state.combat_log[0]
    assert first["intent"] == ATTACK_INTENT_COMMAND_TYPE
    assert first["attacker_id"].startswith("encounter_participant:")
    assert first["target_id"] == DEFAULT_PLAYER_ENTITY_ID
    assert first["applied"] is True
    assert sim.state.entities[DEFAULT_PLAYER_ENTITY_ID].wounds


def test_wound_consequence_persists_through_return_and_save_load() -> None:
    sim = _build_handoff_sim(seed=403)
    _schedule_request(sim)
    sim.advance_ticks(3)
    begin = _trace_by_type(sim, LOCAL_ENCOUNTER_BEGIN_EVENT_TYPE)[0]["params"]
    local_space_id = begin["to_space_id"]
    return_exit_coord = begin["return_exit_coord"]
    hostile_id = sorted(
        entity_id
        for entity_id, entity in sim.state.entities.items()
        if entity.space_id == local_space_id and entity.template_id == HOSTILE_TEMPLATE_ID
    )[0]
    hostile = sim.state.entities[hostile_id]
    player = sim.state.entities[DEFAULT_PLAYER_ENTITY_ID]
    hostile.position_x = player.position_x + 1.0
    hostile.position_y = player.position_y

    sim.advance_ticks(3)

    player = sim.state.entities[DEFAULT_PLAYER_ENTITY_ID]
    wounded_speed = player.speed_per_tick * movement_multiplier_from_wounds(player.wounds)
    assert wounded_speed < player.speed_per_tick

    exit_x, exit_y = square_grid_cell_to_world_xy(return_exit_coord["x"], return_exit_coord["y"])
    player.position_x = exit_x
    player.position_y = exit_y
    assert world_xy_to_square_grid_cell(player.position_x, player.position_y) == return_exit_coord
    hostile.position_x = player.position_x + 3.0
    hostile.position_y = player.position_y

    sim.append_command(
        SimCommand(
            tick=sim.state.tick,
            entity_id=DEFAULT_PLAYER_ENTITY_ID,
            command_type=END_LOCAL_ENCOUNTER_INTENT,
            params={"intent": END_LOCAL_ENCOUNTER_INTENT, "entity_id": DEFAULT_PLAYER_ENTITY_ID, "tags": []},
        )
    )
    sim.advance_ticks(4)

    return_events = _trace_by_type(sim, LOCAL_ENCOUNTER_RETURN_EVENT_TYPE)
    assert len(return_events) == 1
    assert sim.state.entities[DEFAULT_PLAYER_ENTITY_ID].space_id == CAMPAIGN_SPACE_ID

    wounds_before = list(sim.state.entities[DEFAULT_PLAYER_ENTITY_ID].wounds)
    payload = sim.simulation_payload()
    restored = Simulation.from_simulation_payload(payload)
    restored.register_rule_module(LocalEncounterRequestModule())
    restored.register_rule_module(LocalEncounterInstanceModule())
    restored.register_rule_module(LocalHostileBehaviorModule())
    restored.register_rule_module(CombatExecutionModule())
    assert restored.state.entities[DEFAULT_PLAYER_ENTITY_ID].wounds == wounds_before


def test_local_hostile_behavior_role_gated_outside_local_spaces() -> None:
    sim = _build_handoff_sim(seed=404)
    player = sim.state.entities[DEFAULT_PLAYER_ENTITY_ID]
    sim.add_entity(
        EntityState(
            entity_id="hostile_campaign",
            position_x=player.position_x,
            position_y=player.position_y,
            space_id=CAMPAIGN_SPACE_ID,
            template_id=HOSTILE_TEMPLATE_ID,
        )
    )

    sim.advance_ticks(3)

    assert sim.state.combat_log == []
    assert not any(command.command_type == ATTACK_INTENT_COMMAND_TYPE for command in sim.input_log)


def test_local_contact_latch_blocks_infinite_same_contact_hit_loop() -> None:
    sim = _build_handoff_sim(seed=405)
    _schedule_request(sim)
    sim.advance_ticks(3)

    begin = _trace_by_type(sim, LOCAL_ENCOUNTER_BEGIN_EVENT_TYPE)[0]["params"]
    local_space_id = begin["to_space_id"]
    hostile_id = sorted(
        entity_id
        for entity_id, entity in sim.state.entities.items()
        if entity.space_id == local_space_id and entity.template_id == HOSTILE_TEMPLATE_ID
    )[0]
    hostile = sim.state.entities[hostile_id]
    player = sim.state.entities[DEFAULT_PLAYER_ENTITY_ID]

    hostile.position_x = player.position_x + 1.0
    hostile.position_y = player.position_y

    sim.advance_ticks(60)

    applied_melee = [
        row
        for row in sim.state.combat_log
        if row.get("intent") == ATTACK_INTENT_COMMAND_TYPE and row.get("applied") is True
    ]
    assert len(applied_melee) == 1
    assert len(sim.state.entities[DEFAULT_PLAYER_ENTITY_ID].wounds) == 1


def test_local_contact_attack_cooldown_allows_player_reposition_between_hits() -> None:
    sim = _build_handoff_sim(seed=406)
    _schedule_request(sim)
    sim.advance_ticks(3)

    begin = _trace_by_type(sim, LOCAL_ENCOUNTER_BEGIN_EVENT_TYPE)[0]["params"]
    local_space_id = begin["to_space_id"]
    hostile_id = sorted(
        entity_id
        for entity_id, entity in sim.state.entities.items()
        if entity.space_id == local_space_id and entity.template_id == HOSTILE_TEMPLATE_ID
    )[0]
    hostile = sim.state.entities[hostile_id]
    player = sim.state.entities[DEFAULT_PLAYER_ENTITY_ID]

    hostile.position_x = player.position_x + 1.0
    hostile.position_y = player.position_y
    start_x = player.position_x

    for _ in range(6):
        sim.append_command(
            SimCommand(
                tick=sim.state.tick,
                entity_id=DEFAULT_PLAYER_ENTITY_ID,
                command_type="set_move_vector",
                params={"x": 1.0, "y": 0.0},
            )
        )
        sim.advance_ticks(1)

    assert sim.state.entities[DEFAULT_PLAYER_ENTITY_ID].position_x > start_x

    applied_melee = [
        row
        for row in sim.state.combat_log
        if row.get("intent") == ATTACK_INTENT_COMMAND_TYPE and row.get("applied") is True
    ]
    assert applied_melee


def test_local_contact_reengage_after_separation_emits_next_attack() -> None:
    sim = _build_handoff_sim(seed=407)
    _schedule_request(sim)
    sim.advance_ticks(3)

    begin = _trace_by_type(sim, LOCAL_ENCOUNTER_BEGIN_EVENT_TYPE)[0]["params"]
    local_space_id = begin["to_space_id"]
    hostile_id = sorted(
        entity_id
        for entity_id, entity in sim.state.entities.items()
        if entity.space_id == local_space_id and entity.template_id == HOSTILE_TEMPLATE_ID
    )[0]
    hostile = sim.state.entities[hostile_id]
    player = sim.state.entities[DEFAULT_PLAYER_ENTITY_ID]

    hostile.position_x = player.position_x + 1.0
    hostile.position_y = player.position_y
    sim.advance_ticks(5)

    first_count = len([row for row in sim.state.combat_log if row.get("applied") is True])
    assert first_count == 1

    hostile.position_x = player.position_x + 4.0
    hostile.position_y = player.position_y
    sim.advance_ticks(2)

    hostile.position_x = player.position_x + 1.0
    hostile.position_y = player.position_y
    sim.advance_ticks(4)

    second_count = len([row for row in sim.state.combat_log if row.get("applied") is True])
    assert second_count >= 2
