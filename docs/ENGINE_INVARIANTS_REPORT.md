# Engine Invariants & Evidence Report (Broad Readiness Audit)

Date: 2026-02-19  
Scope: Substrate/readiness audit only (no gameplay semantics changes)

## Summary of Findings
- **No confirmed hard invariant violations** were found in the audited substrate contracts.
- Determinism, canonical serialization/hash coverage, and bounded same-tick execution guards have direct code enforcement and regression coverage.
- Evidence gaps called out by this audit now have direct regression coverage for controller mutation timing, near-cap bounded ledgers, and absent-vs-empty canonicalization parity on selected optional world fields.

---

## 1) Determinism & Authority

### Invariant 1.1 — Single authoritative mutation path
- **Statement:** Authoritative world mutation happens through command/event execution and module hooks on the simulation tick path; UI/controller paths do not directly mutate simulation state.
- **Enforced at:**
  - `Simulation._tick_once` phase order and command/event/entity lifecycle.
  - `Simulation._execute_command` seam dispatch + module command hooks.
  - `SimulationController.set_destination` appends `SimCommand` instead of mutating world/entity state.
- **Current tests:**
  - `tests/test_viewer_controller.py::test_ascii_viewer_controller_goto_appends_command`
  - `tests/test_phase5q_integrity_audit.py::test_invalid_intents_fail_deterministically_without_mutation_across_new_seams`
  - `tests/test_phase5q_integrity_audit.py::test_controller_set_destination_does_not_mutate_authoritative_state_until_tick`
- **Gaps:** None significant for this seam after direct no-mutation timing regression coverage.
- **Risk:** **Low**.
- **Proposed minimal test(s):** None.

### Invariant 1.2 — Same seed + same input log => identical hash
- **Statement:** Replayability contract: same initial conditions and input log produce identical simulation hash.
- **Enforced at:**
  - `simulation_hash(...)` canonical hashed payload.
  - deterministic tick/order in `Simulation._tick_once`.
  - deterministic stream derivation + serialized RNG state restoration.
- **Current tests:**
  - `tests/test_determinism.py::test_deterministic_seed_and_commands_produce_identical_hash`
  - `tests/test_rules_state.py::test_rules_state_replay_stability`
  - `tests/test_signal_propagation_module.py::test_signal_replay_hash_identity`
- **Gaps:** None significant for substrate.
- **Risk:** **Low**.
- **Proposed minimal test(s):** None.

### Invariant 1.3 — Same-tick event drain-until-empty FIFO ordering + deterministic runaway guard
- **Statement:** Tick `T` drains all tick-`T` events (including newly scheduled same-tick events) in deterministic insertion order, with deterministic hard cap on runaway loops.
- **Enforced at:**
  - `Simulation._execute_events_for_tick` while-loop drain and `MAX_EVENTS_PER_TICK` guard.
  - `schedule_event` + per-tick list insertion ordering.
- **Current tests:**
  - `tests/test_event_queue.py::test_ordering_same_tick`
  - `tests/test_event_queue.py::test_same_tick_event_scheduled_during_execution_is_drained`
  - `tests/test_event_queue.py::test_same_tick_event_guard_fails_deterministically`
- **Gaps:** None significant.
- **Risk:** **Low**.
- **Proposed minimal test(s):** None.

---

## 2) Serialization & Hash Coverage

### Invariant 2.1 — Canonical JSON + strict validation
- **Statement:** Saves serialize canonically and loader rejects malformed/incompatible payloads deterministically.
- **Enforced at:**
  - `content/io.py`: canonical json writer, save hash verification, atomic writes.
  - `content/schema.py`: strict shape/type validation for world/save payloads.
  - `Simulation.from_simulation_payload` + `WorldState.from_dict` structural validation paths.
- **Current tests:**
  - `tests/test_save_load.py::test_canonical_json_stable_across_save_load_cycles`
  - `tests/test_save_load.py::test_loader_rejects_missing_schema_version`
  - `tests/test_save_load.py::test_loader_rejects_unsupported_schema_version`
  - `tests/test_save_load.py::test_game_loader_rejects_malformed_world_state_signals_shape`
- **Gaps:** Validation matrix is broad but not exhaustive for all optional fields.
- **Risk:** **Low**.
- **Proposed minimal test(s):** Add a compact parameterized malformed-payload test for less-covered optional fields (e.g., `tracks`, `sites`, `containers` variants).

### Invariant 2.2 — Hash covers gameplay-relevant state
- **Statement:** `simulation_hash` and `save_hash` include world/sim/input components required for replay equivalence.
- **Enforced at:**
  - `sim/hash.py`: payload includes world, entities, RNG state, input log, rules_state, pending events, event_trace, selection state, time.
  - `content/io.py`: `save_hash` computed over `world_state`, `simulation_state`, `input_log`.
- **Current tests:**
  - `tests/test_save_load.py::test_save_hash_matches_payload_parts`
  - `tests/test_event_trace.py::test_event_trace_in_hash`
  - `tests/test_rules_state.py::test_rules_state_in_hash`
  - `tests/test_phase5q_integrity_audit.py::test_world_hash_changes_when_structure_occlusion_changes`
- **Gaps:** No single umbrella test enumerating every intended hash-covered field; coverage is distributed.
- **Risk:** **Low**.
- **Proposed minimal test(s):** Add one targeted “field flip changes simulation_hash” table test for recently added fields only.

### Invariant 2.3 — No absent-vs-empty divergence (hash-relevant)
- **Statement:** Optional fields should normalize so absent vs empty does not create unintended semantic drift.
- **Enforced at:**
  - `WorldState.from_dict` defaults absent collections/maps to deterministic empties.
  - `Simulation.from_simulation_payload` defaults `event_trace`, `rules_state`, `selected_entity_id` deterministically.
- **Current tests:**
  - `tests/test_save_load.py::test_game_save_load_round_trip_preserves_spawn_descriptors_exactly`
  - `tests/test_save_load.py::test_game_save_load_round_trip_preserves_rumors_exactly`
  - `tests/test_world_spaces.py::test_world_state_from_legacy_payload_populates_default_overworld_space`
  - `tests/test_phase5q_integrity_audit.py::test_world_optional_collections_absent_vs_empty_are_hash_equivalent`
- **Gaps:** Coverage is intentionally targeted (selected hash-relevant optional fields), not exhaustive for every optional payload field.
- **Risk:** **Low**.
- **Proposed minimal test(s):** Extend parameterized parity matrix only when new optional world collections/maps are introduced.

---

## 3) Boundedness & Backpressure

### Invariant 3.1 — Bounded ledgers/traces/queues with deterministic eviction
- **Statement:** Runtime forensic/history containers and selected ledgers must be bounded, with deterministic FIFO truncation.
- **Enforced at:**
  - `MAX_EVENT_TRACE` bounded append in simulation trace.
  - `MAX_SIGNALS` and `MAX_OCCLUSION_EDGES` bounded FIFO truncation in world state.
  - rule-state bounded UID ledgers in modules (e.g., signal execution ledger).
- **Current tests:**
  - `tests/test_event_trace.py::test_event_trace_bounded_eviction`
  - `tests/test_signal_propagation_module.py::test_signal_bounded_fifo_eviction_is_deterministic`
  - `tests/test_phase5q_integrity_audit.py::test_signal_rules_state_executed_uid_ledger_is_bounded_fifo`
  - `tests/test_phase5q_integrity_audit.py::test_world_structure_occlusion_payload_round_trip_and_fifo_bound`
- **Gaps:** Broader boundedness inventory (all module ledgers/caches) is not centrally asserted.
- **Risk:** **Low/Medium**.
- **Proposed minimal test(s):** Add a small “ledger bound smoke” test spanning two more module ledgers.

### Invariant 3.2 — No unbounded same-tick fanout
- **Statement:** Same-tick recursion/fanout cannot grow unbounded silently.
- **Enforced at:** `MAX_EVENTS_PER_TICK` guard in event drain loop.
- **Current tests:** `tests/test_event_queue.py::test_same_tick_event_guard_fails_deterministically`.
- **Gaps:** None significant.
- **Risk:** **Low**.
- **Proposed minimal test(s):** None.

---

## 4) Separation of Concerns

### Invariant 4.1 — Content templates vs runtime saves remain separated
- **Statement:** Static content loaders and runtime save payloads are distinct responsibilities; runtime save integrity does not depend on mutating base content files.
- **Enforced at:**
  - `content/*` loaders for static data.
  - `content/io.py` save/load pipeline and hash validation.
- **Current tests:**
  - `tests/test_items_content.py`
  - `tests/test_supplies_content.py`
  - `tests/test_save_load.py` save/load integrity set.
- **Gaps:** No explicit regression proving runtime save path never writes/depends on content template mutation.
- **Risk:** **Low**.
- **Proposed minimal test(s):** Add one test creating save + replay without touching content files and asserting identical behavior.

### Invariant 4.2 — Rule modules are ephemeral logic, not authoritative hidden state
- **Statement:** Persistent correctness survives save/load/restart without relying on process-memory module state.
- **Enforced at:**
  - `rules_state` serialized substrate in `SimulationState`.
  - periodic scheduler rehydration from serialized `periodic_tick` events.
- **Current tests:**
  - `tests/test_rules_state.py::test_rules_state_round_trip`
  - `tests/test_periodic_scheduler.py::test_periodic_no_duplicate_scheduling_on_rehydrate`
  - `tests/test_signal_propagation_module.py::test_signal_save_load_mid_delay_idempotence_for_emit_and_perceive`
- **Gaps:** No direct meta-test that a module-internal counter is ignored by correctness (contract is documented and followed in reviewed modules).
- **Risk:** **Low**.
- **Proposed minimal test(s):** Optional contract test fixture for any module asserting replay/save-load parity with module instance recreation.

---

## 5) Extensibility / Must-Not-Lock-Out

### Invariant 5.1 — Current surfaces do not hard-lock future options
- **Statement:** Substrate keeps command/event authority, schema validation, bounded buffers, and multi-space topology compatibility needed by future feature set.
- **Enforced at:**
  - Opaque `LocationRef` with `space_id/topology_type/coord`.
  - world `spaces` substrate and topology-aware helpers.
  - command/event-only mutation architecture and replay tooling.
- **Current tests:**
  - `tests/test_world_spaces.py` suite (legacy migration + square grid transitions)
  - `tests/test_replay_tool.py` replay output/hash path
  - `tests/test_phase5q_integrity_audit.py` mixed seam integration checks
- **Gaps:** “Future-proofness” is partly architectural judgment; not all lock-out constraints are mechanically testable today.
- **Risk:** **Medium** (design-level risk, not current breakage).
- **Proposed minimal test(s):** Keep adding seam tests whenever new substrate fields are introduced; include explicit lock-out checklist in future PRs (already required by AGENTS guidance).

---

## 6) Time Model Coherence

### Invariant 6.1 — Single authoritative simulation time; no wall-clock dependence
- **Statement:** Simulation advances only through deterministic tick/day advancement; runtime wall clock is non-authoritative.
- **Enforced at:**
  - `Simulation.advance_ticks`, `advance_days`, `SimulationTimeState`.
  - periodic task scheduling keyed to simulation tick events.
- **Current tests:**
  - `tests/test_calendar_time.py`
  - `tests/test_periodic_scheduler.py::test_periodic_fires_expected_ticks`
  - `tests/test_periodic_scheduler.py::test_periodic_persistence_roundtrip`
- **Gaps:** No explicit grep/static guard preventing accidental `time.time()` usage in sim modules.
- **Risk:** **Low/Medium**.
- **Proposed minimal test(s):** Add a lightweight static test failing if sim modules import wall-clock time APIs.

---

## 7) Debuggability & Forensics

### Invariant 7.1 — Forensic traces exist, are bounded, serialized, and hash-covered
- **Statement:** Executed event trace is durable enough for deterministic forensic inspection without unbounded growth.
- **Enforced at:**
  - event trace append + bound in simulation core.
  - serialization through `simulation_payload` and inclusion in `simulation_hash`.
- **Current tests:**
  - `tests/test_event_trace.py` full suite
- **Gaps:** Event trace currently records executed events, not a full command/effect causality chain.
- **Risk:** **Low** for current contract.
- **Proposed minimal test(s):** Optional future test for trace readability contract (key required fields) rather than new semantics.

### Invariant 7.2 — Malformed payloads fail fast predictably
- **Statement:** Invalid payloads produce deterministic exceptions and do not partially mutate state.
- **Enforced at:**
  - strict validation in `content/schema.py`, world/sim constructors.
- **Current tests:**
  - malformed payload tests in `tests/test_save_load.py`
  - `tests/test_phase5q_integrity_audit.py::test_world_signal_payload_load_validation_and_fifo_truncation`
- **Gaps:** Some malformed variants remain untested.
- **Risk:** **Low**.
- **Proposed minimal test(s):** Add parameterized malformed payload matrix for under-covered optional structures.

---

## 8) Performance / Complexity Envelope (Structural)

### Invariant 8.1 — Per-tick work and propagation are structurally bounded
- **Statement:** Core same-tick event processing is bounded; signal/occlusion pathways use bounded containers and local path checks.
- **Enforced at:**
  - event execution cap (`MAX_EVENTS_PER_TICK`).
  - bounded signal/occlusion storage with deterministic truncation.
  - topology-aware bounded path-distance helpers in signal propagation.
- **Current tests:**
  - `tests/test_event_queue.py::test_same_tick_event_guard_fails_deterministically`
  - `tests/test_signal_propagation_module.py::test_signal_occlusion_path_cost_reduces_strength_deterministically`
  - `tests/test_phase5q_integrity_audit.py::test_door_toggle_changes_signal_perception_strength_deterministically`
  - `tests/test_phase5q_integrity_audit.py::test_near_cap_ledgers_remain_bounded_with_deterministic_eviction_and_replay_hash`
- **Gaps:** No dedicated runtime benchmark in CI (intentional); structural boundedness now has near-cap deterministic stress-style evidence.
- **Risk:** **Low/Medium**.
- **Proposed minimal test(s):** Optional future benchmark harness outside unit-test suite.

---

## Determinism Verification Statement
- Determinism contracts were verified by existing regression coverage for seed/input replay identity, event ordering/drain semantics, rules-state persistence, periodic rehydration behavior, and signal/interaction mixed seam replay stability.
- No contradictory evidence was observed during this audit.

## Lock-out Constraints Review
- **Lock-out constraints reviewed: OK.**
- No code-level substrate changes were introduced by this audit, so no new lock-out surface regressions were introduced.
