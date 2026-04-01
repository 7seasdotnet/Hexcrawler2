# LOCAL_STRUCTURE_OVERLAY — Greybridge Bounded Structure-Overlay Proof

## Scope and role boundary
- Space role coverage in this pass: **local role only** (Greybridge safe-hub local space).
- This pass is intentionally bounded to the active **Playable Core Loop Slice**.
- This pass is **not** a combat redesign, full town/interior system, editor painting pass, nested-grid implementation, or isometric renderer pass.

## A) Current temporary truth
### What exists now (before this proof)
Greybridge local hub building collision/readability was represented mostly as a coarse blocked-cell shell plus a hand-maintained set of door/opening cells. This shipped the loop quickly (enter hub, move around, turn-in/recover, exit).

### Why it was acceptable as a playable-loop patch
- Very low implementation risk and very fast to ship.
- Deterministic and bounded behavior for collision/pathing.
- Good enough to keep loop momentum while stabilizing patrol/contact/return/recover flows.

### Why it is dangerous as a permanent substrate
- Authoring truth becomes implicit occupancy blobs instead of explicit structure semantics.
- Walls/openings/doors/gates are not first-class authored objects.
- Weak path to future paint-based authoring, finer local detail, and projection experiments.
- Risks hard-locking local authoring to chunky occupancy patches.

## B) Recommended near-term building substrate
### Recommended direction (chosen)
Use a **movement lattice + structure overlay** contract:
1. Keep the existing deterministic square-grid movement lattice for now.
2. Author local structures in overlay source data containing:
   - structure bounds,
   - opening definitions,
   - opening kind semantics (`door`, `opening`, `gate_portal`),
   - room/building identifiers.
3. Deterministically compile overlay data to runtime movement gating (`blocked_cells`) for current movement code.
4. Render from overlay-derived wall/opening truth, not ad hoc viewer-only blocked-cell doodles.

### Why this is the right bounded step
- Preserves current loop behavior/performance.
- Makes the authored truth semantic and future-safe.
- Avoids framework bloat while proving the anti-lock-in direction with one Greybridge area.

## C) Authoring path (future editor compatibility)
Future building painting should target **structure-overlay primitives**, not raw blocked-cell lists.

Exact primitive to paint/edit later:
- `structure_id`
- `room_id` / label
- `bounds` (coarse for now)
- `openings[]` where each opening has:
  - `opening_id`
  - `kind` (`door`, `opening`, `gate_portal`, later extensible)
  - `cell`

Current runtime can keep compiling this authored truth into blocked cells until finer collision layers are added.

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

## E) Recommendation
### Do now (this proof)
- Keep loop-stable local movement lattice.
- Make overlay source data the authored truth for one Greybridge proof area (including gate semantics).
- Derive collision and rendering from that overlay.

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
