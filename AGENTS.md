# Hexcrawler Engine — Codex Project Instructions (AGENTS.md)

## Mission
Build a lightweight, deterministic, modular Hexcrawl Simulation Engine with an integrated in-game editor, designed for OSR lethality, persistence, and systemic emergence. The engine must support “Hotline OSR syncretism” (real-time brutality + OSR consequences) where **information > reflexes**, enforced by tick-based **accounting** under the hood.

## Product Pillars (non-negotiable)
1) **Hexcrawl-first**: the hex grid is a native data structure and the world state is keyed to hex coordinates.
2) **Persistent world**: NPCs/factions/entities tick forward whether the player is present or not.
3) **Deterministic simulation**: seeded RNG; deterministic tick loop; stable replays of the same seed + inputs.
4) **OSR consequence**: no HP bloat, no rubber-banding, no level-scaling; lethality and scarcity are core.
5) **Diegetic information**: rumors, tracks, signs, NPC complaints, faction behavior. No quest markers.
6) **Wounds over HP**: “caveman-readable” wound model with strong functional consequences and persistent scars.
7) **Armor is thresholds**: penetration threshold negates certain vectors; tradeoffs (fatigue/noise/mobility); arcs.
8) **Editor is first-class**: AoE2-style in-game world editor, fun enough to be a product on its own.
9) **Multiplayer-safe architecture**: do not implement multiplayer now, but do not lock it out (no global time accel assumptions in core logic; clean sim/render/input separation; server-authoritative feasibility).

## Core Gameplay Loop (engine must support)
Desire (wealth/progression) → acquire information (rumor/track/threat) → prepare (gear/supplies/hirelings) → travel (continuous clock + scheduled checks) → discover → commit → survive or die → return & recover → world state shifts → new information emerges.

## Simulation Timing (Accounting Layer)
- A fixed simulation tick (e.g., 100ms) drives authoritative state updates.
- Scheduled checks run on defined intervals:
  - encounter checks
  - resource/supply ticks
  - fatigue/exhaustion ticks
  - AI reevaluation ticks
- Seeded RNG is consumed only inside the simulation layer in a controlled, testable way.

## Rumors/Tracks/Threats System
- Rumors are generated from structured world events using typed templates; they are *projections* of world facts, not freeform story.
- Propagation hop target: **3–5**. Beyond hop cap, downgrade into coarse “regional unrest” signals.
- Rumors carry: confidence, TTL/decay, source, linked evidence types (tracks/burns/bodies), and optional distortion.
- Tracks are world objects placed by events (raids, patrols, travel) and can be discovered/validated.

## Wounds System (Table-Driven)
- Each creature defines body parts (head/torso/limbs etc.), coverage, and a wound table.
- Wounds have: region, type, severity, effects (mobility/dexterity/bleed/shock), treatment, recovery, complications, scars/boons (optional).
- Avoid clinical micromanagement (no insulin-level simulation); keep readable and brutal.

## Combat (“Hotline OSR syncretism”)
- Real-time tactical combat with commitment windows; lethality is high.
- “information > reflexes”: scouting, positioning, preparation dominate outcomes.
- Optional targeted attacks: default torso on click; optional fast overlay for aiming at body parts.
- Blocking/defending is a stance with tradeoffs (slows movement, limits actions, improves defense).

## Armor Model (Thresholds + Arcs)
- Compute penetration_value; compare to armor threshold by damage type and arc (front/side/rear).
- If below threshold: no penetration; still allow blunt trauma/stagger/fatigue shock/armor degradation.
- If above threshold: penetration/bleed/organ risk.
- Keep bounded uncertainty (angle class, impact variance) to avoid deterministic exploits.

## Editor Requirements (MVP)
Must exist inside the game:
- hex terrain painter (brush/fill)
- place sites (town/ruin/dungeon entrance)
- place spawners/patrol routes
- edit encounter tables and rumor templates
- edit weapons/armor thresholds/wound tables/factions (at least basic forms)
- “simulate N days” preview mode
Goal: content expansion becomes data entry + balance, not new code.

## Architecture Requirements
- Separate modules: simulation core, rules modules, content data layer, rendering/UI layer, editor layer.
- Prefer ECS or clean component architecture if appropriate; avoid monolith.
- Every system must be testable headless (no UI required).
- Keep saves deterministic and versioned (migrations supported). Human-readable is optional; schema-validation is required.

## Output Discipline (how you work)
When asked to implement:
1) Propose a short plan and file-level change list.
2) Implement in small, reviewable commits/steps.
3) Add automated tests for deterministic simulation and key systems.
4) Provide a short “how to run” and “how to verify” checklist.

## MVP Acceptance Tests (must pass)
- Determinism: same seed + same inputs → identical results for N ticks.
- World persistence: entities act over time; removing player does not stop simulation.
- Rumor pipeline: world event → rumor created → propagates (<= hop cap) → decays.
- Tracks: events leave tracks; player can discover and validate.
- Wounds: damage yields wounds with functional consequences; recovery/treatment works.
- Armor thresholds: low-penetration attacks fail to penetrate; still cause secondary effects.
- Editor: can paint a small map, place a dungeon, define an encounter table, and play it.

## Scope Guardrails
- Do NOT build networking in v1.
- Do NOT build grand strategy or “becoming king” systems in v1.
- Keep graphics minimal early; prioritize simulation + editor + pipelines.
- Avoid feature creep not serving the core loop.
