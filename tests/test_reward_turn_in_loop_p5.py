from __future__ import annotations

from pathlib import Path

from hexcrawler.content.io import load_game_json, load_world_json, save_game_json
from hexcrawler.sim.combat import ATTACK_INTENT_COMMAND_TYPE, CombatExecutionModule
from hexcrawler.sim.campaign_danger import (
    ACCEPT_ENCOUNTER_OFFER_INTENT,
    CampaignDangerModule,
    DEFAULT_DANGER_ENTITY_ID,
)
from hexcrawler.sim.core import EntityState, SimCommand, Simulation
from hexcrawler.sim.encounters import (
    END_LOCAL_ENCOUNTER_INTENT,
    ENCOUNTER_RESOLVE_REQUEST_EVENT_TYPE,
    LOCAL_ENCOUNTER_BEGIN_EVENT_TYPE,
    LOCAL_ENCOUNTER_END_EVENT_TYPE,
    LOCAL_ENCOUNTER_HOSTILE_TEMPLATE_ID,
    LOCAL_ENCOUNTER_REWARD_EVENT_TYPE,
    LOCAL_ENCOUNTER_RETURN_EVENT_TYPE,
    LocalEncounterInstanceModule,
    LocalEncounterRequestModule,
)
from hexcrawler.sim.exploration import (
    CAMPAIGN_AUTHOR_INTENT_COMMAND_TYPE,
    ENTER_SAFE_HUB_INTENT_COMMAND_TYPE,
    EXIT_SAFE_HUB_INTENT_COMMAND_TYPE,
    LOCAL_STRUCTURE_AUTHOR_INTENT_COMMAND_TYPE,
    LOOT_LOCAL_PROOF_INTENT_COMMAND_TYPE,
    REWARD_TURN_IN_OUTCOME_EVENT_TYPE,
    SAFE_HUB_OUTCOME_EVENT_TYPE,
    TURN_IN_REWARD_TOKEN_INTENT_COMMAND_TYPE,
    ExplorationExecutionModule,
)
from hexcrawler.sim.greybridge_layout import compile_greybridge_overlay
from hexcrawler.sim.hash import simulation_hash, world_hash
from hexcrawler.sim.movement import square_grid_cell_to_world_xy
from hexcrawler.sim.world import CAMPAIGN_SPACE_ROLE, SiteRecord, SpaceState


CAMPAIGN_SPACE_ID = "campaign_plane_beta"
SAFE_SITE_ID = "home_greybridge"


def _build_sim(seed: int = 123, *, with_campaign_danger: bool = False) -> Simulation:
    world = load_world_json("content/examples/basic_map.json")
    world.spaces[CAMPAIGN_SPACE_ID] = SpaceState(
        space_id=CAMPAIGN_SPACE_ID,
        role=CAMPAIGN_SPACE_ROLE,
        topology_type="square_grid",
        topology_params={"width": 6, "height": 6, "origin": {"x": 10, "y": 20}},
    )
    world.sites["home_greybridge"] = SiteRecord(
        site_id=SAFE_SITE_ID,
        site_type="town",
        location={"space_id": CAMPAIGN_SPACE_ID, "coord": {"x": 12, "y": 21}},
        tags=["safe"],
    )
    sim = Simulation(world=world, seed=seed)
    x, y = square_grid_cell_to_world_xy(12, 21)
    sim.add_entity(EntityState(entity_id="scout", position_x=x, position_y=y, space_id=CAMPAIGN_SPACE_ID))
    sim.register_rule_module(LocalEncounterRequestModule())
    sim.register_rule_module(LocalEncounterInstanceModule())
    if with_campaign_danger:
        sim.register_rule_module(CampaignDangerModule())
    sim.register_rule_module(CombatExecutionModule())
    sim.register_rule_module(ExplorationExecutionModule())
    return sim


def _trace(sim: Simulation, event_type: str) -> list[dict]:
    return [entry for entry in sim.get_event_trace() if entry["event_type"] == event_type]


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
                "topology_type": "square_grid",
                "coord": {"x": 12, "y": 21},
            },
            "roll": 48,
            "category": "hostile",
            "table_id": "enc_table_primary",
            "entry_id": "wolves_1",
        },
    )


def _issue_end_intent(sim: Simulation) -> None:
    sim.append_command(
        SimCommand(
            tick=sim.state.tick,
            entity_id="scout",
            command_type=END_LOCAL_ENCOUNTER_INTENT,
            params={"intent": END_LOCAL_ENCOUNTER_INTENT, "entity_id": "scout", "tags": []},
        )
    )

def _issue_loot_intent(sim: Simulation) -> None:
    sim.append_command(
        SimCommand(
            tick=sim.state.tick,
            entity_id="scout",
            command_type=LOOT_LOCAL_PROOF_INTENT_COMMAND_TYPE,
            params={},
        )
    )


def _enter_safe_hub(sim: Simulation) -> None:
    sim.append_command(
        SimCommand(
            tick=sim.state.tick,
            entity_id="scout",
            command_type=ENTER_SAFE_HUB_INTENT_COMMAND_TYPE,
            params={"site_id": SAFE_SITE_ID},
        )
    )
    sim.advance_ticks(1)


def _exit_safe_hub(sim: Simulation) -> None:
    sim.append_command(
        SimCommand(
            tick=sim.state.tick,
            entity_id="scout",
            command_type=EXIT_SAFE_HUB_INTENT_COMMAND_TYPE,
            params={},
        )
    )
    sim.advance_ticks(1)


def _player_items(sim: Simulation) -> dict[str, int]:
    container_id = sim.state.entities["scout"].inventory_container_id
    assert container_id is not None
    return dict(sim.state.world.containers[container_id].items)


def _prepare_incapacitated_hostile(sim: Simulation) -> None:
    begin = _trace(sim, LOCAL_ENCOUNTER_BEGIN_EVENT_TYPE)[0]
    local_space_id = begin["params"]["to_space_id"]
    spawned = begin["params"]["spawned_entities"]
    hostile_id = next(
        row["entity_id"]
        for row in spawned
        if sim.state.entities[row["entity_id"]].template_id == LOCAL_ENCOUNTER_HOSTILE_TEMPLATE_ID
    )

    hostile = sim.state.entities[hostile_id]
    hx, hy = square_grid_cell_to_world_xy(0, 0)
    hostile.position_x = hx
    hostile.position_y = hy
    hostile.wounds = [{"severity": 3, "region": "torso"}]

    # keep player close enough to loot manually
    px, py = square_grid_cell_to_world_xy(1, 0)
    sim.state.entities["scout"].position_x = px
    sim.state.entities["scout"].position_y = py
    assert sim.state.entities["scout"].space_id == local_space_id


def test_local_success_grants_single_reward_token_and_persists_after_return() -> None:
    sim = _build_sim(seed=11)
    _schedule_request(sim)
    sim.advance_ticks(3)
    _prepare_incapacitated_hostile(sim)

    _issue_loot_intent(sim)
    sim.advance_ticks(1)
    _issue_end_intent(sim)
    _issue_end_intent(sim)
    sim.advance_ticks(3)

    reward_events = _trace(sim, LOCAL_ENCOUNTER_REWARD_EVENT_TYPE)
    assert reward_events[-1]["params"]["applied"] is True
    assert reward_events[-1]["params"]["reason"] == "token_looted"

    items = _player_items(sim)
    assert items.get("proof_token", 0) == 1


def test_player_attack_intent_can_incapacitate_hostile_and_grant_reward_token() -> None:
    sim = _build_sim(seed=31)
    _schedule_request(sim)
    sim.advance_ticks(3)
    begin = _trace(sim, LOCAL_ENCOUNTER_BEGIN_EVENT_TYPE)[0]
    local_space_id = begin["params"]["to_space_id"]
    spawned = begin["params"]["spawned_entities"]
    hostile_id = next(
        row["entity_id"]
        for row in spawned
        if sim.state.entities[row["entity_id"]].template_id == LOCAL_ENCOUNTER_HOSTILE_TEMPLATE_ID
    )

    player = sim.state.entities["scout"]
    hostile = sim.state.entities[hostile_id]
    player.position_x, player.position_y = square_grid_cell_to_world_xy(1, 1)
    hostile.position_x, hostile.position_y = square_grid_cell_to_world_xy(2, 1)
    assert player.space_id == local_space_id
    assert hostile.space_id == local_space_id

    for offset in (0, 8, 16):
        sim.append_command(
            SimCommand(
                tick=sim.state.tick + offset,
                entity_id="scout",
                command_type=ATTACK_INTENT_COMMAND_TYPE,
                params={
                    "attacker_id": "scout",
                    "target_id": hostile_id,
                    "mode": "melee",
                    "tags": ["test_player_attack_loop"],
                },
            )
        )
    sim.advance_ticks(30)
    assert len(hostile.wounds) >= 3

    _issue_loot_intent(sim)
    sim.advance_ticks(1)
    exit_coord = begin["params"]["return_exit_coord"]
    player.position_x, player.position_y = square_grid_cell_to_world_xy(exit_coord["x"], exit_coord["y"])
    _issue_end_intent(sim)
    sim.advance_ticks(3)

    reward = _trace(sim, LOCAL_ENCOUNTER_REWARD_EVENT_TYPE)[-1]["params"]
    assert reward["applied"] is True
    assert reward["reason"] == "token_looted"
    assert _player_items(sim).get("proof_token", 0) == 1



def test_reward_turn_in_succeeds_only_at_safe_site_and_grants_ration() -> None:
    sim = _build_sim(seed=12)
    _schedule_request(sim)
    sim.advance_ticks(3)
    _prepare_incapacitated_hostile(sim)
    _issue_loot_intent(sim)
    sim.advance_ticks(1)
    begin = _trace(sim, LOCAL_ENCOUNTER_BEGIN_EVENT_TYPE)[0]
    exit_coord = begin["params"]["return_exit_coord"]
    sim.state.entities["scout"].position_x, sim.state.entities["scout"].position_y = square_grid_cell_to_world_xy(exit_coord["x"], exit_coord["y"])
    _issue_end_intent(sim)
    sim.advance_ticks(3)
    _enter_safe_hub(sim)
    scout = sim.state.entities["scout"]
    scout.position_x, scout.position_y = square_grid_cell_to_world_xy(10, 3)

    before = _player_items(sim)
    sim.append_command(
        SimCommand(
            tick=sim.state.tick,
            entity_id="scout",
            command_type=TURN_IN_REWARD_TOKEN_INTENT_COMMAND_TYPE,
            params={},
        )
    )
    sim.advance_ticks(1)

    outcome = _trace(sim, REWARD_TURN_IN_OUTCOME_EVENT_TYPE)[-1]["params"]
    assert outcome["applied"] is True
    assert outcome["reason"] == "reward_turned_in"

    after = _player_items(sim)
    assert after.get("proof_token", 0) == before.get("proof_token", 0) - 1
    assert after.get("rations", 0) == before.get("rations", 0) + 1



def test_reward_turn_in_rejected_when_not_at_safe_site() -> None:
    sim = _build_sim(seed=13)
    container_id = sim.state.entities["scout"].inventory_container_id
    assert container_id is not None
    sim.state.world.containers[container_id].items["proof_token"] = 1

    x, y = square_grid_cell_to_world_xy(13, 21)
    sim.state.entities["scout"].position_x = x
    sim.state.entities["scout"].position_y = y

    sim.append_command(
        SimCommand(
            tick=sim.state.tick,
            entity_id="scout",
            command_type=TURN_IN_REWARD_TOKEN_INTENT_COMMAND_TYPE,
            params={},
        )
    )
    sim.advance_ticks(1)

    outcome = _trace(sim, REWARD_TURN_IN_OUTCOME_EVENT_TYPE)[0]["params"]
    assert outcome["applied"] is False
    assert outcome["reason"] == "greybridge_building_required"
    assert _player_items(sim).get("proof_token", 0) == 1



def test_reward_turn_in_rejected_when_token_absent() -> None:
    sim = _build_sim(seed=14)
    _enter_safe_hub(sim)
    scout = sim.state.entities["scout"]
    scout.position_x, scout.position_y = square_grid_cell_to_world_xy(10, 3)
    sim.append_command(
        SimCommand(
            tick=sim.state.tick,
            entity_id="scout",
            command_type=TURN_IN_REWARD_TOKEN_INTENT_COMMAND_TYPE,
            params={},
        )
    )
    sim.advance_ticks(1)

    outcome = _trace(sim, REWARD_TURN_IN_OUTCOME_EVENT_TYPE)[0]["params"]
    assert outcome["applied"] is False
    assert outcome["reason"] == "token_required"



def test_reward_save_load_and_replay_hash_stable() -> None:
    def run_once(tmp_path: Path) -> str:
        sim = _build_sim(seed=15)
        _schedule_request(sim)
        sim.advance_ticks(3)
        _prepare_incapacitated_hostile(sim)
        _issue_loot_intent(sim)
        sim.advance_ticks(1)
        begin = _trace(sim, LOCAL_ENCOUNTER_BEGIN_EVENT_TYPE)[0]
        exit_coord = begin["params"]["return_exit_coord"]
        sim.state.entities["scout"].position_x, sim.state.entities["scout"].position_y = square_grid_cell_to_world_xy(exit_coord["x"], exit_coord["y"])
        _issue_end_intent(sim)
        sim.advance_ticks(3)
        _enter_safe_hub(sim)
        scout = sim.state.entities["scout"]
        scout.position_x, scout.position_y = square_grid_cell_to_world_xy(10, 3)

        path = tmp_path / "reward_save.json"
        save_game_json(path, sim.state.world, sim)
        _, loaded = load_game_json(path)
        loaded.register_rule_module(LocalEncounterRequestModule())
        loaded.register_rule_module(LocalEncounterInstanceModule())
        loaded.register_rule_module(ExplorationExecutionModule())
        loaded.append_command(
            SimCommand(
                tick=loaded.state.tick,
                entity_id="scout",
                command_type=TURN_IN_REWARD_TOKEN_INTENT_COMMAND_TYPE,
                params={},
            )
        )
        loaded.advance_ticks(1)
        return simulation_hash(loaded)

    # deterministic replay/hash identity for same seed+inputs including save/load boundary
    from tempfile import TemporaryDirectory

    with TemporaryDirectory() as td1, TemporaryDirectory() as td2:
        assert run_once(Path(td1)) == run_once(Path(td2))



def test_local_reward_not_granted_without_incapacitated_hostile() -> None:
    sim = _build_sim(seed=16)
    _schedule_request(sim)
    sim.advance_ticks(3)
    _issue_loot_intent(sim)
    sim.advance_ticks(1)

    reward = _trace(sim, LOCAL_ENCOUNTER_REWARD_EVENT_TYPE)[0]["params"]
    assert reward["applied"] is False
    assert reward["reason"] == "no_lootable_proof"
    assert _player_items(sim).get("proof_token", 0) == 0



def test_local_reward_ignores_stale_incapacitated_nonparticipant_hostiles() -> None:
    sim = _build_sim(seed=17)
    _schedule_request(sim)
    sim.advance_ticks(3)

    begin = _trace(sim, LOCAL_ENCOUNTER_BEGIN_EVENT_TYPE)[0]
    local_space_id = begin["params"]["to_space_id"]

    stale_x, stale_y = square_grid_cell_to_world_xy(1, 1)
    sim.add_entity(
        EntityState(
            entity_id="stale_hostile",
            template_id=LOCAL_ENCOUNTER_HOSTILE_TEMPLATE_ID,
            position_x=stale_x,
            position_y=stale_y,
            space_id=local_space_id,
            wounds=[{"severity": 3, "region": "torso"}],
        )
    )
    sim.state.entities["scout"].position_x, sim.state.entities["scout"].position_y = square_grid_cell_to_world_xy(1, 2)

    _issue_loot_intent(sim)
    sim.advance_ticks(1)
    reward = _trace(sim, LOCAL_ENCOUNTER_REWARD_EVENT_TYPE)[0]["params"]
    assert reward["applied"] is True
    assert reward["reason"] == "token_looted"
    assert _player_items(sim).get("proof_token", 0) == 1


def test_turn_in_refunds_token_if_benefit_grant_fails(monkeypatch) -> None:
    sim = _build_sim(seed=18)
    container_id = sim.state.entities["scout"].inventory_container_id
    assert container_id is not None
    sim.state.world.containers[container_id].items["proof_token"] = 1

    from hexcrawler.sim import exploration as exploration_module

    monkeypatch.setattr(exploration_module, "REWARD_TURN_IN_BENEFIT_ITEM_ID", "missing_item")
    _enter_safe_hub(sim)
    scout = sim.state.entities["scout"]
    scout.position_x, scout.position_y = square_grid_cell_to_world_xy(10, 3)

    sim.append_command(
        SimCommand(
            tick=sim.state.tick,
            entity_id="scout",
            command_type=TURN_IN_REWARD_TOKEN_INTENT_COMMAND_TYPE,
            params={},
        )
    )
    sim.advance_ticks(1)

    outcome = _trace(sim, REWARD_TURN_IN_OUTCOME_EVENT_TYPE)[0]["params"]
    assert outcome["applied"] is False
    assert outcome["reason"] == "benefit_grant_rejected"
    assert outcome["details"]["refund_outcome"] == "applied"
    assert _player_items(sim).get("proof_token", 0) == 1


def test_leaving_local_without_loot_does_not_grant_token() -> None:
    sim = _build_sim(seed=23)
    _schedule_request(sim)
    sim.advance_ticks(3)
    _prepare_incapacitated_hostile(sim)
    begin = _trace(sim, LOCAL_ENCOUNTER_BEGIN_EVENT_TYPE)[0]
    exit_coord = begin["params"]["return_exit_coord"]
    sim.state.entities["scout"].position_x, sim.state.entities["scout"].position_y = square_grid_cell_to_world_xy(exit_coord["x"], exit_coord["y"])
    _issue_end_intent(sim)
    sim.advance_ticks(3)
    assert _player_items(sim).get("proof_token", 0) == 0


def test_turn_in_schedules_single_replacement_patrol() -> None:
    sim = _build_sim(seed=24)
    container_id = sim.state.entities["scout"].inventory_container_id
    assert container_id is not None
    sim.state.world.containers[container_id].items["proof_token"] = 1
    _enter_safe_hub(sim)
    sim.state.entities["scout"].position_x, sim.state.entities["scout"].position_y = square_grid_cell_to_world_xy(10, 3)
    sim.append_command(
        SimCommand(
            tick=sim.state.tick,
            entity_id="scout",
            command_type=TURN_IN_REWARD_TOKEN_INTENT_COMMAND_TYPE,
            params={},
        )
    )
    sim.advance_ticks(2)
    patrols = [e for e in sim.state.entities.values() if str(e.template_id or "") == "campaign_danger_patrol"]
    assert len(patrols) == 1


def test_greybridge_safe_hub_enter_exit_round_trip() -> None:
    sim = _build_sim(seed=25)
    scout = sim.state.entities["scout"]
    origin = (scout.space_id, scout.position_x, scout.position_y)
    _enter_safe_hub(sim)
    assert scout.space_id == "safe_hub:greybridge"
    _exit_safe_hub(sim)
    assert scout.space_id == origin[0]
    assert (scout.position_x, scout.position_y) == (origin[1], origin[2])


def test_greybridge_safe_hub_exit_uses_site_origin_fallback_when_context_missing() -> None:
    sim = _build_sim(seed=26)
    _enter_safe_hub(sim)
    scout = sim.state.entities["scout"]
    assert scout.space_id == "safe_hub:greybridge"

    state = sim.get_rules_state(ExplorationExecutionModule.name)
    state["safe_hub_active_by_entity"] = {}
    sim.set_rules_state(ExplorationExecutionModule.name, state)

    _exit_safe_hub(sim)
    outcome = _trace(sim, SAFE_HUB_OUTCOME_EVENT_TYPE)[-1]["params"]
    assert outcome["applied"] is True
    assert outcome["reason"] == "exited_safe_hub_fallback_origin"
    assert scout.space_id == CAMPAIGN_SPACE_ID


def test_replacement_patrol_reenters_campaign_offer_path_after_turn_in() -> None:
    sim = _build_sim(seed=27, with_campaign_danger=True)
    sim.state.entities.pop(DEFAULT_DANGER_ENTITY_ID, None)
    container_id = sim.state.entities["scout"].inventory_container_id
    assert container_id is not None
    sim.state.world.containers[container_id].items["proof_token"] = 1

    _enter_safe_hub(sim)
    scout = sim.state.entities["scout"]
    scout.position_x, scout.position_y = square_grid_cell_to_world_xy(10, 3)
    sim.append_command(
        SimCommand(
            tick=sim.state.tick,
            entity_id="scout",
            command_type=TURN_IN_REWARD_TOKEN_INTENT_COMMAND_TYPE,
            params={},
        )
    )
    sim.advance_ticks(2)
    assert DEFAULT_DANGER_ENTITY_ID in sim.state.entities

    _exit_safe_hub(sim)
    danger = sim.state.entities[DEFAULT_DANGER_ENTITY_ID]
    danger.speed_per_tick = 0.0
    scout.space_id = danger.space_id
    scout.position_x = danger.position_x
    scout.position_y = danger.position_y
    sim.advance_ticks(1)
    scout.position_x += 2.0
    scout.position_y += 2.0
    sim.advance_ticks(1)
    scout.position_x = danger.position_x
    scout.position_y = danger.position_y
    sim.advance_ticks(2)

    state = sim.get_rules_state(CampaignDangerModule.name)
    pending_offer = state.get("pending_offer_by_player", {}).get("scout")
    assert isinstance(pending_offer, dict)

    sim.append_command(
        SimCommand(
            tick=sim.state.tick,
            entity_id="scout",
            command_type=ACCEPT_ENCOUNTER_OFFER_INTENT,
            params={"entity_id": "scout"},
        )
    )
    sim.advance_ticks(3)
    assert _trace(sim, LOCAL_ENCOUNTER_BEGIN_EVENT_TYPE)
    state = sim.get_rules_state(CampaignDangerModule.name)
    assert state.get("encounter_control_by_player", {}).get("scout", {}).get("state") in {"in_local", "returning", "post_encounter_cooldown"}


def test_greybridge_hub_blocked_cells_stop_movement_but_doors_and_gate_path_remain_open() -> None:
    sim = _build_sim(seed=28)
    _enter_safe_hub(sim)
    scout = sim.state.entities["scout"]

    scout.position_x, scout.position_y = square_grid_cell_to_world_xy(7, 3)
    sim.append_command(
        SimCommand(
            tick=sim.state.tick,
            entity_id="scout",
            command_type="set_target_position",
            params={"x": 8.5, "y": 4.5},
        )
    )
    sim.advance_ticks(40)
    # Wall cell remains blocked.
    assert int(scout.position_x) != 8 or int(scout.position_y) != 4

    sim.append_command(
        SimCommand(
            tick=sim.state.tick,
            entity_id="scout",
            command_type="set_target_position",
            params={"x": 8.5, "y": 3.5},
        )
    )
    sim.advance_ticks(40)
    assert int(scout.position_x) == 8 and int(scout.position_y) == 3

    scout.position_x, scout.position_y = square_grid_cell_to_world_xy(2, 5)
    sim.append_command(
        SimCommand(
            tick=sim.state.tick,
            entity_id="scout",
            command_type="set_target_position",
            params={"x": 1.5, "y": 5.5},
        )
    )
    sim.advance_ticks(30)
    assert int(scout.position_x) == 1 and int(scout.position_y) == 5


def test_greybridge_overlay_compilation_is_deterministic_and_contains_gate_semantics() -> None:
    compiled_a = compile_greybridge_overlay()
    compiled_b = compile_greybridge_overlay()

    assert compiled_a == compiled_b
    gate_rows = [row for row in compiled_a["opening_rows"] if row.get("kind") == "gate_portal"]
    assert gate_rows
    gate_cell = gate_rows[0]["cell"]
    assert gate_cell == {"x": 1, "y": 5}
    assert (1, 5) not in compiled_a["blocked_cells"]
    assert (0, 5) in compiled_a["blocked_cells"]
    assert compiled_a["wall_segments"]


def test_greybridge_overlay_derived_collision_stable_across_save_load(tmp_path: Path) -> None:
    sim = _build_sim(seed=281)
    _enter_safe_hub(sim)
    scout = sim.state.entities["scout"]
    scout.position_x, scout.position_y = square_grid_cell_to_world_xy(7, 3)
    sim.advance_ticks(2)

    save_path = tmp_path / "overlay_collision_save.json"
    save_game_json(save_path, sim.state.world, sim)
    _, loaded = load_game_json(str(save_path))
    loaded.register_rule_module(LocalEncounterRequestModule())
    loaded.register_rule_module(LocalEncounterInstanceModule())
    loaded.register_rule_module(CombatExecutionModule())
    loaded.register_rule_module(ExplorationExecutionModule())
    loaded_hash_before = simulation_hash(loaded)

    loaded.append_command(
        SimCommand(
            tick=loaded.state.tick,
            entity_id="scout",
            command_type="set_target_position",
            params={"x": 8.5, "y": 4.5},
        )
    )
    loaded.advance_ticks(40)
    reloaded_scout = loaded.state.entities["scout"]
    assert int(reloaded_scout.position_x) != 8 or int(reloaded_scout.position_y) != 4

    _, replay = load_game_json(str(save_path))
    replay.register_rule_module(LocalEncounterRequestModule())
    replay.register_rule_module(LocalEncounterInstanceModule())
    replay.register_rule_module(CombatExecutionModule())
    replay.register_rule_module(ExplorationExecutionModule())
    replay_hash_before = simulation_hash(replay)
    assert loaded_hash_before == replay_hash_before
    replay.append_command(
        SimCommand(
            tick=replay.state.tick,
            entity_id="scout",
            command_type="set_target_position",
            params={"x": 8.5, "y": 4.5},
        )
    )
    replay.advance_ticks(40)
    assert simulation_hash(loaded) == simulation_hash(replay)


def test_greybridge_gatehouse_round_trip_remains_traversable_and_exit_stable() -> None:
    sim = _build_sim(seed=29)
    scout = sim.state.entities["scout"]

    _enter_safe_hub(sim)
    assert scout.space_id == "safe_hub:greybridge"

    # Gatehouse spawn side -> interior via opening at (3,5).
    scout.position_x, scout.position_y = square_grid_cell_to_world_xy(2, 5)
    sim.append_command(
        SimCommand(
            tick=sim.state.tick,
            entity_id="scout",
            command_type="set_target_position",
            params={"x": 4.5, "y": 5.5},
        )
    )
    sim.advance_ticks(30)
    assert int(scout.position_x) >= 3 and int(scout.position_y) == 5

    # Interior -> gatehouse -> campaign exit remains available.
    sim.append_command(
        SimCommand(
            tick=sim.state.tick,
            entity_id="scout",
            command_type="set_target_position",
            params={"x": 1.5, "y": 5.5},
        )
    )
    sim.advance_ticks(30)
    assert int(scout.position_x) == 1 and int(scout.position_y) == 5
    _exit_safe_hub(sim)
    assert scout.space_id == CAMPAIGN_SPACE_ID


def test_local_structure_authoring_create_edit_delete_persists_save_load(tmp_path: Path) -> None:
    sim = _build_sim(seed=31)
    _enter_safe_hub(sim)
    scout = sim.state.entities["scout"]

    sim.append_command(
        SimCommand(
            tick=sim.state.tick,
            entity_id="scout",
            command_type=LOCAL_STRUCTURE_AUTHOR_INTENT_COMMAND_TYPE,
            params={
                "operation": "create_rect",
                "structure_id": "authoring_demo_shell",
                "label": "Author Demo",
                "room_id": "authoring_demo",
                "bounds": {"x": 4, "y": 1, "width": 4, "height": 3},
                "tags": ["authoring_demo"],
            },
        )
    )
    sim.advance_ticks(2)
    safe_hub = sim.state.world.spaces["safe_hub:greybridge"]
    structures = safe_hub.structure_primitives
    assert any(row.get("structure_id") == "authoring_demo_shell" for row in structures)

    sim.append_command(
        SimCommand(
            tick=sim.state.tick,
            entity_id="scout",
            command_type=LOCAL_STRUCTURE_AUTHOR_INTENT_COMMAND_TYPE,
            params={
                "operation": "move_opening",
                "structure_id": "authoring_demo_shell",
                "opening_id": "authoring_demo_opening",
                "kind": "door",
                "cell": {"x": 4, "y": 2},
            },
        )
    )
    sim.advance_ticks(2)
    structures = sim.state.world.spaces["safe_hub:greybridge"].structure_primitives
    opening_rows = [
        row
        for row in compile_greybridge_overlay(structures)["opening_rows"]
        if row.get("structure_id") == "authoring_demo_shell"
    ]
    assert {"x": 4, "y": 2} in [row["cell"] for row in opening_rows]

    scout.position_x, scout.position_y = square_grid_cell_to_world_xy(3, 2)
    sim.append_command(
        SimCommand(
            tick=sim.state.tick,
            entity_id="scout",
            command_type="set_target_position",
            params={"x": 4.5, "y": 2.5},
        )
    )
    sim.advance_ticks(30)
    assert int(scout.position_x) == 4 and int(scout.position_y) == 2

    save_path = tmp_path / "local_structure_authoring_save.json"
    save_game_json(save_path, sim.state.world, sim)
    _, loaded = load_game_json(str(save_path))
    loaded.register_rule_module(LocalEncounterRequestModule())
    loaded.register_rule_module(LocalEncounterInstanceModule())
    loaded.register_rule_module(CombatExecutionModule())
    loaded.register_rule_module(ExplorationExecutionModule())
    loaded_space = loaded.state.world.spaces["safe_hub:greybridge"]
    loaded_structures = loaded_space.structure_primitives
    assert any(row.get("structure_id") == "authoring_demo_shell" for row in loaded_structures)

    loaded.append_command(
        SimCommand(
            tick=loaded.state.tick,
            entity_id="scout",
            command_type=LOCAL_STRUCTURE_AUTHOR_INTENT_COMMAND_TYPE,
            params={"operation": "delete_structure", "structure_id": "authoring_demo_shell"},
        )
    )
    loaded.advance_ticks(2)
    loaded_structures = loaded.state.world.spaces["safe_hub:greybridge"].structure_primitives
    assert not any(row.get("structure_id") == "authoring_demo_shell" for row in loaded_structures)


def test_campaign_site_authoring_create_move_delete_persists_save_load(tmp_path: Path) -> None:
    sim = _build_sim(seed=45)
    scout = sim.state.entities["scout"]
    scout.space_id = "overworld"
    scout.position_x = -1.0
    scout.position_y = 2.0

    sim.append_command(
        SimCommand(
            tick=sim.state.tick,
            entity_id="scout",
            command_type=CAMPAIGN_AUTHOR_INTENT_COMMAND_TYPE,
            params={
                "operation": "create_or_update_site",
                "site_id": "authoring_town_site",
                "site_kind": "town",
                "label": "Authoring Town",
                "position": {"x": -1.0, "y": 2.0},
            },
        )
    )
    sim.advance_ticks(2)
    town = sim.state.world.sites.get("authoring_town_site")
    assert town is not None
    assert town.site_type == "town"
    assert town.location.get("campaign_anchor") == {"x": -1.0, "y": 2.0}

    sim.append_command(
        SimCommand(
            tick=sim.state.tick,
            entity_id="scout",
            command_type=CAMPAIGN_AUTHOR_INTENT_COMMAND_TYPE,
            params={
                "operation": "move_site",
                "site_id": "authoring_town_site",
                "position": {"x": 1.5, "y": -0.5},
            },
        )
    )
    sim.advance_ticks(2)
    moved = sim.state.world.sites["authoring_town_site"]
    assert moved.location.get("campaign_anchor") == {"x": 1.5, "y": -0.5}

    save_path = tmp_path / "campaign_site_authoring_save.json"
    save_game_json(save_path, sim.state.world, sim)
    before_world_hash = world_hash(sim.state.world)
    _, loaded = load_game_json(str(save_path))
    assert world_hash(loaded.state.world) == before_world_hash
    assert loaded.state.world.sites["authoring_town_site"].location.get("campaign_anchor") == {"x": 1.5, "y": -0.5}

    loaded.register_rule_module(LocalEncounterRequestModule())
    loaded.register_rule_module(LocalEncounterInstanceModule())
    loaded.register_rule_module(CombatExecutionModule())
    loaded.register_rule_module(ExplorationExecutionModule())
    loaded.append_command(
        SimCommand(
            tick=loaded.state.tick,
            entity_id="scout",
            command_type=CAMPAIGN_AUTHOR_INTENT_COMMAND_TYPE,
            params={"operation": "delete_site", "site_id": "authoring_town_site"},
        )
    )
    loaded.advance_ticks(2)
    assert "authoring_town_site" not in loaded.state.world.sites


def test_campaign_patrol_authoring_create_move_delete_persists_save_load(tmp_path: Path) -> None:
    sim = _build_sim(seed=46)
    scout = sim.state.entities["scout"]
    scout.space_id = "overworld"
    scout.position_x = -2.0
    scout.position_y = 1.0

    sim.append_command(
        SimCommand(
            tick=sim.state.tick,
            entity_id="scout",
            command_type=CAMPAIGN_AUTHOR_INTENT_COMMAND_TYPE,
            params={
                "operation": "create_or_update_patrol",
                "patrol_id": "patrol:authoring_demo",
                "template_id": "campaign_danger_patrol",
                "position": {"x": -2.0, "y": 1.0},
                "route_anchors": [{"x": -1.0, "y": 1.0}],
            },
        )
    )
    sim.advance_ticks(2)
    patrol = sim.state.world.campaign_patrols.get("patrol:authoring_demo")
    assert patrol is not None
    assert patrol.spawn_position == {"x": -2.0, "y": 1.0}
    assert patrol.route_anchors[0] == {"x": -1.0, "y": 1.0}

    sim.append_command(
        SimCommand(
            tick=sim.state.tick,
            entity_id="scout",
            command_type=CAMPAIGN_AUTHOR_INTENT_COMMAND_TYPE,
            params={
                "operation": "move_patrol_spawn",
                "patrol_id": "patrol:authoring_demo",
                "position": {"x": -3.25, "y": 0.5},
            },
        )
    )
    sim.append_command(
        SimCommand(
            tick=sim.state.tick,
            entity_id="scout",
            command_type=CAMPAIGN_AUTHOR_INTENT_COMMAND_TYPE,
            params={
                "operation": "move_patrol_anchor",
                "patrol_id": "patrol:authoring_demo",
                "anchor_index": 0,
                "position": {"x": -2.75, "y": 0.5},
            },
        )
    )
    sim.advance_ticks(2)
    updated = sim.state.world.campaign_patrols["patrol:authoring_demo"]
    assert updated.spawn_position == {"x": -3.25, "y": 0.5}
    assert updated.route_anchors[0] == {"x": -2.75, "y": 0.5}

    before_hash = simulation_hash(sim)
    save_path = tmp_path / "campaign_patrol_authoring_save.json"
    save_game_json(save_path, sim.state.world, sim)
    _, loaded = load_game_json(str(save_path))
    assert simulation_hash(loaded) == before_hash
    assert loaded.state.world.campaign_patrols["patrol:authoring_demo"].route_anchors[0] == {"x": -2.75, "y": 0.5}

    loaded.register_rule_module(LocalEncounterRequestModule())
    loaded.register_rule_module(LocalEncounterInstanceModule())
    loaded.register_rule_module(CombatExecutionModule())
    loaded.register_rule_module(ExplorationExecutionModule())
    loaded.append_command(
        SimCommand(
            tick=loaded.state.tick,
            entity_id="scout",
            command_type=CAMPAIGN_AUTHOR_INTENT_COMMAND_TYPE,
            params={"operation": "delete_patrol", "patrol_id": "patrol:authoring_demo"},
        )
    )
    loaded.advance_ticks(2)
    assert "patrol:authoring_demo" not in loaded.state.world.campaign_patrols


def test_campaign_dungeon_authoring_create_move_delete_persists_save_load(tmp_path: Path) -> None:
    sim = _build_sim(seed=47)
    scout = sim.state.entities["scout"]
    scout.space_id = "overworld"
    scout.position_x = 3.0
    scout.position_y = -1.0

    sim.append_command(
        SimCommand(
            tick=sim.state.tick,
            entity_id="scout",
            command_type=CAMPAIGN_AUTHOR_INTENT_COMMAND_TYPE,
            params={
                "operation": "create_or_update_site",
                "site_id": "authoring_dungeon_site",
                "site_kind": "dungeon_entrance",
                "label": "Authoring Dungeon Entrance",
                "position": {"x": 3.0, "y": -1.0},
            },
        )
    )
    sim.advance_ticks(2)
    dungeon = sim.state.world.sites.get("authoring_dungeon_site")
    assert dungeon is not None
    assert dungeon.site_type == "dungeon_entrance"
    assert dungeon.location.get("campaign_anchor") == {"x": 3.0, "y": -1.0}

    sim.append_command(
        SimCommand(
            tick=sim.state.tick,
            entity_id="scout",
            command_type=CAMPAIGN_AUTHOR_INTENT_COMMAND_TYPE,
            params={
                "operation": "move_site",
                "site_id": "authoring_dungeon_site",
                "position": {"x": 2.25, "y": -2.5},
            },
        )
    )
    sim.advance_ticks(2)
    moved = sim.state.world.sites["authoring_dungeon_site"]
    assert moved.location.get("campaign_anchor") == {"x": 2.25, "y": -2.5}

    before_hash = simulation_hash(sim)
    save_path = tmp_path / "campaign_dungeon_authoring_save.json"
    save_game_json(save_path, sim.state.world, sim)
    _, loaded = load_game_json(str(save_path))
    assert simulation_hash(loaded) == before_hash
    assert loaded.state.world.sites["authoring_dungeon_site"].location.get("campaign_anchor") == {"x": 2.25, "y": -2.5}

    loaded.register_rule_module(LocalEncounterRequestModule())
    loaded.register_rule_module(LocalEncounterInstanceModule())
    loaded.register_rule_module(CombatExecutionModule())
    loaded.register_rule_module(ExplorationExecutionModule())
    loaded.append_command(
        SimCommand(
            tick=loaded.state.tick,
            entity_id="scout",
            command_type=CAMPAIGN_AUTHOR_INTENT_COMMAND_TYPE,
            params={"operation": "delete_site", "site_id": "authoring_dungeon_site"},
        )
    )
    loaded.advance_ticks(2)
    assert "authoring_dungeon_site" not in loaded.state.world.sites


def test_patrol_loop_recontacts_after_leave_return_and_replacement_without_wedge() -> None:
    sim = _build_sim(seed=30, with_campaign_danger=True)
    scout = sim.state.entities["scout"]
    container_id = scout.inventory_container_id
    assert container_id is not None
    sim.state.world.containers[container_id].items["proof_token"] = 1

    danger = sim.state.entities[DEFAULT_DANGER_ENTITY_ID]
    danger.speed_per_tick = 0.0
    scout.space_id = danger.space_id
    scout.position_x = danger.position_x
    scout.position_y = danger.position_y
    sim.advance_ticks(2)
    pending = sim.get_rules_state(CampaignDangerModule.name).get("pending_offer_by_player", {}).get("scout")
    assert isinstance(pending, dict)

    # Accept the first (original patrol) contact and return without kill.
    sim.append_command(
        SimCommand(
            tick=sim.state.tick,
            entity_id="scout",
            command_type=ACCEPT_ENCOUNTER_OFFER_INTENT,
            params={"entity_id": "scout"},
        )
    )
    sim.advance_ticks(3)
    begin = _trace(sim, LOCAL_ENCOUNTER_BEGIN_EVENT_TYPE)[-1]
    exit_coord = begin["params"]["return_exit_coord"]
    scout.position_x, scout.position_y = square_grid_cell_to_world_xy(exit_coord["x"], exit_coord["y"])
    _issue_end_intent(sim)
    _issue_end_intent(sim)
    sim.advance_ticks(4)

    # Recontact original patrol after leave/return before kill.
    danger = sim.state.entities[DEFAULT_DANGER_ENTITY_ID]
    danger.speed_per_tick = 0.0
    scout.space_id = danger.space_id
    scout.position_x = danger.position_x
    scout.position_y = danger.position_y
    sim.advance_ticks(20)
    pending = sim.get_rules_state(CampaignDangerModule.name).get("pending_offer_by_player", {}).get("scout")
    assert isinstance(pending, dict)

    # Enter hub, turn in, and verify replacement patrol also recontacts.
    _enter_safe_hub(sim)
    scout.position_x, scout.position_y = square_grid_cell_to_world_xy(10, 3)
    sim.append_command(
        SimCommand(
            tick=sim.state.tick,
            entity_id="scout",
            command_type=TURN_IN_REWARD_TOKEN_INTENT_COMMAND_TYPE,
            params={},
        )
    )
    sim.advance_ticks(2)
    _exit_safe_hub(sim)
    danger = sim.state.entities[DEFAULT_DANGER_ENTITY_ID]
    danger.speed_per_tick = 0.0
    scout.space_id = danger.space_id
    scout.position_x = danger.position_x
    scout.position_y = danger.position_y
    sim.advance_ticks(20)
    pending = sim.get_rules_state(CampaignDangerModule.name).get("pending_offer_by_player", {}).get("scout")
    assert isinstance(pending, dict)

    # Repeat one more contact to ensure encounter control is not wedged.
    sim.append_command(
        SimCommand(
            tick=sim.state.tick,
            entity_id="scout",
            command_type=ACCEPT_ENCOUNTER_OFFER_INTENT,
            params={"entity_id": "scout"},
        )
    )
    sim.advance_ticks(3)
    state = sim.get_rules_state(CampaignDangerModule.name).get("encounter_control_by_player", {}).get("scout", {})
    assert state.get("state") in {"in_local", "returning", "post_encounter_cooldown", "pending_offer"}
