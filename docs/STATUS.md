# Hexcrawler2 — Current State

## Lock-out Review
- **Lock-out constraints reviewed: OK**

## Phase
- **Current phase:** **Playable Core Loop Slice — Campaign Travel → Contact → Local Encounter → Combat → Extraction/Return**.
- **Next action:** Validate the retreat→safe-site→recover rhythm in the playable loop and tune bounded recovery values without expanding into full medical simulation.
- **Phase status:** Active phase reset complete (documentation-only). Substrate expansion is no longer the default path unless directly required to ship this playable loop.

## Playable Milestone Definition (First Cash-Out Loop)
A milestone build is considered successful when a player can:
1) start from a safe site,
2) travel on the authoritative continuous **campaign** plane,
3) observe and choose to avoid/engage visible danger presence,
4) transition deterministically into a **local** encounter space,
5) survive brutal combat or die,
6) extract/return with persistent consequences still in effect.

## Immediate Priority Rule (Phase Discipline)
During this phase, new work is prioritized by all of the following:
1) direct player-facing payoff,
2) direct relevance to the playable loop above,
3) bounded complexity growth,
4) compatibility with architecture invariants and determinism contracts.

If a task does not materially advance the playable loop, defer it unless it is strictly required to unblock the loop.

## A4 Policy — Active Path vs Preserved-But-Not-Immediate-Critical-Path

### Active Path Systems (current playable slice)
Prefer implementation work in this set unless a justified dependency requires otherwise:
- campaign-role travel/movement visibility on the continuous campaign plane,
- visible campaign danger/contact,
- deterministic campaign → local encounter handoff,
- minimal hostile local behavior,
- fast brutal local combat resolution,
- wound application/persistence,
- extraction/return pressure with minimal supporting supplies/loot/recovery surfaces, including safe-site recovery rest.

### Preserved but Not Immediate Critical Path
These systems remain valid and preserved, but are **not immediate critical path** and should expand only when directly required by the playable slice:
- deeper belief/intelligence propagation,
- advanced diplomacy/political reaction depth,
- broader ecology/site evolution depth,
- nonessential observability expansion,
- editor expansion beyond slice-critical authoring/testing needs,
- higher-order rumor sophistication beyond immediate gameplay payoff.

### Decision Rule for Future Work
Select work in this order:
1) player-facing payoff,
2) direct relevance to the current playable loop,
3) bounded complexity/growth,
4) compatibility with locked architecture contracts.

### Anti-Drift Reminder
Robust/engine-first/do-not-lock-out requirements are architecture guardrails, not permission to expand noncritical systems ahead of playable-loop delivery.

## Invariants (Unchanged, Non-Negotiable)
- Deterministic simulation remains authoritative.
- Authoritative mutation remains command/event-driven only.
- Persistent state remains serialized and hash-covered.
- Queues/logs/containers remain bounded.
- Viewer/UI remains read-only with respect to simulation mutation.
- Campaign/local role separation remains mandatory.
- Multiplayer-safe architecture remains preserved (no lock-out).
- Editor-first extensibility remains preserved.
- Rule modules remain ephemeral behavioral shells (no correctness-critical in-memory state).
- Continuous campaign plane remains authoritative; hex membership remains derived.
- Local topology/projection flexibility remains preserved.

## Supported Action Intent Types (Current)
- Combat/tactical intents currently executed through the authoritative seam: `attack_intent`, `turn_intent` (local-role gated).
- Provisional deterministic encounter action intents currently executed: `signal_intent`, `track_intent`.
- Campaign recovery intent currently executed through rule-module command/event seam: `safe_recovery_intent` (campaign-role and safe-site gated).
- Unknown/unsupported intents must continue to be ignored deterministically with recorded outcomes.

## What Exists (folders / entry points)
- `src/hexcrawler/sim/`: deterministic simulation core, event queue, command processing, encounter/event seams, world/state hashing, save/load substrate.
- `src/hexcrawler/content/`: content loaders/validators for encounter/supply and related data payloads.
- `src/hexcrawler/cli/pygame_viewer.py`: read-only viewer/editor-facing runtime controls and inspection surfaces.
- `play.py`: canonical launch entry point.

## Current Verification Commands (known working)
- `PYTHONPATH=src pytest -q`
- `python -m py_compile src/hexcrawler/cli/pygame_viewer.py tests/test_pygame_viewer_runtime.py tests/test_pygame_viewer_layout.py tests/test_pygame_viewer_cli.py`
- `python play.py --headless`
- `python play.py`

## What changed in this commit
- Added deterministic bounds/capping for safe-recovery UID ledgers (`recovery_scheduled_action_uids`, `recovery_completed_action_uids`) with FIFO eviction to preserve bounded serialized state.
- Kept the campaign-role safe-site delayed recovery seam unchanged while tightening ledger normalization and validation behavior.
- Added focused tests for ledger-cap eviction determinism and invalid recovery ledger type handling alongside the existing recovery-loop coverage.
