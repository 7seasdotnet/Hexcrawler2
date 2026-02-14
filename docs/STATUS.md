# Hexcrawler2 — Current State

## Phase
- **Current phase:** Phase 1 (deterministic sim + minimal viewer + replay forensics tooling)
- **Next action:** Add CI wiring that runs replay-tool determinism checks against canonical save fixtures to speed up regression triage.

## What Exists (folders / entry points)
- `src/hexcrawler/sim/`
  - Deterministic fixed-tick simulation core, movement math, world model, RNG stream derivation, hashing.
  - Deterministic topology world-generation API (`WorldState.create_with_topology`) for `hex_disk` and `hex_rectangle`.
- `src/hexcrawler/content/`
  - JSON schema validation + deterministic load/save helpers for both legacy world-only and canonical game-save payloads.
- `src/hexcrawler/cli/viewer.py`
  - Legacy ASCII CLI viewer/controller (continues using `load_world_json`).
- `src/hexcrawler/cli/pygame_viewer.py`
  - Graphical Phase 1 viewer with vector WASD input, right-click move command, and viewer-only render interpolation between committed simulation ticks.
- `src/hexcrawler/cli/replay_tool.py`
  - Headless replay forensics CLI: loads canonical game save, prints concise save/sim header, reports start/end simulation hashes, supports optional per-tick hashes and input-log summaries, and can dump a post-replay canonical save.
- `src/hexcrawler/__main__.py`
  - Package entrypoint routing to pygame viewer.
- `run_game.py`
  - Simple launch script that injects `src/` into `sys.path` and runs the pygame viewer.

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
- ✅ Mandatory tests implemented and passing, including save integrity/tamper checks and replay determinism checks.

## Out of Scope Kept
- No pathfinding, terrain costs, factions, combat, rumors, wounds, or armor systems in this phase.
- No networking in this phase.

## Current Verification Commands
- `python -m pip install -r requirements.txt`
- `python run_game.py`
- `PYTHONPATH=src pytest -q`
- `PYTHONPATH=src pytest -q tests/test_replay_tool.py`
- `PYTHONPATH=src python -m hexcrawler.cli.replay_tool <save_path> --ticks 200`

## What Changed in This Commit
- Added `hexcrawler.cli.replay_tool` CLI for deterministic replay forensics from the current saved simulation state (forward-only replay semantics).
- Added pytest coverage for replay CLI success path, hash markers, and optional final-save dump.
- Updated project status docs with new replay entrypoint and verification command.
