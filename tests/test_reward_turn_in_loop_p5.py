from __future__ import annotations

from pathlib import Path

from hexcrawler.content.io import load_game_json, load_world_json, save_game_json
from hexcrawler.sim.combat import ATTACK_INTENT_COMMAND_TYPE, CombatExecutionModule
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
    REWARD_TURN_IN_OUTCOME_EVENT_TYPE,
    TURN_IN_REWARD_TOKEN_INTENT_COMMAND_TYPE,
    ExplorationExecutionModule,
)
from hexcrawler.sim.hash import simulation_hash
from hexcrawler.sim.movement import square_grid_cell_to_world_xy
from hexcrawler.sim.world import CAMPAIGN_SPACE_ROLE, SiteRecord, SpaceState


CAMPAIGN_SPACE_ID = "campaign_plane_beta"
SAFE_SITE_ID = "greybridge_safe"


def _build_sim(seed: int = 123) -> Simulation:
    world = load_world_json("content/examples/basic_map.json")
    world.spaces[CAMPAIGN_SPACE_ID] = SpaceState(
        space_id=CAMPAIGN_SPACE_ID,
        role=CAMPAIGN_SPACE_ROLE,
        topology_type="square_grid",
        topology_params={"width": 6, "height": 6, "origin": {"x": 10, "y": 20}},
    )
    world.sites[SAFE_SITE_ID] = SiteRecord(
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

    # keep player at deterministic return exit
    rx, ry = square_grid_cell_to_world_xy(begin["params"]["return_exit_coord"]["x"], begin["params"]["return_exit_coord"]["y"])
    sim.state.entities["scout"].position_x = rx
    sim.state.entities["scout"].position_y = ry
    assert sim.state.entities["scout"].space_id == local_space_id


def test_local_success_grants_single_reward_token_and_persists_after_return() -> None:
    sim = _build_sim(seed=11)
    _schedule_request(sim)
    sim.advance_ticks(3)
    _prepare_incapacitated_hostile(sim)

    _issue_end_intent(sim)
    _issue_end_intent(sim)
    sim.advance_ticks(3)

    reward_events = _trace(sim, LOCAL_ENCOUNTER_REWARD_EVENT_TYPE)
    assert reward_events[-1]["params"]["applied"] is True
    assert reward_events[-1]["params"]["reason"] == "token_granted"

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

    for offset in range(3):
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
    sim.advance_ticks(4)
    assert len(hostile.wounds) >= 3

    exit_coord = begin["params"]["return_exit_coord"]
    player.position_x, player.position_y = square_grid_cell_to_world_xy(exit_coord["x"], exit_coord["y"])
    _issue_end_intent(sim)
    sim.advance_ticks(3)

    reward = _trace(sim, LOCAL_ENCOUNTER_REWARD_EVENT_TYPE)[-1]["params"]
    assert reward["applied"] is True
    assert reward["reason"] == "token_granted"
    assert reward["details"]["incapacitated_hostiles"] >= 1
    assert _player_items(sim).get("proof_token", 0) == 1



def test_reward_turn_in_succeeds_only_at_safe_site_and_grants_ration() -> None:
    sim = _build_sim(seed=12)
    _schedule_request(sim)
    sim.advance_ticks(3)
    _prepare_incapacitated_hostile(sim)
    _issue_end_intent(sim)
    sim.advance_ticks(3)

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
            tick=0,
            entity_id="scout",
            command_type=TURN_IN_REWARD_TOKEN_INTENT_COMMAND_TYPE,
            params={},
        )
    )
    sim.advance_ticks(1)

    outcome = _trace(sim, REWARD_TURN_IN_OUTCOME_EVENT_TYPE)[0]["params"]
    assert outcome["applied"] is False
    assert outcome["reason"] == "safe_site_required"
    assert _player_items(sim).get("proof_token", 0) == 1



def test_reward_turn_in_rejected_when_token_absent() -> None:
    sim = _build_sim(seed=14)
    sim.append_command(
        SimCommand(
            tick=0,
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
        _issue_end_intent(sim)
        sim.advance_ticks(3)

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
    _issue_end_intent(sim)
    sim.advance_ticks(3)

    reward = _trace(sim, LOCAL_ENCOUNTER_REWARD_EVENT_TYPE)[0]["params"]
    assert reward["applied"] is False
    assert reward["reason"] == "no_incapacitated_hostile"
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

    _issue_end_intent(sim)
    sim.advance_ticks(3)

    reward = _trace(sim, LOCAL_ENCOUNTER_REWARD_EVENT_TYPE)[0]["params"]
    assert reward["applied"] is False
    assert reward["reason"] == "no_incapacitated_hostile"
    assert _player_items(sim).get("proof_token", 0) == 0


def test_turn_in_refunds_token_if_benefit_grant_fails(monkeypatch) -> None:
    sim = _build_sim(seed=18)
    container_id = sim.state.entities["scout"].inventory_container_id
    assert container_id is not None
    sim.state.world.containers[container_id].items["proof_token"] = 1

    from hexcrawler.sim import exploration as exploration_module

    monkeypatch.setattr(exploration_module, "REWARD_TURN_IN_BENEFIT_ITEM_ID", "missing_item")

    sim.append_command(
        SimCommand(
            tick=0,
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
