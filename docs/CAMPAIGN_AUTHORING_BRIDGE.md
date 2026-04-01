# CAMPAIGN_AUTHORING_BRIDGE — Minimal Authoring Spine Part 2A

## Scope and role boundary
- Space role coverage: **campaign role only** (`overworld` continuous campaign plane).
- This pass is a bounded authoring bridge for the active playable core loop.
- This pass is **not** dungeon enemy/population authoring, full editor framework, map painting, zoom/nested-grid, isometric rendering, or combat redesign.

## Authored campaign primitives introduced

### 1) Campaign sites (authoring truth)
Campaign sites remain authored as persistent `world.sites[site_id]` records with:
- `site_id`
- `site_type` (authoring-facing `site_kind` accepted in this pass: `town`, `dungeon_entrance`, `safe_home`)
- campaign location payload containing:
  - `space_id=overworld`
  - derived `coord` (hex index derived from continuous position)
  - explicit `campaign_anchor` continuous position (`x`, `y`)
- optional label/name and tags.

### 2) Campaign patrol primitive (new)
Persistent `world.campaign_patrols[patrol_id]` records now hold authored patrol truth:
- `patrol_id`
- `template_id`
- `space_id`
- `spawn_position` (`x`, `y`)
- `route_anchors[]` (`x`, `y`)
- optional `label`, `tags`.

Runtime patrol entities are still compiled/instantiated from these primitives for current playable behavior.

## Minimal in-game workflow (bounded proof)
Authoring commands are routed only through authoritative command/event seams using `campaign_author_intent`:
- create/update town site
- create/update dungeon entrance site
- move site anchor
- delete site
- create/update patrol primitive
- move patrol spawn
- move patrol route anchor
- delete patrol

Viewer hotkeys provide a minimal proof workflow (non-polished):
- `B` (campaign): create/update demo town at player anchor
- `O` (campaign): create/update demo dungeon entrance at player anchor
- `P` (campaign): create/update demo patrol at player anchor
- `M` (campaign): move demo patrol anchor 0 to player anchor
- `Delete` (campaign): delete demo authored town + dungeon + patrol

## Why this is the minimal next step
- Removes campaign site/patrol iteration bottleneck without attempting full editor architecture.
- Keeps viewer read-only with respect to mutation (viewer issues intents only).
- Keeps save/load deterministic and hash-covered because authored truth is serialized in world payload.
- Keeps core playable loop intact while making campaign content editable without hand-editing code.

## Explicitly out of scope in this pass
- dungeon population/enemy authoring
- full editor UX/framework
- map painting workflow
- nested-grid/zoom implementation
- isometric renderer changes
- combat architecture redesign
