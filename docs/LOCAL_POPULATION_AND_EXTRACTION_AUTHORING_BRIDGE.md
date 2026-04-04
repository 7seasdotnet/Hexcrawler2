# LOCAL_POPULATION_AND_EXTRACTION_AUTHORING_BRIDGE (bounded pass)

## Scope and space roles
- Space role coverage in this pass: **local role** authored dungeon proof spaces linked from campaign authored dungeon-entrance sites.
- This pass is a bounded authoring bridge for the current playable slice.
- Out of scope: full dungeon systems, encounter-table overhaul, ecology/AI expansion, combat redesign, nested grids, isometric pass, editor framework rewrite.

## Authored local hostile/spawner primitive
Persistent authored truth now includes `SpaceState.local_hostile_spawners[]` entries:
- `spawner_id` (stable id)
- `coord` (`x`,`y` cell anchor)
- `template_id` (current bounded default `encounter_hostile_v1`)
- `count`
- `enabled`
- optional `label`
- optional `tags[]`

This primitive is save/load serialized and hash-covered.
Runtime hostile entities can be materialized from this primitive; the primitive remains canonical authored truth.

## Authored local entry/extraction primitive
Persistent authored truth now includes `SpaceState.local_transition_points[]` entries:
- `point_id` (stable id)
- `coord` (`x`,`y` cell anchor)
- `point_kind` (`entry_anchor` | `extraction_exit` | `return_to_origin_exit`)
- `enabled`
- optional `label`
- optional `tags[]`

These markers are explicit, editable, persistent, and hash-covered.

## Canonical right-click workflow (local authored dungeon)
- Right-click empty local dungeon cell:
  - `Place Hostile Here`
  - `Place Entry Point Here`
  - `Place Exit / Extraction Here`
  - `Place Return-to-Origin Exit Here`
- Right-click authored local target:
  - hostile marker: move/delete
  - transition marker: move/delete/use

All mutation remains authoritative command-driven via `local_dungeon_author_intent`; viewer stays read-only for state mutation.

## Return-to-origin semantics (explicit choice)
This pass chooses deterministic return semantics:
- **Return target:** linked campaign dungeon entrance site anchor (`SiteRecord.location.campaign_anchor`) for the authored site that owns this local space.
- `use_transition_point` accepts only extraction/return point kinds and transitions to campaign origin anchor.

### Default markers on dungeon creation
- Created dungeon local spaces get an eager default `entry_anchor` marker.
- Created dungeon local spaces get an eager default `return_to_origin_exit` marker.
- Users may move/delete/recreate markers through right-click authoring.

## Bounded proof status
This pass proves one bounded authored dungeon bridge:
- enter authored dungeon local space,
- author hostile spawner(s),
- author/move/delete entry/extraction markers,
- extract/return deterministically,
- persist through save/load.

This does **not** claim global dungeon population tooling completion.
