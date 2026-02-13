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

## 5) RNG Contract
- **Contract:** Simulation owns RNG usage; no gameplay logic may depend on global random state.
- **Contract:** Use deterministically-derived RNG streams at minimum for:
  - world generation (`rng_worldgen`),
  - runtime simulation (`rng_sim`).
- **Contract:** Child stream seeds are derived from the single master seed using SHA-256 over UTF-8 bytes of `f"{master_seed}:{stream_name}"`, then interpreted as an unsigned 64-bit integer from the first 8 digest bytes (big-endian).
- **Contract:** Python `hash()` is forbidden for seed derivation because of per-process hash randomization.
- **Contract:** Stream separation is required to reduce butterfly effects when new random calls are inserted in one subsystem.

## 6) Serialization Contract (Elite)
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

## 7) Movement Contract
- **Contract:** Motion is continuous in simulation space (`position_x`, `position_y`).
- **Contract:** Entity hex is derived from position via deterministic cube-rounding axial conversion.
- **Contract:** Hex derivation/projection logic is defined in the simulation layer and reused by viewers (no duplicate rounding logic in viewers).
- **Contract:** Hex transitions must be stable (no boundary flicker behavior).
- **Contract:** Viewers/controllers never mutate positions directly; they only issue simulation commands.

## 8) Fixed-Point Migration Path (Note)
- **Contract:** Current runtime uses floats with fixed-tick stepping and deterministic update order.
- **Contract:** If cross-platform float drift becomes unacceptable, migration path is:
  1. introduce fixed-point position type,
  2. keep command/tick semantics unchanged,
  3. add dual-hash regression window,
  4. cut over serialization schema version.
- **Contract:** No fixed-point commitment is made now; this is a planned compatibility path.
