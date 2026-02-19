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
from hexcrawler.sim.supplies import SUPPLY_OUTCOME_EVENT_TYPE

ARTIFACT_PRINT_SIGNAL_LIMIT = 10
ARTIFACT_PRINT_TRACK_LIMIT = 10
ARTIFACT_PRINT_SPAWN_LIMIT = 10
ARTIFACT_PRINT_OUTCOME_LIMIT = 20
ARTIFACT_PRINT_ENTITY_LIMIT = 20
ARTIFACT_PRINT_RUMOR_LIMIT = 20
ARTIFACT_PRINT_SUPPLY_OUTCOME_LIMIT = 20


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
        help="Print concise recent signal/track/spawn/action-outcome artifacts after replay",
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
        f"day={simulation.get_day_index()} "
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
        if "q" in coord and "r" in coord:
            return f"{topology}:{coord.get('q', '?')},{coord.get('r', '?')}"
        if "x" in coord and "y" in coord:
            return f"{topology}:{coord.get('x', '?')},{coord.get('y', '?')}"
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

    print(f"artifacts.spawns.limit={ARTIFACT_PRINT_SPAWN_LIMIT}")
    recent_spawns = list(reversed(simulation.state.world.spawn_descriptors[-ARTIFACT_PRINT_SPAWN_LIMIT:]))
    if not recent_spawns:
        print("artifacts.spawn none")
    for record in recent_spawns:
        created_tick = record.get("created_tick", "?")
        template_id = record.get("template_id", "?")
        quantity = record.get("quantity", "?")
        expires_tick = record.get("expires_tick")
        expires_text = "-" if expires_tick is None else str(expires_tick)
        action_uid = record.get("action_uid", "?")
        print(
            "artifacts.spawn "
            f"tick={created_tick} "
            f"location={_format_location(record.get('location'))} "
            f"template_id={template_id} "
            f"quantity={quantity} "
            f"expires_tick={expires_text} "
            f"action_uid={action_uid}"
        )



    print(f"artifacts.rumors.limit={ARTIFACT_PRINT_RUMOR_LIMIT}")
    recent_rumors = list(reversed(simulation.state.world.rumors[-ARTIFACT_PRINT_RUMOR_LIMIT:]))
    if not recent_rumors:
        print("artifacts.rumor none")
    for record in recent_rumors:
        print(
            "artifacts.rumor "
            f"rumor_id={record.get('rumor_id', '?')} "
            f"tick={record.get('created_tick', '?')} "
            f"location={_format_location(record.get('location'))} "
            f"template_id={record.get('template_id', '?')} "
            f"source_action_uid={record.get('source_action_uid', '?')} "
            f"hop={record.get('hop', '?')} "
            f"confidence={record.get('confidence', '?')} "
            f"expires_tick={record.get('expires_tick', '?')}"
        )


    print(f"artifacts.supply_outcomes.limit={ARTIFACT_PRINT_SUPPLY_OUTCOME_LIMIT}")
    supply_outcomes = [
        entry
        for entry in simulation.get_event_trace()
        if entry.get("event_type") == SUPPLY_OUTCOME_EVENT_TYPE
    ]
    recent_supply_outcomes = list(reversed(supply_outcomes[-ARTIFACT_PRINT_SUPPLY_OUTCOME_LIMIT:]))
    if not recent_supply_outcomes:
        print("artifacts.supply_outcome none")
    for entry in recent_supply_outcomes:
        params = entry.get("params")
        params = params if isinstance(params, dict) else {}
        print(
            "artifacts.supply_outcome "
            f"tick={entry.get('tick', '?')} "
            f"entity_id={params.get('entity_id', '?')} "
            f"item_id={params.get('item_id', '?')} "
            f"quantity={params.get('quantity', '?')} "
            f"remaining={params.get('remaining_quantity', '-')} "
            f"outcome={params.get('outcome', '?')} "
            f"action_uid={params.get('action_uid', '?')}"
        )

    print(f"artifacts.entities.limit={ARTIFACT_PRINT_ENTITY_LIMIT}")
    spawned_entities = [
        entity
        for entity in sorted(simulation.state.entities.values(), key=lambda current: current.entity_id)
        if entity.entity_id.startswith("spawn:")
    ]
    recent_entities = list(reversed(spawned_entities[-ARTIFACT_PRINT_ENTITY_LIMIT:]))
    if not recent_entities:
        print("artifacts.entity none")
    for entity in recent_entities:
        print(
            "artifacts.entity "
            f"entity_id={entity.entity_id} "
            f"template_id={entity.template_id if entity.template_id else '-'} "
            f"location=overworld_hex:{entity.hex_coord.q},{entity.hex_coord.r} "
            f"source_action_uid={entity.source_action_uid if entity.source_action_uid else '-'}"
        )

    selection_entity_id = simulation.selected_entity_id(owner_entity_id="scout")
    print(
        "artifacts.selection "
        f"owner_entity_id=scout "
        f"selected_entity_id={selection_entity_id if selection_entity_id is not None else 'none'}"
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
