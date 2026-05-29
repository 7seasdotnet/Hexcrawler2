# Combat Cadence Gate 2 — Headless Cadence Transcript

Generated in the Codex container with `PYTHONPATH=src python ...` using the deterministic core-playable first patrol setup pattern from `tests/test_local_hostile_behavior_slice.py`.

Pygame was not imported and no viewer/contact-sheet rendering was performed for this artifact.

## Exact starter-fight tuning disclosed

- Global authoritative melee profile remains `default_melee`: `windup_ticks=2`, `impact_tick=2`, `recovery_ticks=5`, so `cooldown_until_tick = accepted_tick + 8` and READY resumes exactly at `cooldown_until_tick`.
- Starter hostile local behavior throttle changed only in `LocalHostileBehaviorModule`:
  - `LOCAL_CONTACT_TELEGRAPH_TICKS=3` ticks after adjacent contact before first hostile attack request.
  - `LOCAL_CONTACT_ATTACK_COOLDOWN_TICKS=14` ticks between hostile attack request attempts while contact remains continuous.
- First/core-playable patrol hostile spawn tuning changed only for the spawned starter encounter hostile:
  - `stats.faction_id="hostile"`.
  - `stats.role="starter_patrol_hostile"`.
  - `stats.starter_incoming_wound_severity_bonus=1`, making wounds inflicted **on that starter hostile** severity `2` instead of global default severity `1`.
- No global weapon profile, player wound severity, hostile accuracy, armor, body-part, stamina, ranged, spell, cover, or equipment-derived profile changes were made.

## Scenario

- Seed: `912`.
- Encounter: first hostile patrol handoff from campaign to local encounter.
- Hostile: `encounter_participant:evt-00000002:0`.
- Player: `scout`.
- Hostile was placed adjacent to the player at local contact start.
- Player LMB spam was simulated headlessly by issuing a player `attack_intent` every tick until the starter hostile was incapacitated. Only READY ticks were accepted.
- A single forced duplicate hostile `attack_intent` was injected during hostile WINDUP to demonstrate authoritative not-ready rejection. The normal hostile behavior module itself suppresses cooldown-period attack attempts before command emission.

## Cadence transcript

### Accepted attack ticks

| Actor | accepted_attack_tick list | impact_tick list | cooldown_until_tick list |
|---|---:|---:|---:|
| player `scout` | `[3, 11]` | `[5, 13]` | `[11, 19]` |
| hostile `encounter_participant:evt-00000002:0` | `[6]` | `[8]` | `[14]` |

### Rejected not-ready attempts

| Actor | rejected ticks | reason | feedback |
|---|---:|---|---|
| player `scout` | `[4, 5, 6, 7, 8, 9, 10, 12, 13]` | `not_ready` | `RECOVERING` |
| hostile `encounter_participant:evt-00000002:0` | `[7]` | `not_ready` | `RECOVERING` |

### Combat log outcomes

| tick | actor | source path | reason | applied | action_uid | accepted cadence evidence |
|---:|---|---|---|---|---|---|
| 3 | `scout` | `player_lmb` | `windup_started` | false | `3:0` | accepted at tick 3 |
| 5 | `scout` | `scheduled_impact` | `resolved` | true | `3:0` | yes: `3:0` accepted at tick 3 |
| 6 | `encounter_participant:evt-00000002:0` | `hostile_ai` | `windup_started` | false | `6:2` | accepted at tick 6 |
| 8 | `encounter_participant:evt-00000002:0` | `scheduled_impact` | `resolved` | true | `6:2` | yes: `6:2` accepted at tick 6 |
| 11 | `scout` | `player_lmb` | `windup_started` | false | `11:0` | accepted at tick 11 |
| 13 | `scout` | `scheduled_impact` | `resolved` | true | `11:0` | yes: `11:0` accepted at tick 11 |

## Final deterministic result

- Final simulation tick: `14`.
- Starter hostile wounds:
  - tick `5`: severity `2`, region `torso`, source `scout`.
  - tick `13`: severity `2`, region `torso`, source `scout`.
- Player wounds:
  - tick `8`: severity `1`, region `torso`, source `encounter_participant:evt-00000002:0`.
- Starter hostile final result: incapacitated at wound severity total `4` after exactly two accepted player attacks.
- Hostile final pressure in transcript: one accepted hostile attack, one player wound.

## Evidence invariants

- Every transcripted wound/miss/block outcome corresponds to preceding accepted cadence evidence by matching `action_uid`.
- Rejected player duplicate attempts emitted bounded non-combat command feedback only and did not create MISS/BLOCKED/WOUNDED combat-log rows.
- Rejected hostile duplicate attempt emitted bounded non-combat command feedback only and did not create MISS/BLOCKED/WOUNDED combat-log rows.
- The transcript contains no camera, screen, projection, render, pixel, zoom, interpolation, bbox, cursor, or presentation fields.
- No pygame runtime/contact-sheet verification was performed in this environment.
