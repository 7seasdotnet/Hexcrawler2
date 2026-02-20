import json
from pathlib import Path

from hexcrawler.content.io import load_game_json, save_game_json
from hexcrawler.sim.core import Simulation
from hexcrawler.sim.hash import simulation_hash, world_hash
from hexcrawler.sim.world import CAMPAIGN_SPACE_ROLE, LOCAL_SPACE_ROLE, SpaceState, WorldState


def _build_world_with_arena_role(*, arena_role: str) -> WorldState:
    overworld = SpaceState(
        space_id="overworld",
        topology_type="square_grid",
        role=CAMPAIGN_SPACE_ROLE,
        topology_params={"width": 2, "height": 1, "origin": {"x": 0, "y": 0}},
    )
    arena = SpaceState(
        space_id="arena",
        topology_type="square_grid",
        role=arena_role,
        topology_params={"width": 2, "height": 1, "origin": {"x": 0, "y": 0}},
    )
    return WorldState(spaces={"overworld": overworld, "arena": arena})


def _space_dict_by_id(world_payload: dict) -> dict[str, dict]:
    return {space["space_id"]: space for space in world_payload["spaces"]}


def test_space_role_changes_world_and_save_and_hashes(tmp_path: Path) -> None:
    world_local = _build_world_with_arena_role(arena_role=LOCAL_SPACE_ROLE)
    world_campaign = _build_world_with_arena_role(arena_role=CAMPAIGN_SPACE_ROLE)

    local_dict = world_local.to_dict()
    campaign_dict = world_campaign.to_dict()

    local_spaces = _space_dict_by_id(local_dict)
    campaign_spaces = _space_dict_by_id(campaign_dict)

    assert local_spaces["arena"]["role"] == LOCAL_SPACE_ROLE
    assert campaign_spaces["arena"]["role"] == CAMPAIGN_SPACE_ROLE
    assert local_dict != campaign_dict

    assert world_hash(world_local) != world_hash(world_campaign)

    sim_local = Simulation(world=world_local, seed=7)
    sim_campaign = Simulation(world=world_campaign, seed=7)

    local_path = tmp_path / "role_local.json"
    campaign_path = tmp_path / "role_campaign.json"
    save_game_json(local_path, world_local, sim_local)
    save_game_json(campaign_path, world_campaign, sim_campaign)

    local_payload = json.loads(local_path.read_text(encoding="utf-8"))
    campaign_payload = json.loads(campaign_path.read_text(encoding="utf-8"))

    local_save_spaces = _space_dict_by_id(local_payload["world_state"])
    campaign_save_spaces = _space_dict_by_id(campaign_payload["world_state"])

    assert local_save_spaces["arena"]["role"] == LOCAL_SPACE_ROLE
    assert campaign_save_spaces["arena"]["role"] == CAMPAIGN_SPACE_ROLE
    assert local_payload != campaign_payload
    assert local_payload["save_hash"] != campaign_payload["save_hash"]

    loaded_local_world, _ = load_game_json(local_path)
    loaded_campaign_world, _ = load_game_json(campaign_path)
    assert loaded_local_world.spaces["arena"].role == LOCAL_SPACE_ROLE
    assert loaded_campaign_world.spaces["arena"].role == CAMPAIGN_SPACE_ROLE

    # simulation_hash includes simulation.state.world.to_dict(), so space role differences
    # must change simulation_hash directly (not only via world_hash/save_hash).
    assert simulation_hash(sim_local) != simulation_hash(sim_campaign)
