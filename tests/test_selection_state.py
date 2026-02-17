from hexcrawler.content.io import load_world_json
from hexcrawler.sim.core import EntityState, SimCommand, Simulation
from hexcrawler.sim.hash import simulation_hash
from hexcrawler.sim.world import HexCoord


def _build_sim() -> Simulation:
    sim = Simulation(world=load_world_json("content/examples/basic_map.json"), seed=9)
    sim.add_entity(EntityState.from_hex(entity_id="scout", hex_coord=HexCoord(0, 0)))
    sim.add_entity(EntityState.from_hex(entity_id="npc", hex_coord=HexCoord(1, 0)))
    return sim


def test_selection_commands_apply_and_clear() -> None:
    sim = _build_sim()
    sim.append_command(
        SimCommand(
            tick=0,
            entity_id="scout",
            command_type="set_selected_entity",
            params={"selected_entity_id": "npc"},
        )
    )
    sim.append_command(SimCommand(tick=1, entity_id="scout", command_type="clear_selected_entity", params={}))

    sim.advance_ticks(2)

    assert sim.selected_entity_id(owner_entity_id="scout") is None


def test_selection_state_save_load_round_trip() -> None:
    sim = _build_sim()
    sim.append_command(
        SimCommand(
            tick=0,
            entity_id="scout",
            command_type="set_selected_entity",
            params={"selected_entity_id": "npc"},
        )
    )
    sim.advance_ticks(1)

    payload = sim.simulation_payload()
    restored = Simulation.from_simulation_payload(payload)

    assert restored.selected_entity_id(owner_entity_id="scout") == "npc"


def test_selection_is_hash_covered() -> None:
    a = _build_sim()
    b = _build_sim()
    a.append_command(
        SimCommand(tick=0, entity_id="scout", command_type="set_selected_entity", params={"selected_entity_id": "npc"})
    )
    a.advance_ticks(1)

    assert simulation_hash(a) != simulation_hash(b)


def test_selection_replay_is_deterministic() -> None:
    def run_once() -> str:
        sim = _build_sim()
        sim.append_command(
            SimCommand(tick=2, entity_id="scout", command_type="set_selected_entity", params={"selected_entity_id": "npc"})
        )
        sim.advance_ticks(6)
        return simulation_hash(sim)

    assert run_once() == run_once()
