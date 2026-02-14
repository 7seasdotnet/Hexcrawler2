# Hexcrawler2 — Current State

## Phase
- **Current phase:** Phase 2B (rule module interface / plugin substrate)
- **Next action:** Build encounter scheduler substrate on top of rule modules and event queue contracts (not implemented yet).

## What Exists (folders / entry points)
- `src/hexcrawler/sim/`
  - Deterministic fixed-tick simulation core, movement math, world model, RNG stream derivation, hashing.
  - Deterministic command log + deterministic event queue substrate (`SimEvent`, schedule/cancel APIs, same-tick insertion ordering, execution trace API).
  - Rule-module substrate (`RuleModule`, deterministic registration-order lifecycle hooks, named RNG stream access via `Simulation.rng_stream`).
  - Deterministic topology world-generation API (`WorldState.create_with_topology`) for `hex_disk` and `hex_rectangle`.
- `src/hexcrawler/content/`
  - JSON schema validation + deterministic load/save helpers for legacy world-only payloads and canonical game-save payloads.
- `src/hexcrawler/cli/viewer.py`
  - Legacy ASCII CLI viewer/controller (supports world-only templates via `load_world_json`).
- `src/hexcrawler/cli/pygame_viewer.py`
  - Graphical Phase 1 viewer with vector WASD input, right-click move command, and viewer-only render interpolation between committed simulation ticks.
- `src/hexcrawler/cli/replay_tool.py`
  - Headless replay forensics CLI operating on canonical game saves.
- `src/hexcrawler/cli/new_save_from_map.py`
  - CLI bridge that converts a world-only map template into canonical runtime save JSON with seed-controlled simulation initialization.
- `src/hexcrawler/__main__.py`
  - Package entrypoint routing to pygame viewer.
- `run_game.py`
  - Simple launch script that injects `src/` into `sys.path` and runs the pygame viewer.

## Content/Runtime Save Workflow
- Recommended content templates directory: `content/`
- Recommended runtime save directory: `saves/`
- Build runtime save from template:
  - `PYTHONPATH=src python -m hexcrawler.cli.new_save_from_map content/examples/basic_map.json saves/sample_save.json --seed 123 --force --print-summary`
- Run pygame viewer directly from a map template (legacy-compatible flow):
  - `python run_game.py`
- Run replay tool from canonical save:
  - `PYTHONPATH=src python -m hexcrawler.cli.replay_tool saves/sample_save.json --ticks 200`

## Progress
- ✅ Axial-coordinate hex world model implemented and keyed by `HexCoord`.
- ✅ Per-hex editable records implemented (`terrain_type`, `site_type`, `metadata`).
- ✅ Canonical game-save serialization (v1) implemented with atomic canonical JSON and integrity hashing.
- ✅ Deterministic master-seed RNG stream separation implemented (`rng_worldgen`, `rng_sim`) via SHA-256 child seed derivation.
- ✅ Deterministic topology parameters now persisted in `WorldState` (`topology_type`, `topology_params`).
- ✅ Deterministic world generation API implemented:
  - `generate_hex_disk(radius, rng_worldgen)`
  - `generate_hex_rectangle(width, height, rng_worldgen)`
  - `WorldState.create_with_topology(master_seed, topology_type, topology_params)`
- ✅ Replay forensics CLI added for deterministic debugging without modifying simulation semantics.
- ✅ Map-template → canonical-save CLI added to keep content/runtime boundary explicit.
- ✅ Phase 2A complete: deterministic serialized event queue substrate implemented and included in simulation hash.
- ✅ Phase 2B complete: deterministic rule-module interface integrated into simulation lifecycle with registration-order execution.

## New Public APIs (Phase 2B)
- `hexcrawler.sim.rules.RuleModule`
  - `on_simulation_start(sim)`
  - `on_tick_start(sim, tick)`
  - `on_tick_end(sim, tick)`
  - `on_event_executed(sim, event)`
- `Simulation.register_rule_module(module)`
- `Simulation.rng_stream(name)`

## Out of Scope Kept
- No pathfinding, terrain costs, factions, combat, rumors, wounds, or armor systems in this phase.
- No networking in this phase.

## Current Verification Commands
- `python -m pip install -r requirements.txt`
- `python run_game.py`
- `PYTHONPATH=src pytest -q`
- `PYTHONPATH=src pytest -q tests/test_rule_modules.py`
- `PYTHONPATH=src pytest -q tests/test_event_queue.py`
- `PYTHONPATH=src python -m hexcrawler.cli.new_save_from_map --help`
- `PYTHONPATH=src python -m hexcrawler.cli.new_save_from_map content/examples/basic_map.json saves/sample_save.json --seed 123 --force --print-summary`
- `PYTHONPATH=src python -m hexcrawler.cli.replay_tool saves/sample_save.json --ticks 200`

## What Changed in This Commit
- Added deterministic `RuleModule` substrate and lifecycle hook integration in `Simulation` (`on_tick_start`, `on_event_executed`, `on_tick_end`) with strict registration-order execution.
- Added `Simulation.rng_stream(name)` for named deterministic RNG streams derived from the master seed and cached per simulation instance.
- Added rule-module pytest coverage for lifecycle ordering, event hook ordering, RNG stream determinism, and duplicate-name rejection.
