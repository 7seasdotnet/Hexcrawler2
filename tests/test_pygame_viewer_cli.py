from hexcrawler.cli.pygame_viewer import PLAYER_ID, SimulationController, _build_parser, _build_viewer_simulation
from hexcrawler.sim.encounters import (
    EncounterActionExecutionModule,
    EncounterActionModule,
    EncounterCheckModule,
    EncounterSelectionModule,
)


def test_viewer_parser_with_encounters_flag_defaults_to_disabled() -> None:
    parser = _build_parser()
    args = parser.parse_args([])

    assert args.with_encounters is False
    assert args.map_path == "content/examples/basic_map.json"


def test_viewer_parser_with_encounters_flag_can_be_enabled() -> None:
    parser = _build_parser()
    args = parser.parse_args(["--with-encounters"])

    assert args.with_encounters is True


def test_viewer_simulation_registers_encounter_modules_only_when_enabled() -> None:
    neutral_sim = _build_viewer_simulation(
        "content/examples/basic_map.json",
        with_encounters=False,
    )
    enabled_sim = _build_viewer_simulation(
        "content/examples/basic_map.json",
        with_encounters=True,
    )

    assert neutral_sim.get_rule_module(EncounterCheckModule.name) is None
    assert neutral_sim.get_rule_module(EncounterSelectionModule.name) is None
    assert neutral_sim.get_rule_module(EncounterActionModule.name) is None
    assert neutral_sim.get_rule_module(EncounterActionExecutionModule.name) is None
    assert enabled_sim.get_rule_module(EncounterCheckModule.name) is not None
    assert enabled_sim.get_rule_module(EncounterSelectionModule.name) is not None
    assert enabled_sim.get_rule_module(EncounterActionModule.name) is not None
    assert enabled_sim.get_rule_module(EncounterActionExecutionModule.name) is not None


def test_simulation_controller_appends_move_vector_command() -> None:
    sim = _build_viewer_simulation("content/examples/basic_map.json", with_encounters=False)
    controller = SimulationController(sim=sim, entity_id=PLAYER_ID)

    controller.set_move_vector(1.0, -1.0)

    assert sim.input_log[-1].command_type == "set_move_vector"
    assert sim.input_log[-1].tick == sim.state.tick
    assert sim.input_log[-1].entity_id == PLAYER_ID
    assert sim.input_log[-1].params == {"x": 1.0, "y": -1.0}
