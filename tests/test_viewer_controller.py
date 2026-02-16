from hexcrawler.cli.viewer import SimulationController
from hexcrawler.content.io import load_world_json
from hexcrawler.sim.core import EntityState, Simulation
from hexcrawler.sim.world import HexCoord


def test_ascii_viewer_controller_goto_appends_command() -> None:
    world = load_world_json("content/examples/basic_map.json")
    sim = Simulation(world=world, seed=44)
    sim.add_entity(EntityState.from_hex(entity_id="scout", hex_coord=HexCoord(0, 0), speed_per_tick=0.2))
    controller = SimulationController(sim)

    controller.set_destination("scout", 1, 0)

    assert sim.input_log[-1].command_type == "set_target_position"
    assert sim.input_log[-1].entity_id == "scout"
    assert sim.input_log[-1].tick == 0
