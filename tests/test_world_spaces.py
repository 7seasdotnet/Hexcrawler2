import json
from pathlib import Path

from hexcrawler.content.io import load_game_json, load_world_json, save_game_json
from hexcrawler.sim.core import EntityState, SimCommand, Simulation
from hexcrawler.sim.hash import save_hash, simulation_hash
from hexcrawler.sim.world import HexCoord, WorldState


def _build_sim_with_runner(seed: int = 42) -> Simulation:
    world = load_world_json("content/examples/basic_map.json")
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


def test_save_load_round_trip_preserves_world_spaces_and_location_space_id(tmp_path: Path) -> None:
    sim = _build_sim_with_runner(seed=77)
    sim.append_command(
        SimCommand(
            tick=0,
            entity_id="runner",
            command_type="transition_space",
            params={
                "to_location": {
                    "space_id": "overworld",
                    "topology_type": "overworld_hex",
                    "coord": {"q": 1, "r": 0},
                },
                "reason": "test",
                "site_id": "site-a",
            },
        )
    )
    sim.advance_ticks(2)

    save_path = tmp_path / "spaces_save.json"
    save_game_json(save_path, sim.state.world, sim)
    payload_before = json.loads(save_path.read_text(encoding="utf-8"))

    loaded_world, loaded_sim = load_game_json(save_path)
    save_game_json(save_path, loaded_world, loaded_sim)
    payload_after = json.loads(save_path.read_text(encoding="utf-8"))

    assert payload_before["world_state"]["spaces"] == payload_after["world_state"]["spaces"]
    assert payload_before["save_hash"] == payload_after["save_hash"]
    assert payload_before["save_hash"] == save_hash(payload_after)

    transition_events = [
        entry for entry in loaded_sim.get_event_trace() if entry["event_type"] == "space_transition"
    ]
    assert transition_events
    assert transition_events[0]["params"]["from_location"]["space_id"] == "overworld"
    assert transition_events[0]["params"]["to_location"]["space_id"] == "overworld"


def test_transition_space_command_deterministic_and_moves_entity() -> None:
    sim_a = _build_sim_with_runner(seed=999)
    sim_b = _build_sim_with_runner(seed=999)

    command = SimCommand(
        tick=0,
        entity_id="runner",
        command_type="transition_space",
        params={
            "to_location": {
                "space_id": "overworld",
                "topology_type": "overworld_hex",
                "coord": {"q": 1, "r": 0},
            },
            "reason": "enter_site",
            "site_id": "dungeon-01",
        },
    )

    for sim in (sim_a, sim_b):
        sim.append_command(command)
        sim.advance_ticks(2)

    for sim in (sim_a, sim_b):
        runner = sim.state.entities["runner"]
        assert runner.space_id == "overworld"
        assert runner.hex_coord == HexCoord(1, 0)

    assert simulation_hash(sim_a) == simulation_hash(sim_b)


def test_transition_space_rejects_unknown_space_with_deterministic_trace() -> None:
    sim = _build_sim_with_runner(seed=17)
    sim.append_command(
        SimCommand(
            tick=0,
            entity_id="runner",
            command_type="transition_space",
            params={
                "to_location": {
                    "space_id": "missing_space",
                    "topology_type": "dungeon_grid",
                    "coord": {"x": 0, "y": 0},
                }
            },
        )
    )

    sim.advance_ticks(1)

    event = [entry for entry in sim.get_event_trace() if entry["event_type"] == "space_transition"][0]
    assert event["params"]["status"] == "rejected_unknown_space"
