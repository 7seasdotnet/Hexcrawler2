# Hexcrawler2 — Current State

## Lock-out Review
- **Lock-out constraints reviewed: OK**

## Phase
- **Current phase:** **Playable Core Loop Slice — Campaign Travel → Contact → Local Encounter → Combat → Extraction/Return**.
- **Next action:** Implement deterministic, player-visible campaign danger movers with a deterministic contact handoff into a minimal hostile local encounter that can inflict persistent wounds and force extraction/return decisions.
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

## Long-Term Ambitions Preserved (Not Abandoned)
The following remain valid and required long-term goals, but must not displace the current playable slice:
- deeper ecology/world simulation,
- deeper diegetic intelligence/belief/rumor richness,
- richer in-game editor workflows,
- broader systemic world simulation richness,
- multiplayer-safe/server-authoritative feasibility.

## Not on Immediate Critical Path
Advanced second-order systems are preserved as constraints and future direction, but are **not** on the immediate critical path unless a specific element is required to ship the playable slice above.

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
- Provisional deterministic encounter action intents currently executed: `signal_intent`, `track_intent`.
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
- Reset active phase framing from substrate-hardening emphasis to a single, explicit **Playable Core Loop Slice** execution phase.
- Rewrote next-action and milestone language to force player-visible delivery: campaign travel, visible contact, local encounter, brutal combat, extraction/return, persistent consequences.
- Kept determinism, mutation safety, role separation, and long-term anti-lock-out constraints explicit while marking advanced systems as not on immediate critical path.
