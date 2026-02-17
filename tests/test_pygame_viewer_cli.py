from pathlib import Path

import pytest

from hexcrawler.cli.pygame_viewer import (
    PLAYER_ID,
    SimulationController,
    _build_parser,
    _build_viewer_simulation,
    _find_entity_at_pixel,
    _load_viewer_simulation,
    _save_viewer_simulation,
)
from hexcrawler.sim.core import EntityState
from hexcrawler.sim.encounters import (
    ENCOUNTER_ACTION_OUTCOME_EVENT_TYPE,
    EncounterActionExecutionModule,
    EncounterActionModule,
    EncounterCheckModule,
    EncounterSelectionModule,
    SpawnMaterializationModule,
)
from hexcrawler.sim.hash import simulation_hash
from hexcrawler.sim.world import HexCoord


def test_viewer_parser_with_encounters_flag_defaults_to_disabled() -> None:
    parser = _build_parser()
    args = parser.parse_args([])

    assert args.with_encounters is False
    assert args.map_path == "content/examples/viewer_map.json"
    assert args.save_path == "saves/session_save.json"
    assert args.load_save is None


def test_viewer_parser_with_encounters_flag_can_be_enabled() -> None:
    parser = _build_parser()
    args = parser.parse_args(["--with-encounters", "--save-path", "saves/dev.json", "--load-save", "saves/dev.json"])

    assert args.with_encounters is True
    assert args.save_path == "saves/dev.json"
    assert args.load_save == "saves/dev.json"


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
    assert neutral_sim.get_rule_module(SpawnMaterializationModule.name) is None
    assert enabled_sim.get_rule_module(EncounterCheckModule.name) is not None
    assert enabled_sim.get_rule_module(EncounterSelectionModule.name) is not None
    assert enabled_sim.get_rule_module(EncounterActionModule.name) is not None
    assert enabled_sim.get_rule_module(EncounterActionExecutionModule.name) is not None
    assert enabled_sim.get_rule_module(SpawnMaterializationModule.name) is not None


def test_simulation_controller_appends_move_vector_command() -> None:
    sim = _build_viewer_simulation("content/examples/basic_map.json", with_encounters=False)
    controller = SimulationController(sim=sim, entity_id=PLAYER_ID)

    controller.set_move_vector(1.0, -1.0)

    assert sim.input_log[-1].command_type == "set_move_vector"
    assert sim.input_log[-1].tick == sim.state.tick
    assert sim.input_log[-1].entity_id == PLAYER_ID
    assert sim.input_log[-1].params == {"x": 1.0, "y": -1.0}




def test_simulation_controller_appends_selection_commands() -> None:
    sim = _build_viewer_simulation("content/examples/basic_map.json", with_encounters=False)
    controller = SimulationController(sim=sim, entity_id=PLAYER_ID)

    controller.set_selected_entity(PLAYER_ID)
    controller.clear_selected_entity()

    assert sim.input_log[-2].command_type == "set_selected_entity"
    assert sim.input_log[-2].params == {"selected_entity_id": PLAYER_ID}
    assert sim.input_log[-1].command_type == "clear_selected_entity"
    assert sim.input_log[-1].params == {}

def test_main_help_prints_usage_without_starting_viewer(capsys: pytest.CaptureFixture[str]) -> None:
    from hexcrawler.cli.pygame_viewer import main

    with pytest.raises(SystemExit) as result:
        main(["--help"])

    captured = capsys.readouterr()
    assert result.value.code == 0
    assert "usage:" in captured.out
    assert "--headless" in captured.out


def test_main_headless_mode_exits_cleanly_and_warns(capsys: pytest.CaptureFixture[str]) -> None:
    from hexcrawler.cli.pygame_viewer import main

    with pytest.raises(SystemExit) as result:
        main(["--headless"])

    captured = capsys.readouterr()
    assert result.value.code == 0
    assert "headless mode active" in captured.out


def test_viewer_save_load_round_trip_preserves_tick_log_hash_and_artifacts(tmp_path: Path) -> None:
    sim = _build_viewer_simulation("content/examples/basic_map.json", with_encounters=True)
    sim.advance_ticks(160)
    sim.state.world.upsert_signal(
        {
            "signal_uid": "sig-test",
            "created_tick": sim.state.tick,
            "template_id": "smoke_column",
            "location": {"topology_type": "hex", "coord": {"q": 1, "r": 0}},
            "expires_tick": sim.state.tick + 100,
        }
    )
    sim.state.world.upsert_track(
        {
            "track_uid": "trk-test",
            "created_tick": sim.state.tick,
            "template_id": "wolf_tracks",
            "location": {"topology_type": "hex", "coord": {"q": 1, "r": 1}},
            "expires_tick": sim.state.tick + 100,
        }
    )
    sim.schedule_event_at(
        sim.state.tick,
        ENCOUNTER_ACTION_OUTCOME_EVENT_TYPE,
        {
            "action_uid": "outcome-test",
            "action_type": "signal_intent",
            "outcome": "applied",
            "template_id": "smoke_column",
        },
    )
    sim.advance_ticks(1)

    save_path = tmp_path / "viewer_round_trip.json"
    _save_viewer_simulation(sim, str(save_path))
    loaded = _load_viewer_simulation(str(save_path), with_encounters=True)

    assert loaded.state.tick == sim.state.tick
    assert len(loaded.input_log) == len(sim.input_log)
    assert simulation_hash(loaded) == simulation_hash(sim)
    assert loaded.state.world.signals == sim.state.world.signals
    assert loaded.state.world.tracks == sim.state.world.tracks
    assert loaded.get_event_trace() == sim.get_event_trace()


def test_find_entity_at_pixel_uses_deterministic_tie_break() -> None:
    sim = _build_viewer_simulation("content/examples/basic_map.json", with_encounters=False)
    sim.add_entity(EntityState.from_hex(entity_id="alpha", hex_coord=HexCoord(0, 0)))
    sim.add_entity(EntityState.from_hex(entity_id="beta", hex_coord=HexCoord(0, 0)))

    hit = _find_entity_at_pixel(sim, (0, 0), (0.0, 0.0), radius_px=20.0)

    assert hit == "alpha"
