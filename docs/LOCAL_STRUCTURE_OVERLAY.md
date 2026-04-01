# LOCAL_STRUCTURE_OVERLAY — Greybridge Local Structure Authoring Bridge (Part 1)

## Scope and role boundary
- Space role coverage in this pass: **local role only** (Greybridge safe-hub local space).
- This pass is intentionally bounded to the active **Playable Core Loop Slice**.
- This pass is **not** a combat redesign, full town/interior system, editor painting pass, nested-grid implementation, or isometric renderer pass.

## A) Current pass scope (what this pass implemented)
- Space role coverage in this pass: **local role only** (`safe_hub:greybridge`).
- Added a schema/content-backed local structure primitive saved in local space topology params as:
  - `structure_id`, `label`, `room_id`
  - `bounds` (`x`, `y`, `width`, `height`)
  - `openings[]` (`opening_id`, `kind`, `cell`)
  - optional `tags[]`
- Runtime blocked cells remain in use for movement/collision, but they are now **derived compile output** from structure primitives.

### Why it was acceptable as a playable-loop patch
- Very low implementation risk and very fast to ship.
- Deterministic and bounded behavior for collision/pathing.
- Good enough to keep loop momentum while stabilizing patrol/contact/return/recover flows.

### Why it is dangerous as a permanent substrate
- Authoring truth becomes implicit occupancy blobs instead of explicit structure semantics.
- Walls/openings/doors/gates are not first-class authored objects.
- Weak path to future paint-based authoring, finer local detail, and projection experiments.
- Risks hard-locking local authoring to chunky occupancy patches.

## B) Authoring primitive and compile contract
Canonical authored truth for this bridge pass:
1. `structure_primitives[]` on the Greybridge local-space topology payload.
2. Deterministic compile step:
   - input: normalized structure primitives,
   - output: `blocked_cells`, `wall_cells`, `wall_segments`, `opening_rows`, `opening_cells`.
3. Collision query uses derived `blocked_cells` only as runtime substrate.
4. Local rendering draws structure boundaries from `wall_segments` + `opening_rows` (not from blocked-cell fill blobs).

### Why this is the right bounded step
- Preserves current loop behavior/performance.
- Makes the authored truth semantic and future-safe.
- Avoids framework bloat while proving the anti-lock-in direction with one Greybridge area.

## C) Minimal in-game authoring workflow (bridge proof)
This pass adds a small in-game authoring seam through authoritative command/event mutation:
- create one rectangular structure (`create_rect`)
- add/move one opening (`move_opening` / `upsert_opening`)
- remove one opening (`remove_opening`)
- delete one structure (`delete_structure`)
- persist through existing save/load path (hash-covered world topology payload)

Viewer hotkeys for the bounded proof in Greybridge local hub:
- `B` create/update demo rectangle at player cell.
- `O` move demo opening to player cell.
- `P` remove demo opening.
- `Delete` remove demo structure.

## D) Zoom / nesting / projection path preservation
This overlay keeps the path open by separating:
- **authoring semantics** (structure/opening/room/gate),
- **runtime traversal substrate** (current coarse lattice),
- **presentation** (top-down now; future projection experiments later).

Because authored truth is no longer “just blocked cells,” later passes can:
- introduce finer collision refinement per structure,
- add nested/local-detail spaces,
- test isometric projection,
without rewriting the canonical meaning of buildings and openings.

## E) Greybridge conversion proof in this pass
- Gatehouse/Watch Hall/Inn shells are represented as structure primitives.
- At least one meaningful area (Gatehouse) is now visibly rendered from authored wall/opening primitives (segments + portals), while collision remains derived and deterministic.
- This is a **bounded bridge proof**, not full local-town/interior completion.

### Do **not** do now
- No full town/interior system.
- No editor painting UI implementation.
- No nested-grid/zoom implementation.
- No isometric renderer implementation.
- No combat logic redesign.

### Next two bounded follow-up passes
1. **Follow-up pass 1 (bounded substrate pass):**
   - Extend overlay schema to explicit wall segments/portals (beyond bounds-derived shells).
   - Add deterministic compile diagnostics + validation errors for malformed overlays.
2. **Follow-up pass 2 (bounded authoring bridge):**
   - Add minimal read-only overlay inspection + editor-facing data entry hooks (no full painter yet).
   - Add one more Greybridge or local-encounter-space overlay-authored building proof.

---
This pass is a **single Greybridge anti-lock-in proof**, not a global local-building substrate completion.
