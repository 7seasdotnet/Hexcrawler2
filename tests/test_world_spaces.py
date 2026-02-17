import json
from pathlib import Path

from hexcrawler.content.io import load_game_json, load_world_json, save_game_json
from hexcrawler.sim.core import EntityState, SimCommand, Simulation
from hexcrawler.sim.hash import save_hash, simulation_hash, world_hash
from hexcrawler.sim.location import LocationRef
from hexcrawler.sim.world import HexCoord, SiteRecord, SpaceState, WorldState


def _build_sim_with_runner(seed: int = 42) -> Simulation:
    world = load_world_json("content/examples/basic_map.json")
    world.spaces["dungeon_alpha"] = SpaceState(
        space_id="dungeon_alpha",
        topology_type="square_grid",
        topology_params={"width": 3, "height": 2, "origin": {"x": 0, "y": 0}},
    )
    world.sites = {
        "site_with_entrance": SiteRecord(
            site_id="site_with_entrance",
            site_type="dungeon_entrance",
            location={"space_id": "overworld", "topology_type": "overworld_hex", "coord": {"q": 0, "r": 0}},
            tags=["ruin", "alpha"],
            entrance={"target_space_id": "dungeon_alpha", "spawn": {"x": 1, "y": 1}},
        ),
        "site_no_entrance": SiteRecord(
            site_id="site_no_entrance",
            site_type="ruin",
            location={"space_id": "overworld", "topology_type": "overworld_hex", "coord": {"q": 0, "r": 0}},
        ),
        "site_unknown_target": SiteRecord(
            site_id="site_unknown_target",
            site_type="dungeon_entrance",
            location={"space_id": "overworld", "topology_type": "overworld_hex", "coord": {"q": 0, "r": 0}},
            entrance={"target_space_id": "missing_space", "spawn": {"q": 0, "r": 0}},
        ),
    }
    sim = Simulation(world=world, seed=seed)
    sim.add_entity(EntityState.from_hex(entity_id="runner", hex_coord=HexCoord(0, 0)))
    return sim


def test_world_state_from_legacy_payload_populates_default_overworld_space() -> None:
    legacy_world = {
        "topology_type": "custom",
        "topology_params": {},
        "hexes": [
            {
                "coord": {"q": 0, "r": 0},
                "record": {"terrain_type": "plains", "site_type": "none", "metadata": {}},
            }
        ],
    }

    world = WorldState.from_dict(legacy_world)

    assert "overworld" in world.spaces
    overworld = world.spaces["overworld"]
    assert overworld.space_id == "overworld"
    assert overworld.topology_type == "custom"
    assert overworld.topology_params == {}
    assert HexCoord(0, 0) in overworld.hexes
    assert world.sites == {}


def test_sites_hash_stability_and_round_trip(tmp_path: Path) -> None:
    sim = _build_sim_with_runner(seed=11)
    before_hash = world_hash(sim.state.world)

    save_path = tmp_path / "sites_save.json"
    save_game_json(save_path, sim.state.world, sim)
    payload_before = json.loads(save_path.read_text(encoding="utf-8"))

    loaded_world, loaded_sim = load_game_json(save_path)
    save_game_json(save_path, loaded_world, loaded_sim)
    payload_after = json.loads(save_path.read_text(encoding="utf-8"))

    assert payload_before["world_state"]["sites"] == payload_after["world_state"]["sites"]
    assert payload_before["save_hash"] == payload_after["save_hash"]
    assert payload_before["save_hash"] == save_hash(payload_after)
    assert before_hash == world_hash(loaded_world)
    assert [site.site_id for site in loaded_world.get_sites_at_location({"space_id": "overworld", "coord": {"q": 0, "r": 0}})] == [
        "site_no_entrance",
        "site_unknown_target",
        "site_with_entrance",
    ]


def test_enter_site_valid_transitions_and_is_deterministic() -> None:
    sim_a = _build_sim_with_runner(seed=999)
    sim_b = _build_sim_with_runner(seed=999)

    command = SimCommand(
        tick=0,
        entity_id="runner",
        command_type="enter_site",
        params={"site_id": "site_with_entrance"},
    )

    for sim in (sim_a, sim_b):
        sim.append_command(command)
        sim.advance_ticks(2)

    for sim in (sim_a, sim_b):
        runner = sim.state.entities["runner"]
        assert runner.space_id == "dungeon_alpha"

    assert simulation_hash(sim_a) == simulation_hash(sim_b)


def test_enter_site_failure_outcomes_do_not_mutate_entity_state() -> None:
    for site_id, expected in [
        ("unknown_site_id", "unknown_site"),
        ("site_no_entrance", "no_entrance"),
        ("site_unknown_target", "unknown_target_space"),
    ]:
        sim = _build_sim_with_runner(seed=17)
        before = simulation_hash(sim)
        sim.append_command(SimCommand(tick=0, entity_id="runner", command_type="enter_site", params={"site_id": site_id}))
        sim.advance_ticks(1)

        events = [entry for entry in sim.get_event_trace() if entry["event_type"] == "site_enter_outcome"]
        assert events
        assert events[-1]["params"]["outcome"] == expected
        assert sim.state.entities["runner"].space_id == "overworld"
        assert simulation_hash(sim) != before
        assert not [entry for entry in sim.get_event_trace() if entry["event_type"] == "space_transition"]


def test_enter_site_replay_and_save_load_stability(tmp_path: Path) -> None:
    sim_live = _build_sim_with_runner(seed=23)
    command = SimCommand(tick=0, entity_id="runner", command_type="enter_site", params={"site_id": "site_with_entrance"})
    sim_live.append_command(command)
    sim_live.advance_ticks(8)

    sim_replay = _build_sim_with_runner(seed=23)
    sim_replay.append_command(command)
    sim_replay.advance_ticks(8)
    assert simulation_hash(sim_live) == simulation_hash(sim_replay)

    save_path = tmp_path / "site_replay.json"
    save_game_json(save_path, sim_live.state.world, sim_live)
    loaded_world, loaded_sim = load_game_json(save_path)
    assert world_hash(loaded_world) == world_hash(sim_live.state.world)
    assert simulation_hash(loaded_sim) == simulation_hash(sim_live)


def test_square_grid_space_round_trip_and_hash_stability(tmp_path: Path) -> None:
    sim = _build_sim_with_runner(seed=123)
    save_path = tmp_path / "square_grid_save.json"
    save_game_json(save_path, sim.state.world, sim)
    world_before = world_hash(sim.state.world)
    sim_before = simulation_hash(sim)

    loaded_world, loaded_sim = load_game_json(save_path)

    assert world_before == world_hash(loaded_world)
    assert sim_before == simulation_hash(loaded_sim)
    assert loaded_world.spaces["dungeon_alpha"].topology_type == "square_grid"
    assert loaded_world.spaces["dungeon_alpha"].iter_cells() == [
        {"x": 0, "y": 0},
        {"x": 1, "y": 0},
        {"x": 2, "y": 0},
        {"x": 0, "y": 1},
        {"x": 1, "y": 1},
        {"x": 2, "y": 1},
    ]


def test_square_grid_location_ref_validation_and_space_validity() -> None:
    space = SpaceState(
        space_id="demo_room_grid",
        topology_type="square_grid",
        topology_params={"width": 2, "height": 2, "origin": {"x": -1, "y": 0}},
    )

    valid = LocationRef.from_dict(
        {"space_id": "demo_room_grid", "topology_type": "square_grid", "coord": {"x": -1, "y": 1}}
    )
    assert valid.coord == {"x": -1, "y": 1}
    assert space.is_valid_cell(valid.coord)
    assert not space.is_valid_cell({"x": 3, "y": 0})

    try:
        LocationRef.from_dict({"space_id": "demo_room_grid", "topology_type": "square_grid", "coord": {"x": 0}})
        raise AssertionError("expected ValueError for invalid square_grid coord")
    except ValueError:
        pass


def test_transition_space_to_square_grid_is_deterministic() -> None:
    sim_a = _build_sim_with_runner(seed=444)
    sim_b = _build_sim_with_runner(seed=444)
    transition = SimCommand(
        tick=0,
        entity_id="runner",
        command_type="transition_space",
        params={
            "to_location": {"space_id": "dungeon_alpha", "topology_type": "square_grid", "coord": {"x": 0, "y": 0}},
            "reason": "test",
        },
    )

    for sim in (sim_a, sim_b):
        sim.append_command(transition)
        sim.advance_ticks(1)
        assert sim.state.entities["runner"].space_id == "dungeon_alpha"
        assert (sim.state.entities["runner"].position_x, sim.state.entities["runner"].position_y) == (0.5, 0.5)

    assert simulation_hash(sim_a) == simulation_hash(sim_b)
