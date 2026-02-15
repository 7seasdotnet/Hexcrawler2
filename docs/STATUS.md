# Hexcrawler2 — Current State

## Phase
- **Current phase:** Phase 4V UI visibility pass — read-only encounter inspector panel layered over the Phase 4B encounter skeleton, now explicitly gated behind a viewer CLI flag.
- **Next action:** Plan Phase 4C boundaries for content-free downstream wiring while preserving strict no-content semantics (no encounter tables or resolution yet), with viewer runtime kept neutral unless encounter inspection is explicitly enabled.

## What Exists (folders / entry points)
- `src/hexcrawler/sim/`
  - Deterministic fixed-tick simulation core, movement math, world model, RNG stream derivation, hashing.
  - Deterministic command log + deterministic event queue substrate (`SimEvent`, schedule/cancel APIs, same-tick insertion ordering, execution trace API).
  - Deterministic bounded execution trace substrate (`SimulationState.event_trace`) for executed events only, serialized in canonical saves and included in `simulation_hash`.
  - Rule-module substrate (`RuleModule`, deterministic registration-order lifecycle hooks, named RNG stream access via `Simulation.rng_stream`).
  - Generic periodic scheduling substrate (`PeriodicScheduler`) backed by serialized event queue events (`periodic_tick`) with callback reattachment after load.
  - Generic check emission substrate (`CheckRunner`) that registers periodic tasks and emits serialized `check` events for deterministic forensics/debugging.
  - Encounter-check eligibility gate (`EncounterCheckModule`) that emits structured `encounter_check` events on a fixed periodic schedule, evaluates deterministic eligibility, and emits `encounter_roll` follow-on events only when eligible.
  - Serialized per-module `rules_state` store on `SimulationState` with JSON-validating `Simulation.get_rules_state(...)`/`Simulation.set_rules_state(...)` APIs.
  - Deterministic topology world-generation API (`WorldState.create_with_topology`) for `hex_disk` and `hex_rectangle`.
- `src/hexcrawler/content/`
  - JSON schema validation + deterministic load/save helpers for legacy world-only payloads and canonical game-save payloads.
- `src/hexcrawler/cli/viewer.py`
  - Legacy ASCII CLI viewer/controller (supports world-only templates via `load_world_json`).
- `src/hexcrawler/cli/pygame_viewer.py`
  - Graphical viewer with vector WASD input, right-click move command, and viewer-only render interpolation between committed simulation ticks.
  - Includes CLI parsing for viewer boundary configuration (`--map-path`, `--with-encounters`).
  - Includes a read-only "Encounter Debug" panel that inspects `encounter_check` rules-state fields, shows cooldown summary values, and lists recent `encounter_check`/`encounter_roll` entries from the executed event trace only when the encounter module is enabled.
- `src/hexcrawler/cli/replay_tool.py`
  - Headless replay forensics CLI operating on canonical game saves.
- `src/hexcrawler/cli/new_save_from_map.py`
  - CLI bridge that converts a world-only map template into canonical runtime save JSON with seed-controlled simulation initialization.
- `src/hexcrawler/__main__.py`
  - Package entrypoint routing to pygame viewer.
- `run_game.py`
  - Simple launch script that injects `src/` into `sys.path` and runs the pygame viewer.
- `docs/PROMPTLOG.md`
  - Canonical reverse-chronological prompt history linking verbatim prompts, Codex summaries, commit references, and verification notes.

## Content/Runtime Save Workflow
- Recommended content templates directory: `content/`
- Recommended runtime save directory: `saves/`
- Build runtime save from template:
  - `PYTHONPATH=src python -m hexcrawler.cli.new_save_from_map content/examples/basic_map.json saves/sample_save.json --seed 123 --force --print-summary`
- Run pygame viewer directly from a map template (legacy-compatible flow):
  - `python run_game.py`
  - `python run_game.py --with-encounters`
  - Encounter panel location: upper-right "Encounter Debug" section in the running window.
  - Encounter debug data appears only when run with `--with-encounters`; otherwise the panel shows an explicit enablement hint.
- Run replay tool from canonical save:
  - `PYTHONPATH=src python -m hexcrawler.cli.replay_tool saves/sample_save.json --ticks 200`
- `sed -n '1,220p' docs/PROMPTLOG.md`

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
- ✅ Phase 2C complete: deterministic generic periodic scheduler substrate implemented via serialized `periodic_tick` events.
- ✅ Phase 2C hardening complete: periodic rehydration now prevents duplicate chains and rejects interval conflicts deterministically.
- ✅ Phase 3A substrate complete: stateless `CheckRunner` now emits serialized `check` events via `PeriodicScheduler` callbacks.
- ✅ Phase 3B substrate complete: serialized hash-covered `rules_state` store added to canonical simulation save/load and simulation hashing.
- ✅ Phase 3C substrate complete: serialized hash-covered bounded `event_trace` execution history added with deterministic FIFO eviction and deep-copy read API.
- ✅ Phase 4A complete: `EncounterCheckModule` emits deterministic structured `encounter_check` events via `PeriodicScheduler`, uses only serialized `rules_state` for pacing state, and remains save/load + replay hash stable.
- ✅ Phase 4B complete: encounter checks now pass through a deterministic eligibility gate with cooldown accounting and emit `encounter_roll` events (content-free, no resolution).
- ✅ Phase 4V complete: pygame UI now has a read-only encounter visibility panel for `encounter_check` rules-state and recent encounter execution trace entries.

## New Public APIs (Phase 4B)
- `Simulation.get_rule_module(module_name)`
- `Simulation.get_event_trace()` (deep-copy, read-only inspection surface for executed-event trace)
- `hexcrawler.sim.core.MAX_EVENT_TRACE` (hard cap: 256 entries)
- `Simulation.get_rules_state(module_name)` (copy semantics; mutate via `set_rules_state`)
- `Simulation.set_rules_state(module_name, state)`
- `hexcrawler.sim.checks.CheckRunner`
  - `register_check(check_name, interval_ticks, start_tick=0)`
  - `set_check_callback(check_name, callback)`
- `hexcrawler.sim.checks.CHECK_EVENT_TYPE`
- `hexcrawler.sim.encounters.EncounterCheckModule`
- `hexcrawler.sim.encounters.ENCOUNTER_CHECK_EVENT_TYPE`
- `hexcrawler.sim.encounters.ENCOUNTER_CHECK_INTERVAL`
- `hexcrawler.sim.encounters.ENCOUNTER_ROLL_EVENT_TYPE`
- `hexcrawler.sim.encounters.ENCOUNTER_CHANCE_PERCENT`
- `hexcrawler.sim.encounters.ENCOUNTER_COOLDOWN_TICKS`

## Out of Scope Kept
- No pathfinding, terrain costs, factions, combat, rumors, wounds, or armor systems in this phase.
- No networking in this phase.

## Current Verification Commands
- `python -m pip install -r requirements.txt`
- `python run_game.py`
- `python run_game.py --with-encounters`
- `PYTHONPATH=src pytest -q`
- `PYTHONPATH=src pytest -q tests/test_check_runner.py`
- `PYTHONPATH=src pytest -q tests/test_rules_state.py`
- `PYTHONPATH=src pytest -q tests/test_periodic_scheduler.py`
- `PYTHONPATH=src pytest -q tests/test_rule_modules.py`
- `PYTHONPATH=src pytest -q tests/test_event_queue.py`
- `PYTHONPATH=src pytest -q tests/test_event_trace.py`
- `PYTHONPATH=src pytest -q tests/test_encounter_check_module.py`
- `PYTHONPATH=src python -m hexcrawler.cli.new_save_from_map --help`
- `PYTHONPATH=src python -m hexcrawler.cli.new_save_from_map content/examples/basic_map.json saves/sample_save.json --seed 123 --force --print-summary`
- `PYTHONPATH=src python -m hexcrawler.cli.replay_tool saves/sample_save.json --ticks 200`
- `sed -n '1,220p' docs/PROMPTLOG.md`

## What Changed in This Commit
- Added explicit pygame viewer CLI wiring for `--with-encounters` (default off) and `--map-path`, and routed `run_game.py` / package entrypoint through the viewer CLI parser.
- Removed unconditional encounter module registration from default viewer startup; encounter module now registers only when `--with-encounters` is passed.
- Updated Encounter Debug panel absent-module messaging and status/run instructions to document neutral-default behavior and the explicit enablement command.
