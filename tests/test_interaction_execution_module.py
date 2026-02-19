from pathlib import Path

from hexcrawler.content.io import load_game_json, save_game_json
from hexcrawler.sim.core import EntityState, SimCommand, Simulation
from hexcrawler.sim.hash import simulation_hash
from hexcrawler.sim.interactions import INTERACTION_OUTCOME_EVENT_TYPE, InteractionExecutionModule
from hexcrawler.sim.world import AnchorRecord, DoorRecord, HexCoord, HexRecord, InteractableRecord, SpaceState, WorldState


def _build_world() -> WorldState:
    overworld = SpaceState(
        space_id="overworld",
        topology_type="hex_rectangle",
        topology_params={"width": 1, "height": 1},
        hexes={HexCoord(0, 0): HexRecord(terrain_type="plains")},
    )
    dungeon = SpaceState(
        space_id="dungeon:test",
        topology_type="square_grid",
        topology_params={"width": 4, "height": 4, "origin": {"x": 0, "y": 0}},
        doors={
            "door:1": DoorRecord(
                door_id="door:1",
                space_id="dungeon:test",
                a={"x": 1, "y": 1},
                b={"x": 2, "y": 1},
                state="closed",
            )
        },
        anchors={
            "anchor:exit": AnchorRecord(
                anchor_id="anchor:exit",
                space_id="dungeon:test",
                coord={"x": 0, "y": 0},
                kind="exit",
                target={"type": "space", "space_id": "overworld"},
            )
        },
        interactables={
            "int:1": InteractableRecord(
                interactable_id="int:1",
                space_id="dungeon:test",
                coord={"x": 3, "y": 3},
                kind="urn",
                state={"used": False},
            )
        },
    )
    return WorldState(spaces={"overworld": overworld, "dungeon:test": dungeon})


def _build_sim(seed: int = 13) -> Simulation:
    sim = Simulation(world=_build_world(), seed=seed)
    sim.add_entity(EntityState.from_hex(entity_id="scout", hex_coord=HexCoord(0, 0)))
    scout = sim.state.entities["scout"]
    scout.space_id = "dungeon:test"
    scout.position_x = 1.0
    scout.position_y = 1.0
    sim.register_rule_module(InteractionExecutionModule())
    return sim


def _interaction_outcomes(sim: Simulation) -> list[dict[str, object]]:
    return [entry for entry in sim.get_event_trace() if entry.get("event_type") == INTERACTION_OUTCOME_EVENT_TYPE]


def test_interaction_replay_hash_identity_same_seed_same_inputs() -> None:
    sim_a = _build_sim(seed=77)
    sim_b = _build_sim(seed=77)

    for sim in (sim_a, sim_b):
        sim.append_command(SimCommand(tick=0, entity_id="scout", command_type="interaction_intent", params={"interaction_type": "open", "target": {"kind": "door", "id": "door:1"}, "duration_ticks": 5}))
        sim.append_command(SimCommand(tick=10, entity_id="scout", command_type="interaction_intent", params={"interaction_type": "toggle", "target": {"kind": "door", "id": "door:1"}, "duration_ticks": 2}))
        sim.append_command(SimCommand(tick=20, entity_id="scout", command_type="interaction_intent", params={"interaction_type": "inspect", "target": {"kind": "interactable", "id": "int:1"}, "duration_ticks": 1}))

    sim_a.advance_ticks(40)
    sim_b.advance_ticks(40)

    assert simulation_hash(sim_a) == simulation_hash(sim_b)


def test_save_load_mid_interaction_does_not_double_apply(tmp_path: Path) -> None:
    sim = _build_sim(seed=80)
    sim.append_command(SimCommand(tick=0, entity_id="scout", command_type="interaction_intent", params={"interaction_type": "open", "target": {"kind": "door", "id": "door:1"}, "duration_ticks": 12}))

    sim.advance_ticks(6)
    save_path = tmp_path / "interaction_save.json"
    save_game_json(save_path, sim.state.world, sim)

    _, loaded = load_game_json(save_path)
    loaded.register_rule_module(InteractionExecutionModule())
    loaded.advance_ticks(20)

    outcomes = [entry for entry in _interaction_outcomes(loaded) if entry.get("params", {}).get("action_uid") == "0:0"]
    assert len(outcomes) == 1
    assert loaded.state.world.spaces["dungeon:test"].doors["door:1"].state == "open"


def test_unknown_target_is_safe_and_non_mutating() -> None:
    sim = _build_sim(seed=91)
    initial_state = sim.state.world.spaces["dungeon:test"].doors["door:1"].state
    sim.append_command(SimCommand(tick=0, entity_id="scout", command_type="interaction_intent", params={"interaction_type": "open", "target": {"kind": "door", "id": "door:404"}, "duration_ticks": 3}))

    sim.advance_ticks(6)

    outcomes = _interaction_outcomes(sim)
    assert outcomes
    assert outcomes[-1]["params"]["outcome"] == "unknown_target"
    assert sim.state.world.spaces["dungeon:test"].doors["door:1"].state == initial_state


def test_door_state_deterministic_across_save_load() -> None:
    commands = [
        SimCommand(tick=0, entity_id="scout", command_type="interaction_intent", params={"interaction_type": "open", "target": {"kind": "door", "id": "door:1"}, "duration_ticks": 1}),
        SimCommand(tick=5, entity_id="scout", command_type="interaction_intent", params={"interaction_type": "close", "target": {"kind": "door", "id": "door:1"}, "duration_ticks": 1}),
        SimCommand(tick=8, entity_id="scout", command_type="interaction_intent", params={"interaction_type": "toggle", "target": {"kind": "door", "id": "door:1"}, "duration_ticks": 1}),
    ]

    full_run = _build_sim(seed=123)
    for command in commands:
        full_run.append_command(command)
    full_run.advance_ticks(30)

    save_load_run = _build_sim(seed=123)
    for command in commands:
        save_load_run.append_command(command)
    save_load_run.advance_ticks(7)
    snapshot = save_load_run.simulation_payload()

    loaded = Simulation.from_simulation_payload(snapshot)
    loaded.register_rule_module(InteractionExecutionModule())
    loaded.advance_ticks(23)

    assert loaded.state.world.spaces["dungeon:test"].doors["door:1"].state == full_run.state.world.spaces["dungeon:test"].doors["door:1"].state
