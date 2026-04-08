from pathlib import Path

from hexcrawler.cli.runtime_profiles import CORE_PLAYABLE, configure_runtime_profile
from hexcrawler.content.io import load_game_json, load_world_json, save_game_json
from hexcrawler.sim.core import EntityState, SimCommand, Simulation
from hexcrawler.sim.exploration import LOCAL_DUNGEON_AUTHOR_INTENT_COMMAND_TYPE
from hexcrawler.sim.hash import simulation_hash, world_hash

MAP_PATH = "content/examples/viewer_map.json"
PROVING_GROUND_SPACE_ID = "local_site:demo_dungeon_entrance"
PROVING_GROUND_SITE_ID = "demo_dungeon_entrance"


def _build_core_playable_sim(*, seed: int = 7) -> Simulation:
    world = load_world_json(MAP_PATH)
    sim = Simulation(world=world, seed=seed)
    configure_runtime_profile(sim, CORE_PLAYABLE)
    return sim


def _add_scout_at_dungeon_entrance(sim: Simulation) -> None:
    site = sim.state.world.sites[PROVING_GROUND_SITE_ID]
    anchor = site.location.get("campaign_anchor") if isinstance(site.location, dict) else None
    assert isinstance(anchor, dict)
    sim.add_entity(
        EntityState(
            entity_id="scout",
            position_x=float(anchor["x"]),
            position_y=float(anchor["y"]),
            space_id="overworld",
            speed_per_tick=0.20,
        )
    )


def test_proving_ground_authored_data_is_present_and_bounded() -> None:
    world = load_world_json(MAP_PATH)
    site = world.sites[PROVING_GROUND_SITE_ID]
    assert isinstance(site.entrance, dict)
    assert site.entrance.get("target_space_id") == PROVING_GROUND_SPACE_ID

    local_space = world.spaces[PROVING_GROUND_SPACE_ID]
    assert local_space.role == "local"
    assert len(local_space.structure_primitives) == 2
    assert any(row.get("spawner_id") == "pg_hostile_a" for row in local_space.local_hostile_spawners)
    point_kinds = {str(row.get("point_kind", "")) for row in local_space.local_transition_points}
    assert {"entry_anchor", "extraction_exit", "return_to_origin_exit"}.issubset(point_kinds)


def test_proving_ground_entry_and_return_to_origin_flow() -> None:
    sim = _build_core_playable_sim(seed=101)
    _add_scout_at_dungeon_entrance(sim)

    sim.append_command(
        SimCommand(
            tick=sim.state.tick,
            entity_id="scout",
            command_type="enter_site",
            params={"site_id": PROVING_GROUND_SITE_ID},
        )
    )
    sim.advance_ticks(2)

    scout = sim.state.entities["scout"]
    assert scout.space_id == PROVING_GROUND_SPACE_ID

    sim.append_command(
        SimCommand(
            tick=sim.state.tick,
            entity_id="scout",
            command_type=LOCAL_DUNGEON_AUTHOR_INTENT_COMMAND_TYPE,
            params={"operation": "use_transition_point", "point_id": "return_to_origin_default"},
        )
    )
    sim.advance_ticks(2)

    scout = sim.state.entities["scout"]
    assert scout.space_id == "overworld"


def test_proving_ground_hostile_spawner_materializes_in_linked_local_space() -> None:
    sim = _build_core_playable_sim(seed=102)
    _add_scout_at_dungeon_entrance(sim)

    sim.append_command(
        SimCommand(
            tick=sim.state.tick,
            entity_id="scout",
            command_type="enter_site",
            params={"site_id": PROVING_GROUND_SITE_ID},
        )
    )
    sim.advance_ticks(2)

    spawned = [
        entity_id
        for entity_id, row in sim.state.entities.items()
        if row.space_id == PROVING_GROUND_SPACE_ID
        and isinstance(row.stats, dict)
        and str(row.stats.get("authored_spawner_id", "")) == "pg_hostile_a"
    ]
    assert spawned == ["authored:local_site:demo_dungeon_entrance:pg_hostile_a:0"]


def test_proving_ground_save_load_hash_stability(tmp_path: Path) -> None:
    sim = _build_core_playable_sim(seed=103)
    _add_scout_at_dungeon_entrance(sim)

    sim.append_command(
        SimCommand(
            tick=sim.state.tick,
            entity_id="scout",
            command_type="enter_site",
            params={"site_id": PROVING_GROUND_SITE_ID},
        )
    )
    sim.advance_ticks(4)

    before_world_hash = world_hash(sim.state.world)
    before_sim_hash = simulation_hash(sim)

    save_path = tmp_path / "proving_ground_save.json"
    save_game_json(save_path, sim.state.world, sim)
    loaded_world, loaded_sim = load_game_json(str(save_path))

    assert world_hash(loaded_world) == before_world_hash
    assert simulation_hash(loaded_sim) == before_sim_hash
