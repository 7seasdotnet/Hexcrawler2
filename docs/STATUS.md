# Hexcrawler2 — Current State

## Phase
- **Current phase:** Phase 1 (deterministic sim + minimal viewer)
- **Next action:** Keep replay payload migration-ready (schema v2 planning) while preserving deterministic command execution ordering.

## What Exists (folders / entry points)
- `src/hexcrawler/sim/`
  - Deterministic fixed-tick simulation core, movement math, world model, RNG stream derivation, hashing.
  - Deterministic topology world-generation API (`WorldState.create_with_topology`) for `hex_disk` and `hex_rectangle`.
- `src/hexcrawler/content/`
  - JSON schema validation + deterministic load/save helpers for world data.
- `src/hexcrawler/cli/viewer.py`
  - Legacy ASCII CLI viewer/controller.
- `src/hexcrawler/cli/pygame_viewer.py`
  - Graphical Phase 1 viewer with vector WASD input and right-click move command.
- `src/hexcrawler/__main__.py`
  - Package entrypoint routing to pygame viewer.
- `run_game.py`
  - Simple launch script that injects `src/` into `sys.path` and runs the pygame viewer.

## Progress
- ✅ Axial-coordinate hex world model implemented and keyed by `HexCoord`.
- ✅ Per-hex editable records implemented (`terrain_type`, `site_type`, `metadata`).
- ✅ Serialization contract (v1) implemented and validated with hash verification + canonical JSON + atomic save.
- ✅ Deterministic master-seed RNG stream separation implemented (`rng_worldgen`, `rng_sim`) via SHA-256 child seed derivation.
- ✅ Deterministic topology parameters now persisted in `WorldState` (`topology_type`, `topology_params`).
- ✅ Deterministic world generation API implemented:
  - `generate_hex_disk(radius, rng_worldgen)`
  - `generate_hex_rectangle(width, height, rng_worldgen)`
  - `WorldState.create_with_topology(master_seed, topology_type, topology_params)`
- ✅ Mandatory tests implemented and passing, including world-generation determinism checks.

## Out of Scope Kept
- No pathfinding, terrain costs, factions, combat, rumors, wounds, or armor systems in this phase.
- No UI replay tooling yet (engine replay API and persistence only).

## Current Verification Commands
- `python -m pip install -r requirements.txt`
- `python run_game.py`
- `PYTHONPATH=src pytest -q`
- `PYTHONPATH=src pytest -q tests/test_world_generation.py`
- `PYTHONPATH=src pytest -q tests/test_replay_log.py`

## What Changed in This Commit
- Added a deterministic simulation command log schema and apply-at-tick execution path (`append_command`, stable same-tick insertion order, and `run_replay(...)`).
- Added simulation save/load payload support with canonical JSON, schema versioning, and embedded `input_log` persistence.
- Added replay-focused tests for determinism parity, live-vs-replay equivalence, and input-log save/load round-trip fidelity.
