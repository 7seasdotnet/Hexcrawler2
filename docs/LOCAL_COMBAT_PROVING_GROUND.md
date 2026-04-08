# LOCAL_COMBAT_PROVING_GROUND (bounded playable-slice pass)

## Lock-out review
- **Lock-out constraints reviewed: OK**

## Scope and space roles
- Space roles in this pass:
  - **campaign role**: deterministic entry into authored dungeon site (`demo_dungeon_entrance`).
  - **local role**: bounded proving-ground melee readability inside linked local space (`local_site:demo_dungeon_entrance`).
- In scope:
  - one authored combat lab,
  - bounded top-down melee readability cues,
  - no combat architecture rewrite.
- Out of scope:
  - isometric renderer pivot,
  - nested-grid/zoom implementation,
  - new combat mechanics (ranged/stealth/morale/AI overhaul),
  - full dungeon framework.

## Purpose
Provide a **repeatable authored local combat lab** that can answer one narrow question:

> Is top-down local melee becoming readable enough to continue iterating, or does it still fail core readability gates badly enough to justify later projection analysis?

## Proving-ground authored setup
The proving ground is seeded through existing authored truths and seams (no parallel harness):
- Site: `demo_dungeon_entrance` links to `local_site:demo_dungeon_entrance`.
- Layout: two small authored rooms with one doorway choke.
  - entry room + combat room,
  - one narrow transition doorway/opening between rooms.
- Population: one authored hostile spawner (`pg_hostile_a`, count 1).
- Transition points: entry anchor + extraction/return points.

All data is serialized/hash-covered and save/load stable through existing world/save contracts.

## Readability criteria for this pass
Manual checks are intended to be judgeable in a short run:
1. Can the player tell when enemy attack is about to happen?
2. Can the player tell when enemy is punishable/recovering?
3. Can the player tell why attacks hit/miss/fail?
4. Are reactions legible enough for decision-making?
5. Does local melee feel less like raw walk-and-spam?

## What this pass changed (bounded)
1. **Authored proving ground seeded in canonical playable map** using linked local-site primitives.
2. **On-world local structure rendering extended** from Greybridge-only to authored local square spaces with structure primitives.
3. **On-world melee readability cues (viewer-only):**
   - hostile ring colors by recent strike phase (telegraph / active / recovery),
   - player attack readiness ring (ready vs recovering),
   - existing hit flash retained for impacts.

## What this pass did not attempt
- No new authoritative combat state model.
- No attack semantics rewrite.
- No camera/projection migration.
- No full UX/editor framework expansion.

## Current bounded verdict
- **Provisional verdict:** top-down readability is improving enough to continue bounded iteration for now.
- Reason: in a controlled authored room/choke setup, telegraph/recovery windows and readiness states are visible on-world without adding new mechanics.
- This is **not** a claim that melee is solved.
- If future passes still show ambiguity under pressure (multi-hostile density, occlusion, clutter), that should trigger a focused projection-analysis discussion with concrete failure cases.
