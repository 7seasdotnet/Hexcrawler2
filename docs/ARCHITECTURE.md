# Engine Architecture Contracts (MVP)

This document locks core engine contracts and invariants for the simulation substrate.

## 1) World Contract
- **Contract:** `WorldState` is the deterministic simulation container.
- **Contract:** World data includes:
  - topology definition parameters (generation inputs),
  - realized valid-cell set (`world.hexes: dict[HexCoord, HexRecord]`),
  - entities (via simulation state),
  - simulation tick counter,
  - simulation-owned RNG state.
- **Contract:** Rendering/view state is never part of world state.

## 2) Topology Contract
- **Contract:** Current overworld topology is bounded axial hex.
- **Contract:** Bounds are enforced by valid-hex membership (`coord in world.hexes`), not by separate min/max clamps.
- **Contract:** Generation helpers (for example: disk/rectangle) may be used to create topology, but persistence stores only the realized valid-cell set.
- **Contract:** Future dungeon spaces may use a different topology (for example: square grid) while sharing the same simulation clock and entity model.

## 3) Time Contract
- **Contract:** Authoritative simulation advances only via `advance_ticks(n)` and `advance_days(n)`.
- **Contract:** Tick duration is an in-world quantum; wall-clock stepping/speed controls are viewer concerns.
- **Contract:** `TICKS_PER_DAY` is configuration, not a forever-locked design constant (default currently `240`).
- **Contract:** Subsystems may evaluate at different intervals on the same master tick timeline; do not introduce separate incompatible tick systems.

## 4) Determinism Contract
- **Contract:** Same initial state + same seed + same input log => identical world/simulation hash.
- **Contract:** Non-determinism is allowed only in rendering/presentation.
- **Contract:** Player/viewer actions must be represented as commands applied at specific ticks (input log semantics).
- **Contract:** Simulation stores an ordered input log (`tick`, `entity_id`, `command_type`, `params`), applies every command scheduled for tick `T` before entity updates on tick `T`, and preserves insertion order for commands with the same tick.
- **Contract:** Replay runs consume the same command log through the same simulation path (no alternate gameplay logic path for replay).


## 5) Event Queue Substrate Contract
- **Contract:** Simulation owns a deterministic event queue substrate with serialized `SimEvent` records (`tick`, `event_id`, `event_type`, `params`, `unknown_fields`).
- **Contract:** Pending events are keyed by absolute tick and preserve insertion order for events scheduled on the same tick.
- **Contract:** Authoritative per-tick phase ordering is: (1) apply commands for tick `T`, (2) execute events for tick `T`, (3) run entity updates for tick `T`, (4) increment tick counter.
- **Contract:** Replay runs use the exact same command/event execution path as runtime simulation (no replay-specific event path).
- **Contract:** Event queue state (including future-tick events and event ID counter) is serialized in canonical saves and contributes to `simulation_hash`.

## 6) RNG Contract
- **Contract:** Simulation owns RNG usage; no gameplay logic may depend on global random state.
- **Contract:** Use deterministically-derived RNG streams at minimum for:
  - world generation (`rng_worldgen`),
  - runtime simulation (`rng_sim`).
- **Contract:** Child stream seeds are derived from the single master seed using SHA-256 over UTF-8 bytes of `f"{master_seed}:{stream_name}"`, then interpreted as an unsigned 64-bit integer from the first 8 digest bytes (big-endian).
- **Contract:** Python `hash()` is forbidden for seed derivation because of per-process hash randomization.
- **Contract:** Stream separation is required to reduce butterfly effects when new random calls are inserted in one subsystem.

## 6B) Rule Module Substrate
- **Purpose:** Provide a deterministic plugin substrate so rule logic can hook into simulation lifecycle without adding gameplay logic to `Simulation` core.
- **Contract:** Rule modules are registered with `Simulation.register_rule_module(module)` and execute in strict registration order.
- **Contract:** Duplicate module names are rejected (`ValueError`) to preserve stable module identity and registration ordering.
- **Lifecycle Hook Order (tick `T`):**
  1. `module.on_tick_start(sim, T)` for each module in registration order,
  2. apply commands scheduled for `T`,
  3. execute events scheduled for `T`, and after each event execution call `module.on_event_executed(sim, event)` in registration order,
  4. entity updates for `T`,
  5. `module.on_tick_end(sim, T)` for each module in registration order,
  6. increment simulation tick.
- **Determinism Guarantee:** Registration order is authoritative ordering; no hidden sorting or global state.
- **RNG Requirement for Modules:** Modules must use `sim.rng_stream("stream_name")` for randomness. Direct use of `random.Random()` or global `random` in modules is forbidden.
- **World Mutation Boundary:** Modules must mutate simulation state only through public `Simulation` APIs (commands/events/simulation methods), never by directly mutating underlying world/entity internals.

## 6C) Periodic Scheduling Substrate
- **Purpose:** Provide a generic deterministic fixed-interval scheduler for rule modules without embedding gameplay/domain semantics.
- **Contract:** `PeriodicScheduler` is a rule module (`name="periodic_scheduler"`) that schedules and executes periodic tasks strictly through `SimEvent` records with `event_type="periodic_tick"` and params `{"task": <task_name>, "interval": <interval_ticks>}`.
- **Contract:** Periodic task registration API:
  - `register_task(task_name, interval_ticks, start_tick=0)` is idempotent when parameters are consistent with existing task metadata.
  - Re-registering an existing task with a conflicting interval is rejected deterministically (`ValueError`); no silent override is permitted.
  - `set_task_callback(task_name, callback)` where callback signature is `(sim, tick)`.
- **Contract:** When a periodic event fires at tick `T`, scheduler behavior is deterministic and ordered:
  1. invoke callback for task (if attached),
  2. schedule next periodic event at tick `T + interval_ticks`.
- **Ordering Rule:** Same-tick periodic tasks execute in event queue FIFO order. For tasks registered with the same `start_tick`, initial event insertion order is registration order.
- **Persistence Model:** Pending periodic events in the serialized event queue are the single source of truth for future executions; there are no hidden wall-clock timers or non-serialized timer state.
- **Load/Rehydrate Behavior:** On simulation start, scheduler metadata is reconstructed from pending `periodic_tick` events sorted by `(tick, task_name)`.
  - The serialized pending event queue is authoritative for task existence and next-fire timing.
  - Rehydration must not create duplicate periodic chains when a task already has pending events.
  - Callback callables remain in-memory only and must be reattached after load.

## 6D) Rule Module Persistence Boundary
- **Contract:** Rule modules are not serialized and must be treated as ephemeral behavioral shells.
- **Contract:** A rule module must never rely on in-memory state (counters, cooldowns, caches, “already processed” sets, etc.) for correctness across save/load, replay, or process restart.
- **Contract:** Any state that must persist across ticks must be represented in serialized, hash-covered substrates:
  1. world/simulation state (via Simulation APIs), and/or
  2. scheduled events (deterministic event queue), and/or
  3. input log (commands), where applicable.
- **Contract:** PeriodicScheduler callbacks are reattached after load; callbacks must be safe under “no persistent module memory” and derive any needed context exclusively from serialized state.
- **Contract:** Until an explicit serialized “module state” substrate is introduced and locked by tests, modules must be stateless beyond configuration constants.
- **Contract:** `rules_state` is the explicit serialized per-module persistence substrate (`dict[str, JSON-object]`) and is hash-covered via `simulation_hash`/canonical saves; module persistent state must live only in `rules_state`, scheduled events, and/or world state APIs.

## 6E) Encounter Check Eligibility Gate (Phase 4B)
- **Purpose:** Extend the content-free encounter skeleton with deterministic eligibility accounting while still avoiding encounter content logic.
- **Contract:** `EncounterCheckModule` emits fixed-interval `encounter_check` events and deterministically evaluates an eligibility gate per check.
- **Contract:** On eligible checks, the module emits `encounter_roll` with deterministic params (`tick`, `context`, `roll`) using the same encounter RNG stream.
- **Contract:** Encounter logic remains intentionally content-free in Phase 4B: no encounter table lookups, no encounter resolution, no faction/ecology logic, no world mutation side effects, and no combat spawning.
- **Contract:** Eligibility/accounting persistence is stored only in serialized `rules_state["encounter_check"]` (`last_check_tick`, `checks_emitted`, `eligible_count`, `ineligible_streak`, `cooldown_until_tick`); no in-memory counters are authoritative.
- **Contract:** All randomness in this module must consume `sim.rng_stream("encounter_check")` to preserve deterministic stream continuity and hash stability across save/load/replay.

## 6F) Encounter Result Stub Seam (Phase 4C)
- **Purpose:** Add a stable, deterministic downstream seam after `encounter_roll` while remaining strictly content-free.
- **Contract:** When `encounter_roll` executes, `EncounterCheckModule` must schedule `encounter_result_stub` at `event.tick + 1`.
- **Contract:** `encounter_result_stub` params are deterministic and minimal: `tick`, `context`, `roll`, and coarse `category` only.
- **Contract:** Category derivation is deterministic from roll bands (`1-40 => hostile`, `41-75 => neutral`, `76-100 => omen`) and uses no additional RNG.
- **Contract:** Phase 4C remains content-free: no encounter-table selection, no NPC/spawn creation, no faction/ecology logic, and no world mutation side effects.
- **Contract:** Save/load/replay determinism is enforced by serialized event queue + event trace + rules_state; no module in-memory state is authoritative.

## 6G) Encounter Trigger Semantics Contract (Phase 4E)
- **Purpose:** Keep encounter triggers explicit while extending the substrate with an event-driven travel channel and preserving content-free deterministic behavior.
- **Contract:** `encounter_check` params include explicit `trigger`.
- **Contract:** Allowed values currently: `"idle"` and `"travel"`.
- **Contract:** `TRAVEL_STEP_EVENT_TYPE = "travel_step"` is a deterministic serialized event emitted by simulation movement when an entity crosses a hex boundary.
- **Contract:** `travel_step` params are minimal and deterministic: `tick`, `entity_id`, `from_hex`, and `to_hex`; no RNG usage and no world mutation side effects.
- **Contract:** Encounter module integration is reactive: on `travel_step`, `EncounterCheckModule` schedules `encounter_check` with `trigger="travel"` through normal simulation event APIs.
- **Contract:** Periodic scheduler checks continue to emit `encounter_check` with `trigger="idle"`; interval/cooldown behavior remains unchanged.
- **Contract:** `encounter_roll` must propagate `tick`, `context`, `roll`, and `trigger` exactly from the triggering check.
- **Contract:** `encounter_result_stub` must propagate `tick`, `context`, `roll`, `category`, and `trigger` from `encounter_roll` with no added randomness.
- **Contract:** Trigger channels are structural only in Phase 4E: no semantic branching by trigger value (no probability changes, terrain modifiers, or hex-based scaling).
- **Contract:** RNG usage remains strictly `sim.rng_stream("encounter_check")`; no new RNG streams and no additional RNG draws.

## 7) Serialization Contract (Elite)
- **Contract:** Save -> load must round-trip to identical world hash.
- **Contract:** Save payloads include top-level `schema_version`.
- **Contract:** Backward compatibility window policy: each save format must remain readable by at least one previous schema version.
- **Contract:** Serialization uses canonical JSON rules (stable key ordering and stable formatting).
- **Contract:** Saves are atomic (write temp file, then rename).
- **Contract:** Canonical game saves are the single source of truth and include `schema_version`, `save_hash`, `world_state`, `simulation_state`, `input_log`, and optional `metadata`.
- **Contract:** `save_hash` is computed from `schema_version` + `world_state` + `simulation_state` + `input_log` and excludes `save_hash` itself.
- **Contract:** Canonical save loader fails fast on `save_hash` mismatch.
- **Contract:** Legacy world-only payloads (`world_hash` + top-level world fields) remain loadable for compatibility with existing viewers.
- **Contract:** Unknown fields should be preserved where feasible (especially `metadata`) for forward compatibility.
- **Contract:** `event_trace` is a bounded, serialized, hash-covered execution history buffer for inspection and debugging.

## 8) Movement Contract
- **Contract:** Motion is continuous in simulation space (`position_x`, `position_y`).
- **Contract:** Entity hex is derived from position via deterministic cube-rounding axial conversion.
- **Contract:** Hex derivation/projection logic is defined in the simulation layer and reused by viewers (no duplicate rounding logic in viewers).
- **Contract:** Hex transitions must be stable (no boundary flicker behavior).
- **Contract:** Viewers/controllers never mutate positions directly; they only issue simulation commands.

## 9) Fixed-Point Migration Path (Note)
- **Contract:** Current runtime uses floats with fixed-tick stepping and deterministic update order.
- **Contract:** If cross-platform float drift becomes unacceptable, migration path is:
  1. introduce fixed-point position type,
  2. keep command/tick semantics unchanged,
  3. add dual-hash regression window,
  4. cut over serialization schema version.
- **Contract:** No fixed-point commitment is made now; this is a planned compatibility path.

## 10) Rendering & Interpolation Contract
- **Contract:** Simulation remains fixed-tick authoritative and only advances on simulation tick boundaries.
- **Contract:** Viewer rendering may run at a higher frame rate and interpolate visual positions between the previous committed tick state (`T-1`) and current committed tick state (`T`).
- **Contract:** Interpolation alpha is derived from wall-clock frame time relative to tick duration and clamped to `[0, 1]`.
- **Contract:** Interpolated render positions are presentation-only and must never feed back into simulation state, command logs, RNG, or hashing.

## 11) Replay Forensics CLI Contract
- **Contract:** `python -m hexcrawler.cli.replay_tool <save_path> --ticks N` replays forward from the **current saved simulation state** (not reconstruction from tick 0).
- **Contract:** Replay tool uses the same simulation stepping path and command execution semantics as runtime simulation; no alternate replay gameplay logic is introduced.
- **Contract:** Tooling output is concise by default (`header`, `integrity=OK`, `start_hash`, `end_hash`) with optional flags for per-tick hashes and input-log command-type summaries.
- **Contract:** Replay CLI is forensic/debug tooling only and must not alter simulation semantics, RNG behavior, or command execution order.

## 12) Content Template vs Runtime Save Boundary Contract
- **Contract:** `content/` stores world-only map templates used for authoring and iteration; templates are serialized as world payloads (`schema_version`, `world_hash`, top-level world fields).
- **Contract:** Runtime play/replay operates on canonical game saves under `saves/` (or equivalent runtime output path), never directly on content templates.
- **Contract:** `python -m hexcrawler.cli.new_save_from_map <map_template.json> <save.json> --seed <N>` is the canonical bridge from template content to runtime save state.
- **Contract:** `new_save_from_map` refuses canonical input saves to keep the boundary explicit and avoid silently mixing content authoring with runtime state.
- **Contract:** Viewer entrypoints may still load world templates for editor/prototyping workflows, but replay/forensics tooling must consume canonical game saves.
- **Workflow:** Build runtime save from template: `PYTHONPATH=src python -m hexcrawler.cli.new_save_from_map content/examples/basic_map.json saves/sample_save.json --seed 123 --force --print-summary`.
- **Workflow:** Run pygame viewer from map template flow: `python run_game.py`.
- **Workflow:** Run replay forensics on canonical save: `PYTHONPATH=src python -m hexcrawler.cli.replay_tool saves/sample_save.json --ticks 200`.
