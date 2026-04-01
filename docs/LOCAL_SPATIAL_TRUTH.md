# LOCAL_SPATIAL_TRUTH — Anti-Lock-In Direction Pass (Playable Core Loop Slice)

## Scope and intent
This memo is a bounded direction-setting pass for the current **Playable Core Loop Slice**. It prevents accidental spatial lock-in while preserving delivery focus.

This pass is **not**:
- a combat redesign,
- a town/editor expansion,
- a full building-system refactor,
- a nested-grid implementation,
- an isometric renderer implementation,
- an architecture reset.

---

## A) Heading / facing separation (authoritative distinction)

### 1) Campaign heading (campaign role)
- Applies to: **campaign** spaces.
- Meaning: directional motion signal on the authoritative continuous campaign plane.
- Source: continuous position/time deltas (movement on `(x, y)` world coordinates).
- Contract: campaign heading must not be derived from hex adjacency cadence.

### 2) Local tactical facing (local role)
- Applies to: **local** spaces (and tactical semantics in general).
- Meaning: simulation/combat-facing orientation token used for admissibility/arcs/resolution.
- Source: authoritative simulation entity state.
- Contract: may be discrete by topology rules; deterministic and serialized/hash-covered when authoritative.

### 3) Render-heading / display heading (viewer)
- Applies to: **viewer presentation** in campaign/local render layers.
- Meaning: how a marker/wedge/arrow is visually oriented for readability.
- Source: viewer-only interpolation and display rules.
- Contract: may be continuous/interpolated even when authoritative tactical facing is discrete.

### Required anti-lock-in rule
These are **not the same concept**. Campaign/local render presentation must not look hex-snapped simply because hexes exist for indexing/content organization.

---

## B) Building / collision substrate direction

### Current temporary Greybridge truth
Current Greybridge local buildings are represented primarily by chunky blocked-cell occupancy + a small set of explicit door cells.

### Why this is acceptable now
- It ships immediate playable-loop traversal and gatehouse/hub readability quickly.
- It is deterministic, bounded, and easy to inspect.
- It avoids broad refactor risk during loop stabilization.

### Why this is dangerous as a permanent substrate
- It hard-binds building authoring to coarse occupancy and weakly expresses walls/openings.
- It poorly supports thin walls, interior partitions, offset entrances, and richer collision geometry.
- It risks silent lock-in against future zoom/refinement, projection flexibility, and richer local encounter layouts.

### Recommended future-safe primitive direction
Adopt a **coarse movement lattice + higher-fidelity structure overlay**:
1. Keep a coarse local movement grid/lattice for deterministic occupancy/navigation constraints.
2. Represent structures using explicit wall/door/opening segments (or equivalent room/portal boundary primitives) over that lattice.
3. Resolve movement/collision against lattice truth plus deterministic structure overlay checks.

Why this direction:
- Preserves current deterministic local traversal performance/boundedness.
- Supports finer building geometry without immediately requiring full nested-grid machinery.
- Keeps a path to later zoom/refinement and alternative projections without rewriting simulation truth.

---

## C) Zoom / nested-local policy

### Decision now
We do **not** need true nested grids/zoom implementation in this pass.

### What we do need now
Preserve a path so future nested refinement can be added without invalidating current local data.

### Exact anti-lock-in rule
No new local feature may assume "one blocked cell == final building truth." Local-space contracts must treat coarse occupancy as temporary traversal substrate and allow optional higher-fidelity structural overlays later.

---

## D) Isometric timing decision

### Decision now
Do **not** pivot to isometric local rendering now. Stay top-down while improving local readability and spatial truth clarity.

### Why
- Current risk is semantic lock-in, not projection deficiency.
- Premature projection pivot adds high scope/cost while weakly addressing substrate correctness.
- Architecture already requires projection independence; we should validate that with bounded proofs first.

### Trigger criteria for a later isometric prototype
Run a bounded isometric prototype only if top-down remains insufficient after targeted readability passes and at least one of these holds:
1. Repeated playtests show persistent local readability failures (occlusion, ingress/egress interpretation, target/facing legibility) not solved by bounded top-down UI/render improvements.
2. Structure-overlay prototype still needs projection-specific depth cues that top-down cannot communicate clearly.
3. We can run the prototype without changing simulation hashes/contracts and without coupling combat semantics to projection.

---

## Clear recommendation

### Do now
1. Lock heading/facing/render-heading separation as explicit architecture + recurring-bug guidance.
2. Keep Greybridge blocked cells as temporary loop patch only.
3. Prefer the future-safe direction: coarse movement lattice + explicit structure overlay primitives.
4. Keep viewer heading presentation decoupled from hex-axial appearance in campaign rendering.

### Do not do now
- Do not harden blocked-cell building occupancy into final building authoring substrate.
- Do not implement full nested-grid/zoom.
- Do not pivot to isometric renderer.
- Do not modify combat semantics in this pass.

### Next two bounded follow-up passes
1. **Follow-up Pass 1 (bounded, substrate-safe):**
   - Introduce local structure overlay data contract (walls/doors/openings) with no broad content rewrite.
   - Add deterministic collision query seam that can read overlay + coarse lattice.
2. **Follow-up Pass 2 (bounded, presentation-safe):**
   - Local readability pass for top-down (contrast, outlines, doorway clarity, facing readability).
   - Add acceptance criteria/playtest rubric; only then evaluate need for an isometric prototype.
