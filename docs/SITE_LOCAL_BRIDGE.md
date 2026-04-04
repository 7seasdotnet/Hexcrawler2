# SITE_LOCAL_BRIDGE — Authored Site Activation Bridge (bounded pass)

## Purpose
Make authored campaign towns and dungeon entrances first-class enterable sites instead of dead markers.

## Space roles
- Campaign role: authored site records, right-click placement/edit/delete, and entry command emission.
- Local role: linked local proof spaces used as immediate authoring/entry destinations.

## Linkage contract
- Authored site linkage is explicit and serialized through `SiteRecord.entrance`:
  - `target_space_id`
  - `spawn`
- Deterministic linked local id: `local_site:{site_id}`.
- This keeps save/load and world hash behavior stable and inspectable.

## Creation timing
- Linked local spaces are created eagerly when authored town/dungeon sites are created.
- Rationale: deterministic lifecycle, fewer edge cases than lazy first-entry allocation.

## Delete semantics
- Campaign authored site delete uses cascading delete for linked authored local space.
- This pass intentionally avoids orphan lifecycle management.

## Why this is bounded
- Adds only tiny proof spaces (town proof hub / dungeon proof chamber).
- Does not implement population authoring, procedural generation, or full editor framework.
- Unblocks the next bounded pass: local spawner/population authoring inside linked spaces.
