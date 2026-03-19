from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from hexcrawler.cli.pygame_viewer import run_pygame_viewer
from hexcrawler.cli.runtime_profiles import DEFAULT_RUNTIME_PROFILE, RUNTIME_PROFILE_CHOICES
from hexcrawler.content.io import load_game_json, load_world_json, save_game_json
from hexcrawler.sim.core import Simulation
from hexcrawler.sim.hash import world_hash

DEFAULT_MAP_PATH = "content/examples/viewer_map.json"
DEFAULT_SAVE_PATH = "saves/canonical_viewer_save.json"
DEFAULT_SEED = 7


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python play.py", description="Canonical Hexcrawler launcher.")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help="Seed used when creating the canonical save.")
    parser.add_argument("--load-save", default=DEFAULT_SAVE_PATH, help="Path to canonical save JSON to load at startup.")
    parser.add_argument("--map-path", default=DEFAULT_MAP_PATH, help="Map path used if canonical save must be created.")
    parser.add_argument("--headless", action="store_true", help="Run startup path in headless mode.")
    parser.add_argument(
        "--runtime-profile",
        choices=RUNTIME_PROFILE_CHOICES,
        default=DEFAULT_RUNTIME_PROFILE,
        help="Runtime module composition profile for viewer startup.",
    )
    return parser


def _ensure_save_exists(*, map_path: str, save_path: str, seed: int, refresh_if_mismatch: bool = False) -> None:
    save_file = Path(save_path)
    if save_file.exists():
        if not refresh_if_mismatch:
            return
        world = load_world_json(map_path)
        try:
            saved_world, _ = load_game_json(str(save_file))
        except Exception:
            saved_world = None
        if saved_world is not None and world_hash(saved_world) == world_hash(world):
            return
    else:
        world = load_world_json(map_path)
    save_file.parent.mkdir(parents=True, exist_ok=True)
    simulation = Simulation(world=world, seed=seed)
    save_game_json(save_file, world, simulation)


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    refresh_if_mismatch = args.load_save == DEFAULT_SAVE_PATH and args.map_path == DEFAULT_MAP_PATH
    _ensure_save_exists(map_path=args.map_path, save_path=args.load_save, seed=args.seed, refresh_if_mismatch=refresh_if_mismatch)
    return run_pygame_viewer(
        map_path=args.map_path,
        runtime_profile=args.runtime_profile,
        headless=args.headless,
        load_save=args.load_save,
        save_path=args.load_save,
    )


if __name__ == "__main__":
    raise SystemExit(main())
