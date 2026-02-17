# Hexcrawler2 — Current State

## Phase
- **Current phase:** Phase 5H2 — Supplies + Consumption ticks (deterministic accounting; no towns/prices).
- **Next action:** Phase 5I — settlement/site substrates (non-economic) for stockpile locations and logistics anchors, or Phase 5J dungeon exploration actions.
- **Phase status:** ✅ Phase 5H2 complete (data-driven supply profiles + deterministic periodic consumption + forensic outcomes landed).

## What Exists (folders / entry points)
- `src/hexcrawler/sim/`
  - Deterministic fixed-tick simulation core, movement math, world model, RNG stream derivation, hashing.
  - Deterministic command log + deterministic event queue substrate (`SimEvent`, schedule/cancel APIs, same-tick insertion ordering, execution trace API).
  - Same-tick event execution now drains-until-empty for tick `T` (including events scheduled during `T`) with deterministic FIFO behavior and a hard deterministic guard for runaway self-rescheduling.
  - Deterministic bounded execution trace substrate (`SimulationState.event_trace`) for executed events only, serialized in canonical saves and included in `simulation_hash`.
  - Rule-module substrate (`RuleModule`, deterministic registration-order lifecycle hooks, named RNG stream access via `Simulation.rng_stream`).
  - Generic periodic scheduling substrate (`PeriodicScheduler`) backed by serialized event queue events (`periodic_tick`) with callback reattachment after load.
  - Generic check emission substrate (`CheckRunner`) that registers periodic tasks and emits serialized `check` events for deterministic forensics/debugging.
  - Encounter-check eligibility gate (`EncounterCheckModule`) that emits structured `encounter_check` events on a fixed periodic schedule with explicit trigger semantics, evaluates deterministic eligibility, emits `encounter_roll` follow-on events only when eligible, and emits content-free `encounter_result_stub` events from each roll, and emits deterministic `encounter_resolve_request` follow-on seam events (+1 tick) for downstream resolution consumers.
  - Encounter selection seam (`EncounterSelectionModule`) that consumes a validated default encounter table and deterministically emits descriptive `encounter_selection_stub` events from `encounter_resolve_request` using a dedicated RNG stream (`encounter_selection`) only.
  - Encounter action grammar seam (`EncounterActionModule`) that consumes `encounter_selection_stub` and deterministically emits descriptive `encounter_action_stub` events with extensible `actions` intents (fallback `signal_intent` when entry payload has no explicit actions).
  - Encounter action execution seam (`EncounterActionExecutionModule`) that consumes `encounter_action_stub`, schedules `encounter_action_execute`, executes the provisional supported action set (`signal_intent`, `track_intent`, `spawn_intent`), records deterministic forensic outcomes, appends data-only `world.spawn_descriptors` records for spawn intents, and enforces idempotence via serialized executed-action UID ledger in `rules_state`.
  - Spawn materialization seam (`SpawnMaterializationModule`) that deterministically materializes inert entities from `world.spawn_descriptors` using stable IDs (`spawn:<action_uid>:<i>`), preserves idempotence with serialized materialization ledger state, and never mutates combat/AI systems.
  - Rumor pipeline seam (`RumorPipelineModule`) that deterministically creates `world.rumors` from executed `encounter_action_outcome` events, persists emitted-rumor ledger state in `rules_state["rumor_pipeline"]`, and runs serialized periodic propagation/expiration accounting (hop cap 4).
  - Serialized per-module `rules_state` store on `SimulationState` with JSON-validating `Simulation.get_rules_state(...)`/`Simulation.set_rules_state(...)` APIs.
  - Deterministic topology world-generation API (`WorldState.create_with_topology`) for `hex_disk` and `hex_rectangle`.
  - World spaces substrate (`WorldState.spaces`) with deterministic canonical serialization and back-compat migration from legacy top-level overworld payloads into `spaces["overworld"]`.
  - Opaque `LocationRef` substrate (`hexcrawler.sim.location`) now includes `space_id` (defaults to `"overworld"` for legacy payloads) while preserving existing `topology_type` + `coord` contracts.
  - Deterministic `transition_space` command seam that records `space_transition` forensic trace entries and rejects unknown `space_id` targets deterministically.
  - Deterministic selection command substrate: `set_selected_entity` / `clear_selected_entity`, with serialized/hash-covered selection storage on the command owner entity when present (fallback on simulation state), save/load round-trip support, and replay stability.
  - Stackable inventory substrate: `world.containers` persistence, per-entity `inventory_container_id` linkage, deterministic container serialization/hash coverage, and load-time referential validation for entity inventory containers.
  - Deterministic `inventory_intent` command seam (`transfer`/`drop`/`pickup`/`consume`/`spawn`) with single authoritative apply path, no-negative enforcement, deterministic `action_uid` (`tick:command_index`), and serialized idempotence ledger in `rules_state["inventory_ledger"].applied_action_uids`.
  - Deterministic forensic `inventory_outcome` event-trace entries for every intent (`applied`, `already_applied`, `insufficient_quantity`, `unknown_item`, `unknown_container`, `invalid_quantity`, `unsupported_reason`).
  - Deterministic supply profile content loader (`content/supplies/supply_profiles.json`) with strict schema validation + deterministic normalization (`hexcrawler.content.supplies`).
  - Deterministic `SupplyConsumptionModule` periodic accounting seam that consumes configured supplies via the authoritative inventory apply path, with per-attempt deterministic `action_uid` and idempotence ledger in `rules_state["supply_consumption"]`.
  - Deterministic forensic `supply_outcome` event-trace entries (`consumed`, `insufficient_supply`, `already_applied`, `unknown_item`, `no_inventory_container`) and warning stubs in `rules_state["supply_consumption"].warnings`.
  - Default player (`scout`) supply profile assignment (`player_default`) on new entities/saves.
- `src/hexcrawler/content/`
  - JSON schema validation + deterministic load/save helpers for legacy world-only payloads and canonical game-save payloads.
  - Encounter table content loader/validator (`content.encounters`) with strict schema checks, deterministic normalization, and default example table wiring.
  - Item registry loader/validator (`content.items`) with strict schema validation, stackable-only enforcement for this phase, deterministic item ordering, and default path constant `DEFAULT_ITEMS_PATH = "content/items/items.json"`.
- `src/hexcrawler/cli/viewer.py`
  - Legacy ASCII CLI viewer/controller (supports world-only templates via `load_world_json`) with controller actions routed through `SimCommand` append semantics (no direct simulation mutation).
- `src/hexcrawler/cli/pygame_viewer.py`
  - Graphical viewer with vector WASD input, deterministic right-click context menus (entity/hex/background), and viewer-only render interpolation between committed simulation ticks.
  - Viewer controller input paths append `SimCommand`s at current simulation tick instead of mutating movement state directly.
  - Includes CLI parsing for viewer runtime/session controls (`--map-path`, `--with-encounters`, `--headless`, `--load-save`, `--save-path`).
  - Startup diagnostics print Python/pygame/platform details and key SDL env vars before SDL init; startup failures from `pygame.init()` or `pygame.display.set_mode(...)` emit actionable stderr hints and non-zero exits.
  - Uses split layout regions (left world viewport + right fixed-width Encounter Debug panel) so world rendering and the player marker remain visible in the viewport.
  - Encounter Debug is read-only and supports section scrolling/pagination for signals/tracks/spawns/spawned-entities/rumors/outcomes with stable forensic identifiers and newest-first ordering.
  - Encounter panel rows now wrap by pixel width so long forensic lines stay inside panel bounds.
  - World viewport renders deterministic decluttered in-hex marker slots for signals/tracks/spawn descriptors/spawned entities while keeping UI rendering strictly read-only.
  - Supports deterministic canonical session persistence in-viewer (`F5` save / `F9` load) using `save_game_json`/`load_game_json` contracts.
- `src/hexcrawler/cli/replay_tool.py`
  - Headless replay forensics CLI operating on canonical game saves; artifact output includes signals/tracks/spawns/rumors/entities/outcomes.
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
  - `python run_game.py [--map-path ...] [--with-encounters] [--headless]`
  - `HEXCRAWLER_HEADLESS=1 python run_game.py [--map-path ...] [--with-encounters]`
  - Encounter panel location: upper-right "Encounter Debug" section in the running window.
  - Encounter debug data appears only when run with `--with-encounters`; otherwise the panel shows an explicit enablement hint.
  - Troubleshooting: if `SDL_VIDEODRIVER=dummy` (explicitly, via `--headless`, or via `HEXCRAWLER_HEADLESS=1`) or you are in WSL/remote/headless environments, no real window will appear.
- Run replay tool from canonical save:
  - `PYTHONPATH=src python -m hexcrawler.cli.replay_tool saves/sample_save.json --ticks 200`
- `PYTHONPATH=src python -m hexcrawler.cli.replay_tool saves/sample_save.json --ticks 200 --print-artifacts`
- `PYTHONPATH=src pytest -q tests/test_supply_consumption.py`
- `PYTHONPATH=src pytest -q tests/test_supplies_content.py`
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
- ✅ Phase 4C complete: eligible encounter rolls now emit deterministic content-free `encounter_result_stub` events with coarse categories (`hostile`, `neutral`, `omen`) and no world mutation side effects.
- ✅ Phase 4D complete: `encounter_check` now carries explicit `trigger` semantics (`idle`) and the module propagates `trigger` deterministically through `encounter_roll` and `encounter_result_stub` with unchanged RNG/cooldown contracts.
- ✅ Phase 4E complete: movement now emits serialized `travel_step` events on hex-boundary crossings and `EncounterCheckModule` reacts by scheduling `encounter_check` with `trigger="travel"` while keeping eligibility/cooldown/RNG behavior unchanged.
- ✅ Phase 4F complete: introduced opaque `LocationRef` contracts and migrated encounter-facing travel/check/roll/result event payloads from raw axial dicts to location references without semantic or RNG changes.
- ✅ Phase 4G complete: `encounter_result_stub` now deterministically schedules `encounter_resolve_request` at +1 tick with a minimal passthrough payload (`tick`, `context`, `trigger`, `location`, `roll`, `category`) and no content selection side effects.
- ✅ Phase 4H complete: validated encounter-table content now feeds deterministic weighted selection in `EncounterSelectionModule`, emitting descriptive `encounter_selection_stub` events via RNG stream `encounter_selection` with save/load + replay hash stability.
- ✅ Phase 4I complete: `EncounterActionModule` now emits deterministic descriptive `encounter_action_stub` events (+1 tick after selection) with extensible declarative `actions` intents and no action execution or world mutation.
- ✅ Phase 4J complete: `EncounterActionExecutionModule` now schedules deterministic `encounter_action_execute` events (+1 tick after action stubs), executes provisional `signal_intent`/`track_intent` records idempotently, persists a serialized executed UID ledger in rules-state, and emits deterministic `encounter_action_outcome` forensic events (including `ignored_unsupported`).
- ✅ Phase 4V complete: pygame UI now has a read-only encounter visibility panel for `encounter_check` rules-state and recent encounter execution trace entries.

## New Public APIs (Phase 4I)
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
- `hexcrawler.sim.encounters.ENCOUNTER_TRIGGER_IDLE`
- `hexcrawler.sim.encounters.ENCOUNTER_TRIGGER_TRAVEL`
- `hexcrawler.sim.encounters.ENCOUNTER_CHANCE_PERCENT`
- `hexcrawler.sim.encounters.ENCOUNTER_COOLDOWN_TICKS`
- `hexcrawler.sim.encounters.ENCOUNTER_RESULT_STUB_EVENT_TYPE`
- `hexcrawler.sim.encounters.ENCOUNTER_RESOLVE_REQUEST_EVENT_TYPE`
- `hexcrawler.sim.encounters.EncounterSelectionModule`
- `hexcrawler.sim.encounters.ENCOUNTER_SELECTION_STUB_EVENT_TYPE`
- `hexcrawler.sim.encounters.EncounterActionModule`
- `hexcrawler.sim.encounters.ENCOUNTER_ACTION_STUB_EVENT_TYPE`
- `hexcrawler.sim.encounters.ENCOUNTER_ACTION_EXECUTE_EVENT_TYPE`
- `hexcrawler.sim.encounters.ENCOUNTER_ACTION_OUTCOME_EVENT_TYPE`
- `hexcrawler.sim.encounters.EncounterActionExecutionModule`
- `hexcrawler.sim.encounters.SpawnMaterializationModule`
- `hexcrawler.content.encounters.load_encounter_table_json(path)`
- `hexcrawler.content.encounters.validate_encounter_table_payload(payload)`
- `hexcrawler.content.encounters.DEFAULT_ENCOUNTER_TABLE_PATH`
- `hexcrawler.sim.core.TRAVEL_STEP_EVENT_TYPE`
- `hexcrawler.content.supplies.load_supply_profiles_json(path)`
- `hexcrawler.content.supplies.DEFAULT_SUPPLY_PROFILES_PATH`
- `hexcrawler.sim.supplies.SupplyConsumptionModule`
- `hexcrawler.sim.supplies.SUPPLY_OUTCOME_EVENT_TYPE`
- `hexcrawler.sim.location.LocationRef`
- `hexcrawler.sim.location.OVERWORLD_HEX_TOPOLOGY`

## Out of Scope Kept
- No towns/markets/prices/economy systems in this phase.
- No combat/wounds/armor/HP systems in this phase.
- No AI/factions/networking in this phase.

## Current Verification Commands
- `python -m pip install -r requirements.txt`
- `python run_game.py [--map-path ...] [--with-encounters] [--save-path ...] [--load-save ...]  # default map: content/examples/viewer_map.json`
- `python run_game.py --headless`
- `HEXCRAWLER_HEADLESS=1 python run_game.py --with-encounters`
- `python run_game.py --with-encounters --save-path saves/canonical_with_artifacts.json`
  - Move briefly, press `F5`, then quit.
- `PYTHONPATH=src python -m hexcrawler.cli.replay_tool saves/canonical_with_artifacts.json --ticks 400 --print-artifacts`
- `PYTHONPATH=src pytest -q`
- `set PYTHONPATH=src && pytest -q`
- `PYTHONPATH=src pytest -q tests/test_check_runner.py`
- `PYTHONPATH=src pytest -q tests/test_rules_state.py`
- `PYTHONPATH=src pytest -q tests/test_periodic_scheduler.py`
- `PYTHONPATH=src pytest -q tests/test_rule_modules.py`
- `PYTHONPATH=src pytest -q tests/test_event_queue.py`
- `PYTHONPATH=src pytest -q tests/test_event_trace.py`
- `PYTHONPATH=src pytest -q tests/test_encounter_check_module.py`
- `PYTHONPATH=src pytest -q tests/test_encounter_selection_module.py`
- `PYTHONPATH=src python -m hexcrawler.cli.new_save_from_map --help`
- `PYTHONPATH=src python -m hexcrawler.cli.new_save_from_map content/examples/basic_map.json saves/sample_save.json --seed 123 --force --print-summary`
- `PYTHONPATH=src python -m hexcrawler.cli.replay_tool saves/sample_save.json --ticks 200`
- `PYTHONPATH=src python -m hexcrawler.cli.replay_tool saves/sample_save.json --ticks 200 --print-artifacts`
- `PYTHONPATH=src pytest -q tests/test_supply_consumption.py`
- `PYTHONPATH=src pytest -q tests/test_supplies_content.py`
- `sed -n '1,220p' docs/PROMPTLOG.md`

## Initial Supported Action Set (provisional)
- `signal_intent`
- `track_intent`
- `spawn_intent`
- `transition_space` (simulation command seam; structural space transition only)
- `inventory_intent` (simulation command seam; stackable inventory delta substrate)

## Track Emission Note
- `track_intent` is supported by the execution substrate, but tracks are not emitted by default `content/examples/encounters/basic_encounters.json` entries in this phase (artifacts may show `track none` unless custom content/tests include track actions).

## Repo Hygiene Note
- Assessed potential stray path `python`: no such tracked/untracked file or directory exists in the repo root at this time (`git status -sb` clean, `test -e python` false), so no deletion/ignore change was necessary in this commit.

## What Changed in This Commit
- Added data-driven supply profile content (`content/supplies/supply_profiles.json`) plus strict deterministic loader/validator (`hexcrawler.content.supplies`) and added `water` to default stackable items for the baseline player profile.
- Added Phase 5H2 deterministic supply accounting: player default supply profile assignment, periodic consumption scheduling via `PeriodicScheduler`, authoritative inventory consumption through existing `inventory_intent` apply path, idempotent consumption ledger, and deterministic `supply_outcome` forensic events + warning stubs.
- Extended read-only visibility surfaces: pygame debug panel now shows key supplies + recent supply outcomes, and replay tool `--print-artifacts` now prints supply outcome artifacts; added deterministic tests for content validation, scheduling, no-negative behavior, insufficient outcomes, determinism, and save/load stability.

## Troubleshooting
- On CI/WSL/remote shells without a GUI display, run `python run_game.py --headless` (or set `HEXCRAWLER_HEADLESS=1`) to force SDL dummy mode and validate startup paths without opening a window.
