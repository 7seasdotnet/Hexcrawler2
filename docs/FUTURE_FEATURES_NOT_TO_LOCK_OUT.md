# Future Features — Must Not Lock Out

## How to use this doc
Use this document as an architecture guardrail checklist, not a feature roadmap.
Before merging substrate or domain changes, verify no listed constraint is violated.
Each item defines a required capability boundary the engine must preserve.
If a change appears to weaken a constraint, update contracts explicitly before implementation.
These constraints are additive to `docs/ARCHITECTURE.md` and phase scope in `docs/STATUS.md`.
Do not implement future features here; preserve feasibility only.

## Constraints
- **Must support server-authoritative simulation in a future multiplayer mode without requiring any direct UI/viewer mutation path into world state.**
  - Why it matters: preserving command/event-only mutation paths keeps determinism, replayability, and anti-desync safety intact.

- **Must support command/event ingestion from non-local clients without requiring alternate simulation logic paths for networked vs local execution.**
  - Why it matters: one authoritative execution path prevents forked behavior and replay/hash divergence.

- **Must support editor-first content extension without requiring engine code changes for routine data additions (encounters, rumors, items, tables, forms).**
  - Why it matters: long-term content scale depends on data workflows rather than code churn.

- **Must support patchable content bundles and partial overrides without requiring mutation of canonical base files at runtime.**
  - Why it matters: safe modding/live-ops workflows require deterministic layering and reversible content provenance.

- **Must support strict schema validation with deterministic failure modes without requiring permissive runtime guessing for malformed payloads.**
  - Why it matters: predictable validation protects save compatibility, tooling, and replay stability.

- **Must support forward-compatible unknown content fields without requiring old runtimes to understand new semantics to remain load-safe.**
  - Why it matters: preserving unknown fields enables gradual migrations and mixed-version toolchains.

- **Must support multiple world spaces/topologies (hex, rectangular, and future nested spaces) without requiring separate clocks or per-space simulation loops.**
  - Why it matters: shared authoritative time is required for cross-space causality and deterministic scheduling.

- **Must support hierarchical or nested location references in future (site interiors, sub-grids, overlays) without requiring a breaking rewrite of identity semantics.**
  - Why it matters: stable location identity unlocks expansion while preserving save/load and command compatibility.

- **Must support future occlusion-aware and wave-like signal propagation models without requiring replacement of the deterministic command/event substrate.**
  - Why it matters: richer perception can be layered incrementally if scheduling and serialization contracts remain stable.

- **Must support richer wounds and armor-threshold rule sets via table-driven content without requiring hard-coded combat logic branches per creature/item.**
  - Why it matters: data-first rules keep lethality tuning transparent, testable, and editor-extensible.

- **Must support rule-module replacement and reordering experiments without requiring persistent correctness to depend on module in-memory state.**
  - Why it matters: module ephemerality is essential for restart/replay determinism and save/load continuity.

- **Must support deterministic idempotence for delayed actions/events without requiring process-lifetime caches or hidden cooldown maps.**
  - Why it matters: serialized ledgers are required to survive restarts and prevent duplicate world mutation.

- **Must support bounded forensic/history buffers without requiring unbounded logs, traces, or world record growth.**
  - Why it matters: memory and save size must remain predictable under long-running persistent simulation.

- **Must support bounded queue/backlog behavior under load without requiring dynamic unbounded retries or recursive same-tick fan-out.**
  - Why it matters: bounded execution protects performance ceilings while keeping deterministic failure handling explicit.

- **Must support deterministic save migrations across schema versions without requiring ad-hoc one-off migration code paths outside canonical loaders.**
  - Why it matters: centralized migrations preserve reproducibility and reduce compatibility regressions.
