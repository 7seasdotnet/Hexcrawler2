from pathlib import Path

from hexcrawler.content.io import load_game_json, load_world_json, save_game_json
from hexcrawler.sim.core import Simulation
from hexcrawler.cli.play import DEFAULT_MAP_PATH, DEFAULT_SAVE_PATH, main
from hexcrawler.cli.runtime_profiles import DEFAULT_RUNTIME_PROFILE


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
    monkeypatch.setattr("hexcrawler.cli.play._ensure_save_exists", lambda **_: None)

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
    monkeypatch.setattr("hexcrawler.cli.play._ensure_save_exists", lambda **_: None)

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
