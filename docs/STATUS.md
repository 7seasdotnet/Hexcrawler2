# Hexcrawler2 — Current State

## Lock-out Review
- **Lock-out constraints reviewed: OK**

## Phase
- **Current phase:** **Playable Core Loop Slice — Campaign Travel → Contact → Local Encounter → Combat → Extraction/Return**.
- **Next action:** Run a manual `python play.py` smoke to validate Greybridge Enter/E home-panel flow and committed melee strike readability in the live local encounter loop.
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
- Campaign encounter-control intents currently executed through the authoritative seam: `accept_encounter_offer`, `flee_encounter_offer`.
- Campaign recovery intent currently executed through rule-module command/event seam: `safe_recovery_intent` (campaign-role and safe-site gated).
- Campaign reward turn-in intent currently executed through rule-module command/event seam: `turn_in_reward_token_intent` (campaign-role and safe-site gated).
- Unknown/unsupported intents must continue to be ignored deterministically with recorded outcomes.

## What Exists (folders / entry points)
- `src/hexcrawler/sim/`: deterministic simulation core, event queue, command processing, encounter/event seams, world/state hashing, save/load substrate.
- `src/hexcrawler/content/`: content loaders/validators for encounter/supply and related data payloads.
- `src/hexcrawler/cli/pygame_viewer.py`: read-only viewer/editor-facing runtime controls and inspection surfaces.
- `play.py`: canonical launch entry point.

## Current Verification Commands (known working)
- `PYTHONPATH=src pytest -q`
- `PYTHONPATH=src pytest -q tests/test_pygame_viewer_cli.py tests/test_reward_turn_in_loop_p5.py tests/test_calendar_time.py`
- `PYTHONPATH=src python - <<'PY' ... core_playable visible-loop smoke (home visibility + local attack intent + hostile incapacitation + reward turn-in + calendar tie-to-tick) ... PY`
- `PYTHONPATH=src pytest -q tests/test_local_hostile_behavior_slice.py tests/test_pygame_viewer_cli.py tests/test_runtime_profiles.py tests/test_exploration_execution_module.py tests/test_reward_turn_in_loop_p5.py`
- `PYTHONPATH=src python - <<'PY' ... core_playable scripted smoke (patrol contact -> Fight -> local pressure -> return) ... PY`
- `PYTHONPATH=src pytest -q tests/test_campaign_danger_contact_slice.py`
- `PYTHONPATH=src pytest -q tests/test_campaign_danger_contact_slice.py tests/test_local_hostile_behavior_slice.py tests/test_local_encounter_return.py`
- `PYTHONPATH=src pytest -q tests/test_campaign_danger_contact_slice.py tests/test_pygame_viewer_cli.py tests/test_pygame_viewer_runtime.py`
- `PYTHONPATH=src pytest -q tests/test_encounter_controller_smoke_slice.py`
- `PYTHONPATH=src pytest -q tests/test_pygame_viewer_cli.py -k local_contact_and_return_smoke_slice`
- `PYTHONPATH=src pytest -q tests/test_soak_bounds_slice.py tests/test_soak_audit_slice.py`
- `PYTHONPATH=src python - <<'PY' ... collect_soak_metrics headless/viewer 20000-tick comparison ... PY`
- `python -m py_compile src/hexcrawler/cli/pygame_viewer.py tests/test_pygame_viewer_runtime.py tests/test_pygame_viewer_layout.py tests/test_pygame_viewer_cli.py`
- `python play.py --headless`
- `python play.py --headless --runtime-profile experimental_world`
- `python play.py --headless --runtime-profile soak_audit`
- `python play.py`

## What changed in this commit
- Improved **Greybridge/home usability in `core_playable`**: Greybridge now renders as a centered high-contrast home marker with a persistent halo/label treatment, and the home panel can be opened from the home hex with either **Enter or E** (plus marker/context routes), keeping it the canonical minimal home interaction surface.
- Improved reward turn-in clarity on the same home panel/HUD surfaces: condition + proof/ration counts + recover/turn-in availability reasons remain explicit, with clear feedback for proof-token gain and ration gain.
- Added a **committed melee strike foundation** on the existing authoritative `attack_intent` seam: attack now snapshots target/cell at commit time, resolves after deterministic windup ticks, enforces a deterministic recovery cooldown gate, and emits clear hit/miss reasons (including moved-target misses) without introducing a second combat path.

## Core-playable clarity note (this pass)
- Greybridge is now a **minimal usable home node** in the default `core_playable` path via an explicit service panel (Recover, Turn in Proof, Leave) without requiring a full interior.
- Full town interior/editor workflows remain later scope, and combat work here is a committed-melee foundation pass only (not a broad redesign and no projectile/ranged path added).

## Runtime profile note (C1)
- Default play now uses `core_playable` (narrow playable-loop module set).
- Preserved second-order systems remain available via explicit opt-in: `--runtime-profile experimental_world`.
- Soak/audit composition remains explicit, bounded, and distinct via `--runtime-profile soak_audit`.

## Soak/Performance Diagnosis (this pass)
- **Main driver:** viewer/runtime overhead remains the dominant long-run slowdown source once caps are enforced, because viewer-coupled systems keep additional entities/events/encounter-control bookkeeping active; record containers are now bounded.
- **Simulation-side status:** headless run stayed bounded with no active entities/events growth (20k-tick diagnostic: `signals=256`, `tracks=256`, `spawn_descriptors=256`, `entities=0`, `pending_events=0`).
- **Viewer/runtime-side status:** 20k-tick diagnostic remained bounded on capped records but retained higher active-state load (`entities=258`, `event_trace=256`, `pending_events=6`, `pending_offers=1`), matching expected viewer+encounter module workload and confirming slowdown is now mostly runtime/viewer-coupled rather than unbounded container growth.
