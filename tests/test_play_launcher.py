from pathlib import Path

from hexcrawler.cli.play import DEFAULT_SAVE_PATH, main


def test_play_launcher_creates_default_save_when_missing(tmp_path: Path, monkeypatch) -> None:
    save_path = tmp_path / "canonical.json"

    def fake_run(**kwargs):
        assert kwargs["with_encounters"] is True
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
