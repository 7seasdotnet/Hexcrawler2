from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from hexcrawler.cli.pygame_viewer import run_pygame_viewer
from hexcrawler.content.io import load_world_json, save_game_json
from hexcrawler.sim.core import Simulation

DEFAULT_MAP_PATH = "content/examples/viewer_map.json"
DEFAULT_SAVE_PATH = "saves/canonical_viewer_save.json"
DEFAULT_SEED = 7


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python play.py", description="Canonical Hexcrawler launcher.")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help="Seed used when creating the canonical save.")
    parser.add_argument("--load-save", default=DEFAULT_SAVE_PATH, help="Path to canonical save JSON to load at startup.")
    parser.add_argument("--map-path", default=DEFAULT_MAP_PATH, help="Map path used if canonical save must be created.")
    parser.add_argument("--headless", action="store_true", help="Run startup path in headless mode.")
    return parser


def _ensure_save_exists(*, map_path: str, save_path: str, seed: int) -> None:
    save_file = Path(save_path)
    if save_file.exists():
        return
    save_file.parent.mkdir(parents=True, exist_ok=True)
    world = load_world_json(map_path)
    simulation = Simulation(world=world, seed=seed)
    save_game_json(save_file, world, simulation)


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    _ensure_save_exists(map_path=args.map_path, save_path=args.load_save, seed=args.seed)
    return run_pygame_viewer(
        map_path=args.map_path,
        with_encounters=True,
        headless=args.headless,
        load_save=args.load_save,
        save_path=args.load_save,
    )


if __name__ == "__main__":
    raise SystemExit(main())
