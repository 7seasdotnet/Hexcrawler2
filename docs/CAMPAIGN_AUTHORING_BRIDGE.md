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

## Canonical in-game workflow (bounded proof)
Authoring commands are routed only through authoritative command/event seams using `campaign_author_intent`:
- create/update town site
- create/update dungeon entrance site
- move site anchor
- delete site
- create/update patrol primitive
- move patrol spawn
- move patrol route anchor
- delete patrol

Campaign authoring UX is now **right-click/context-menu first** in campaign space:
- Right-click empty campaign space:
  - `Place Town Here`
  - `Place Dungeon Entrance Here`
  - `Place Patrol Here`
- Right-click authored campaign object (site/patrol):
  - `Move`
  - `Delete`
  - `Edit Path` (patrol only; bounded anchor add/delete)
- Move is bounded:
  - choose `Move`,
  - next right-click destination commits move through authoritative intent,
  - `Esc` cancels pending move safely.

Hotkeys remain available only as hidden/debug fallback and are **not** canonical UX.

## Canonical control hierarchy + uniform semantics rule (campaign role)
- Right-click/context-menu placement/edit/delete is the canonical player-facing campaign spatial authoring UX.
- Hotkeys are fallback/debug only unless explicitly documented as primary for a specific workflow.
- Authored campaign objects must behave uniformly regardless of creation path:
  - seeded defaults,
  - hotkey/demo-created objects,
  - right-click/context-menu-created objects.
- Seeded defaults are not special-cased from move/delete semantics in authoring mode.
- Patrol path editing is bounded in this pass:
  - right-click patrol -> `Edit Path`,
  - right-click campaign space -> `Add route anchor here`,
  - right-click existing anchor -> `Move route anchor #N here` or `Delete route anchor #N`,
  - `Esc` finishes path editing.

### Patrol placement/path workflow clarification (campaign role)
- After `Place Patrol Here`, viewer now automatically enters **patrol path edit mode** for the placed patrol.
- Spawn position is the patrol origin.
- Route anchors are authored via right-click context actions:
  - add anchor at clicked world position,
  - move clicked anchor to clicked world position,
  - delete clicked anchor.
- Exit path edit with `Esc` or context `Finish path edit`.

### Patrol movement semantics (campaign role, continuous plane)
- Patrol movement consumes authored `world.campaign_patrols[patrol_id].route_anchors` as authoritative route data.
- Runtime patrol entity truth is synchronized from the same authored patrol record (no dead split record).
- Movement remains continuous on the campaign plane (not hex-step cadence).
- **Path requirement is explicit:** patrol requires at least one route anchor to move.
  - `route_anchors == []` => patrol idles and UI surfaces a `path needed` message.
  - one or more anchors => patrol loops through anchors continuously.

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
