from pathlib import Path

from hexcrawler.content.io import load_game_json, load_world_json, save_game_json
from hexcrawler.sim.core import Simulation
from hexcrawler.cli.play import DEFAULT_MAP_PATH, DEFAULT_SAVE_PATH, main
from hexcrawler.cli.runtime_profiles import CORE_PLAYABLE, DEFAULT_RUNTIME_PROFILE


def test_play_launcher_creates_default_save_when_missing(tmp_path: Path, monkeypatch) -> None:
    save_path = tmp_path / "canonical.json"

    def fake_run(**kwargs):
        assert kwargs["runtime_profile"] == DEFAULT_RUNTIME_PROFILE
        assert kwargs["load_save"] == str(save_path)
        assert kwargs["save_path"] == str(save_path)
        return 0

    monkeypatch.setattr("hexcrawler.cli.play.run_pygame_viewer", fake_run)

    result = main(["--headless", "--load-save", str(save_path), "--map-path", "content/examples/viewer_map.json", "--seed", "7"])

    assert result == 0
    assert save_path.exists()


def test_play_launcher_defaults_to_canonical_save_path(monkeypatch) -> None:
    captured = {}

    def fake_run(**kwargs):
        captured.update(kwargs)
        return 0

    monkeypatch.setattr("hexcrawler.cli.play.run_pygame_viewer", fake_run)
    monkeypatch.setattr(
        "hexcrawler.cli.play._ensure_save_exists",
        lambda **_: type(
            "StartupTruthStub",
            (),
            {
                "source_map_path": DEFAULT_MAP_PATH,
                "source_save_path": DEFAULT_SAVE_PATH,
                "rebuilt_save": False,
                "major_site_rows": (),
                "home_town_count": 0,
                "dungeon_entrance_count": 0,
                "patrol_count": 0,
            },
        )(),
    )

    result = main(["--headless"])

    assert result == 0
    assert captured["load_save"] == DEFAULT_SAVE_PATH
    assert captured["save_path"] == DEFAULT_SAVE_PATH
    assert captured["map_path"] == DEFAULT_MAP_PATH
    assert captured["runtime_profile"] == DEFAULT_RUNTIME_PROFILE


def test_play_launcher_runtime_profile_override(monkeypatch) -> None:
    captured = {}

    def fake_run(**kwargs):
        captured.update(kwargs)
        return 0

    monkeypatch.setattr("hexcrawler.cli.play.run_pygame_viewer", fake_run)
    monkeypatch.setattr(
        "hexcrawler.cli.play._ensure_save_exists",
        lambda **_: type(
            "StartupTruthStub",
            (),
            {
                "source_map_path": DEFAULT_MAP_PATH,
                "source_save_path": DEFAULT_SAVE_PATH,
                "rebuilt_save": False,
                "major_site_rows": (),
                "home_town_count": 0,
                "dungeon_entrance_count": 0,
                "patrol_count": 0,
            },
        )(),
    )

    result = main(["--headless", "--runtime-profile", "experimental_world"])

    assert result == 0
    assert captured["runtime_profile"] == "experimental_world"


def test_play_launcher_rebuilds_save_when_existing_world_mismatches_map(tmp_path: Path, monkeypatch) -> None:
    save_path = tmp_path / "canonical.json"
    stale_world = load_world_json("content/examples/basic_map.json")
    stale_sim = Simulation(world=stale_world, seed=7)
    save_game_json(save_path, stale_world, stale_sim)

    def fake_run(**kwargs):
        assert kwargs["load_save"] == str(save_path)
        return 0

    monkeypatch.setattr("hexcrawler.cli.play.run_pygame_viewer", fake_run)
    monkeypatch.setattr("hexcrawler.cli.play.DEFAULT_SAVE_PATH", str(save_path))
    monkeypatch.setattr("hexcrawler.cli.play.DEFAULT_MAP_PATH", "content/examples/viewer_map.json")
    result = main(["--headless", "--load-save", str(save_path), "--map-path", "content/examples/viewer_map.json", "--seed", "7"])

    assert result == 0
    world, _ = load_game_json(str(save_path))
    assert "home_greybridge" in world.sites
    assert "demo_dungeon_entrance" in world.sites


def test_play_launcher_keeps_existing_explicit_save_when_not_default_path(tmp_path: Path, monkeypatch) -> None:
    save_path = tmp_path / "explicit.json"
    stale_world = load_world_json("content/examples/basic_map.json")
    stale_sim = Simulation(world=stale_world, seed=7)
    save_game_json(save_path, stale_world, stale_sim)

    def fake_run(**kwargs):
        assert kwargs["load_save"] == str(save_path)
        return 0

    monkeypatch.setattr("hexcrawler.cli.play.run_pygame_viewer", fake_run)
    result = main(["--headless", "--load-save", str(save_path), "--map-path", "content/examples/viewer_map.json", "--seed", "7"])

    assert result == 0
    world, _ = load_game_json(str(save_path))
    assert "home_greybridge" not in world.sites


def test_play_launcher_default_core_playable_rebuilds_when_scene_is_missing(tmp_path: Path, monkeypatch) -> None:
    save_path = tmp_path / "canonical.json"
    world = load_world_json("content/examples/viewer_map.json")
    stale_sim = Simulation(world=world, seed=7)
    save_game_json(save_path, world, stale_sim)

    monkeypatch.setattr("hexcrawler.cli.play.DEFAULT_SAVE_PATH", str(save_path))
    monkeypatch.setattr("hexcrawler.cli.play.DEFAULT_MAP_PATH", "content/examples/viewer_map.json")
    monkeypatch.setattr("hexcrawler.cli.play.run_pygame_viewer", lambda **kwargs: 0)

    result = main(["--headless", "--seed", "7", "--runtime-profile", CORE_PLAYABLE])

    assert result == 0
    _, rebuilt_sim = load_game_json(str(save_path))
    patrol_count = sum(1 for entity in rebuilt_sim.state.entities.values() if entity.template_id == "campaign_danger_patrol")
    assert patrol_count >= 1


def test_play_launcher_startup_truth_log_includes_scene_and_paths(tmp_path: Path, monkeypatch, capsys) -> None:
    save_path = tmp_path / "canonical.json"
    monkeypatch.setattr("hexcrawler.cli.play.run_pygame_viewer", lambda **kwargs: 0)

    result = main(
        [
            "--headless",
            "--runtime-profile",
            CORE_PLAYABLE,
            "--load-save",
            str(save_path),
            "--map-path",
            "content/examples/viewer_map.json",
        ]
    )

    assert result == 0
    output = capsys.readouterr().out
    assert "runtime_profile=core_playable" in output
    assert f"map_path=content/examples/viewer_map.json" in output
    assert f"save_path={save_path}" in output
    assert "major_sites=home_greybridge:town,demo_dungeon_entrance:dungeon_entrance" in output
    assert "home_town_count=1" in output
    assert "dungeon_entrance_count=1" in output
