# STALE FOR COMBAT CADENCE GATE 2 MELEE-READABILITY ACCEPTANCE

This report/contact-sheet bundle was **not regenerated** after the accepted Combat Cadence Gate 2 melee-readability code amendment referenced as commit `5072447` (current branch equivalent: `a340e24`). It must not be used as final acceptance evidence for default_melee readability. Runtime/manual pygame verification remains required before merge acceptance.

Required pygame-enabled reruns before claiming visual acceptance:
- `python play.py`
- `python play.py --visual-audit`
- `python play.py --perf-sentinel --profile-on-lag --lag-frame-ms 50`

Pending visual questions:
1. Does `default_melee` now read as a clean arc/crescent?
2. Does the arc originate from attacker and travel toward/into hostile?
3. Is the orange/yellow impact circle actually gone or reduced enough?
4. Is the hostile marker visible above the cue?
5. Is the facing/front indicator legible?
6. Do F1/F10/zoom/pan/recenter still work?

Do not claim `Known Blockers: None recorded` for this PR until those runs regenerate fresh artifacts.

---

# Hexcrawler2 AI Visual Audit Report

## Upload This File
Upload docs/ai_playtest/AI_VISUAL_AUDIT_CONTACT_SHEET.png to ChatGPT for visual critique.

## Latest Run
- Command: `python play.py --visual-audit --script core_playable_first_loop --out docs/ai_playtest/latest`
- Timestamp: 2026-05-25T13:27:44.304393+00:00
- Commit: 3127cfe
- Runtime profile: core_playable
- Script: core_playable_first_loop
- Pygame status: unavailable
- Result: pygame_unavailable
- Screenshots captured: 8
- Beats reached: none
- Beats failed: title, campaign_start, danger_visible, contact_modal, local_entry, first_attack, combat_result, extraction_return

## Captured Beats
| Beat | File | Tick | Status | Notes |
|---|---|---:|---|---|
| title | `00_title.png` | 0 | failed | No module named 'pygame' |
| campaign_start | `01_campaign_start.png` | 0 | failed | No module named 'pygame' |
| danger_visible | `02_danger_visible.png` | 0 | failed | No module named 'pygame' |
| contact_modal | `03_contact_modal.png` | 0 | failed | No module named 'pygame' |
| local_entry | `04_local_entry.png` | 0 | failed | No module named 'pygame' |
| first_attack | `05_first_attack.png` | 0 | failed | No module named 'pygame' |
| combat_result | `06_combat_result.png` | 0 | failed | No module named 'pygame' |
| extraction_return | `07_extraction_return.png` | 0 | failed | No module named 'pygame' |

## Manual Visual Checklist
- Does the first screen look meaningfully different?
- Is the player immediately visible?
- Are Greybridge and Old Stair visually distinct?
- Is the patrol/danger source visually obvious?
- Does CONTACT feel like a game event?
- Does the local encounter look different from campaign travel?
- Can the player distinguish self, hostile, and extraction/return?
- Does combat have visible impact?
- Is the HUD compact and player-facing?
- What remains ugliest?

## Known Blockers
- pygame unavailable: No module named 'pygame'

## Notes for Codex
Presentation changes must improve the contact sheet. If the contact sheet still looks basically the same, the presentation pass failed.
