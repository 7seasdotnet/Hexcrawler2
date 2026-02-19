from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from hexcrawler.content.io import load_world_json, save_game_json
from hexcrawler.sim.core import Simulation
from hexcrawler.sim.hash import world_hash


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hexcrawler-new-save-from-map",
        description=(
            "Convert a world-only map template JSON into a canonical game save JSON "
            "(world_state + simulation_state + input_log + save_hash)."
        ),
    )
    parser.add_argument("map_path", help="Path to world-only map template JSON")
    parser.add_argument("save_path", help="Output path for canonical game save JSON")
    parser.add_argument("--seed", type=int, default=0, help="Simulation seed for the new canonical save (default: 0)")
    parser.add_argument("--force", action="store_true", help="Overwrite output path if it already exists")
    parser.add_argument(
        "--print-summary",
        action="store_true",
        help="Print concise world topology/entity/tick/day summary",
    )
    return parser


def _input_is_canonical_save(path: Path) -> bool:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return isinstance(payload, dict) and "world_state" in payload and "save_hash" in payload


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    map_path = Path(args.map_path)
    save_path = Path(args.save_path)

    try:
        if not map_path.exists():
            raise ValueError(f"input map_path does not exist: {map_path}")

        if _input_is_canonical_save(map_path):
            raise ValueError(
                "input is already canonical save; use replay_tool or load_game_json instead"
            )

        if save_path.exists() and not args.force:
            raise ValueError(f"output exists: {save_path} (use --force to overwrite)")

        world = load_world_json(map_path)
        simulation = Simulation(world=world, seed=args.seed)
        save_game_json(save_path, world, simulation)

        save_payload = json.loads(save_path.read_text(encoding="utf-8"))
        if args.print_summary:
            print(
                "summary "
                f"topology_type={world.topology_type} "
                f"topology_params={world.topology_params} "
                f"hex_count={len(world.hexes)} "
                f"entity_count={len(simulation.state.entities)} "
                f"tick={simulation.state.tick} "
                f"day={simulation.get_day_index()}"
            )

        print(
            "ok "
            f"save_path={save_path} "
            f"seed={simulation.seed} "
            f"world_hash={world_hash(world)} "
            f"save_hash={save_payload['save_hash']}"
        )
    except Exception as exc:
        print(f"error: {exc}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
