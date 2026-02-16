from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Sequence

from hexcrawler.content.io import load_game_json, save_game_json
from hexcrawler.sim.core import Simulation
from hexcrawler.sim.encounters import ENCOUNTER_ACTION_OUTCOME_EVENT_TYPE
from hexcrawler.sim.hash import simulation_hash

ARTIFACT_PRINT_SIGNAL_LIMIT = 10
ARTIFACT_PRINT_TRACK_LIMIT = 10
ARTIFACT_PRINT_OUTCOME_LIMIT = 20


def _non_negative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("ticks must be >= 0")
    return parsed


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hexcrawler-replay",
        description=(
            "Deterministic replay forensic tool. Replay starts from the CURRENT saved simulation "
            "state and advances forward N ticks using commands from the save input_log."
        ),
    )
    parser.add_argument("save_path", help="Path to canonical game save JSON")
    parser.add_argument("--ticks", type=_non_negative_int, default=1, help="Ticks to advance from current saved state")
    parser.add_argument(
        "--per-tick",
        action="store_true",
        help="Print simulation hash after each replayed tick",
    )
    parser.add_argument(
        "--print-input-summary",
        action="store_true",
        help="Print command counts grouped by command_type",
    )
    parser.add_argument(
        "--print-artifacts",
        action="store_true",
        help="Print concise recent signal/track/action-outcome artifacts after replay",
    )
    parser.add_argument(
        "--dump-final-save",
        help="Optional path to write canonical save payload after replay",
    )
    return parser


def _clone_simulation(simulation: Simulation) -> Simulation:
    return Simulation.from_simulation_payload(simulation.simulation_payload())


def _print_header(save_payload: dict[str, object], simulation: Simulation) -> None:
    print(
        "header "
        f"schema_version={save_payload.get('schema_version')} "
        f"tick={simulation.state.tick} "
        f"day={simulation.state.day} "
        f"entity_count={len(simulation.state.entities)} "
        f"input_log_length={len(simulation.input_log)}"
    )
    print("integrity=OK")


def _print_input_summary(simulation: Simulation) -> None:
    counts = Counter(command.command_type for command in simulation.input_log)
    if not counts:
        print("input_summary none")
        return
    summary = " ".join(f"{command_type}={counts[command_type]}" for command_type in sorted(counts))
    print(f"input_summary {summary}")


def _format_location(location: object) -> str:
    if not isinstance(location, dict):
        return "?"
    topology = str(location.get("topology_type", "?"))
    coord = location.get("coord")
    if isinstance(coord, dict):
        return f"{topology}:{coord.get('q', '?')},{coord.get('r', '?')}"
    return f"{topology}:?"


def _print_artifacts(simulation: Simulation) -> None:
    print(f"artifacts.signals.limit={ARTIFACT_PRINT_SIGNAL_LIMIT}")
    recent_signals = list(reversed(simulation.state.world.signals[-ARTIFACT_PRINT_SIGNAL_LIMIT:]))
    if not recent_signals:
        print("artifacts.signal none")
    for record in recent_signals:
        created_tick = record.get("created_tick", "?")
        template_id = record.get("template_id", "?")
        expires_tick = record.get("expires_tick")
        expires_text = "-" if expires_tick is None else str(expires_tick)
        print(
            "artifacts.signal "
            f"tick={created_tick} "
            f"location={_format_location(record.get('location'))} "
            f"template_id={template_id} "
            f"expires_tick={expires_text}"
        )

    print(f"artifacts.tracks.limit={ARTIFACT_PRINT_TRACK_LIMIT}")
    recent_tracks = list(reversed(simulation.state.world.tracks[-ARTIFACT_PRINT_TRACK_LIMIT:]))
    if not recent_tracks:
        print("artifacts.track none")
    for record in recent_tracks:
        created_tick = record.get("created_tick", "?")
        template_id = record.get("template_id", "?")
        expires_tick = record.get("expires_tick")
        expires_text = "-" if expires_tick is None else str(expires_tick)
        print(
            "artifacts.track "
            f"tick={created_tick} "
            f"location={_format_location(record.get('location'))} "
            f"template_id={template_id} "
            f"expires_tick={expires_text}"
        )

    print(f"artifacts.outcomes.limit={ARTIFACT_PRINT_OUTCOME_LIMIT}")
    outcomes = [
        entry
        for entry in simulation.get_event_trace()
        if entry.get("event_type") == ENCOUNTER_ACTION_OUTCOME_EVENT_TYPE
    ]
    recent_outcomes = list(reversed(outcomes[-ARTIFACT_PRINT_OUTCOME_LIMIT:]))
    if not recent_outcomes:
        print("artifacts.outcome none")
    for entry in recent_outcomes:
        params = entry.get("params")
        params = params if isinstance(params, dict) else {}
        tick = entry.get("tick", "?")
        action_uid = params.get("action_uid", "?")
        action_type = params.get("action_type", "?")
        outcome = params.get("outcome", "?")
        template_id = params.get("template_id")
        template_text = "-" if template_id in (None, "") else str(template_id)
        print(
            "artifacts.outcome "
            f"tick={tick} "
            f"action_uid={action_uid} "
            f"action_type={action_type} "
            f"outcome={outcome} "
            f"template_id={template_text}"
        )


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        save_payload = json.loads(Path(args.save_path).read_text(encoding="utf-8"))
        _, loaded_simulation = load_game_json(args.save_path)
        simulation = _clone_simulation(loaded_simulation)

        _print_header(save_payload, simulation)
        if args.print_input_summary:
            _print_input_summary(simulation)

        start_hash = simulation_hash(simulation)
        print(f"start_hash={start_hash}")

        if args.per_tick and args.ticks > 0:
            for _ in range(args.ticks):
                simulation.advance_ticks(1)
                print(f"tick={simulation.state.tick} hash={simulation_hash(simulation)}")
        else:
            simulation.advance_ticks(args.ticks)

        end_hash = simulation_hash(simulation)
        print(f"end_hash={end_hash}")

        if args.print_artifacts:
            _print_artifacts(simulation)

        if args.dump_final_save:
            save_game_json(args.dump_final_save, simulation.state.world, simulation)
            print(f"dumped_final_save={args.dump_final_save}")

    except Exception as exc:
        print(f"error: {exc}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
