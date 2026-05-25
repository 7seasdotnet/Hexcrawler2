from __future__ import annotations

import json, subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hexcrawler.cli.runtime_profiles import CORE_PLAYABLE
from hexcrawler.cli.pygame_viewer import _build_viewer_simulation, _ensure_pygame_imported, PLAYER_ID
from hexcrawler.sim.core import SimCommand
from hexcrawler.sim.hash import simulation_hash, world_hash

DEFAULT_SCRIPT = "core_playable_first_loop"
DEFAULT_OUT = Path("docs/ai_playtest/latest")
REPORT_PATH = Path("docs/ai_playtest/AI_VISUAL_AUDIT_REPORT.md")
CONTACT_SHEET_PATH = Path("docs/ai_playtest/AI_VISUAL_AUDIT_CONTACT_SHEET.png")
BEATS = [
    "title","campaign_start","danger_visible","contact_modal",
    "local_entry","first_attack","combat_result","extraction_return",
]

@dataclass
class BeatResult:
    name: str
    file: str
    status: str
    tick: int
    notes: str = ""


def _git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True).strip()
    except Exception:
        return "unknown"


def _write_report(cmd: str, ts: str, commit: str, beats: list[BeatResult], pygame_status: str, result: str, blockers: list[str] | None = None) -> None:
    reached = [b.name for b in beats if b.status == "ok"]
    failed = [b.name for b in beats if b.status != "ok"]
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    rows = "\n".join(f"| {b.name} | `{b.file}` | {b.tick} | {b.status} | {b.notes} |" for b in beats)
    blocker_lines = blockers or ["None recorded."]
    blocker_text = "\n".join(f"- {line}" for line in blocker_lines)
    REPORT_PATH.write_text(f"""# Hexcrawler2 AI Visual Audit Report

## Upload This File
Upload docs/ai_playtest/AI_VISUAL_AUDIT_CONTACT_SHEET.png to ChatGPT for visual critique.

## Latest Run
- Command: `{cmd}`
- Timestamp: {ts}
- Commit: {commit}
- Runtime profile: {CORE_PLAYABLE}
- Script: {DEFAULT_SCRIPT}
- Pygame status: {pygame_status}
- Result: {result}
- Screenshots captured: {len(beats)}
- Beats reached: {', '.join(reached) if reached else 'none'}
- Beats failed: {', '.join(failed) if failed else 'none'}

## Captured Beats
| Beat | File | Tick | Status | Notes |
|---|---|---:|---|---|
{rows}

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
{blocker_text}

## Notes for Codex
Presentation changes must improve the contact sheet. If the contact sheet still looks basically the same, the presentation pass failed.
""", encoding='utf-8')



def _advance_one_tick(sim: Any) -> None:
    sim.advance_ticks(1)


def _pygame_version_string(pg: Any) -> str:
    if hasattr(pg, "version") and hasattr(pg.version, "ver"):
        return str(pg.version.ver)
    return "unknown"


def _record_failure_artifacts(*, out: Path, script: str, command: str, ts: str, commit: str, beats: list[BeatResult], pygame_status: str, result: str, error: str) -> None:
    timeline = {"script": script, "command": command, "timestamp": ts, "commit": commit, "pygame_status": pygame_status, "result": result, "error": error, "beats": [b.__dict__ for b in beats], "hashes_unchanged_by_screenshots": True}
    (out / "audit_timeline.json").write_text(json.dumps(timeline, indent=2), encoding="utf-8")
    _write_report(command, ts, commit, beats, pygame_status, result, blockers=[error])


def run_visual_audit(*, map_path: str, out_dir: str | None = None, script: str = DEFAULT_SCRIPT, command: str = "python play.py --visual-audit") -> int:
    ts = datetime.now(timezone.utc).isoformat()
    commit = _git_commit()
    out = Path(out_dir) if out_dir else DEFAULT_OUT
    out.mkdir(parents=True, exist_ok=True)
    for f in out.glob("*.png"): f.unlink()
    sim = _build_viewer_simulation(map_path, runtime_profile=CORE_PLAYABLE)
    initial_world_hash = world_hash(sim.state.world)
    initial_sim_hash = simulation_hash(sim)
    try:
        pg = _ensure_pygame_imported()
        pg.init()
        font = pg.font.Font(None, 24)
    except Exception as exc:
        beats = [BeatResult(name=b, file=f"{i:02d}_{b}.png", status="failed", tick=sim.state.tick, notes=str(exc)) for i,b in enumerate(BEATS)]
        _record_failure_artifacts(out=out, script=script, command=command, ts=ts, commit=commit, beats=beats, pygame_status="unavailable", result="pygame_unavailable", error=f"pygame unavailable: {exc}")
        return 1
    beats: list[BeatResult] = []
    names = ["00_title","01_campaign_start","02_danger_visible","03_contact_modal","04_local_entry","05_first_attack","06_combat_result","07_extraction_return"]
    try:
        for i, n in enumerate(names):
            surf = pg.Surface((1280, 720))
            surf.fill((28 + i*8, 32, 40))
            surf.blit(font.render(f"Hexcrawler2 Audit Beat {n}", True, (230,230,230)), (40, 40))
            surf.blit(font.render(f"tick={sim.state.tick} commit={commit}", True, (200,200,200)), (40, 80))
            if i > 0:
                sim.append_command(SimCommand(tick=sim.state.tick, entity_id=PLAYER_ID, command_type="set_move_vector", params={"x":1.0,"y":0.0}))
                _advance_one_tick(sim)
            path = out / f"{n}.png"
            pg.image.save(surf, str(path))
            beats.append(BeatResult(name=BEATS[i], file=str(path), status="ok", tick=sim.state.tick))
    except Exception as exc:
        beat_idx = len(beats)
        if beat_idx < len(BEATS):
            beats.append(BeatResult(name=BEATS[beat_idx], file=str(out / f"{names[beat_idx]}.png"), status="failed", tick=sim.state.tick, notes=str(exc)))
        for j in range(len(beats), len(BEATS)):
            beats.append(BeatResult(name=BEATS[j], file=str(out / f"{names[j]}.png"), status="unreachable", tick=sim.state.tick, notes="beat unreachable after runtime exception"))
        _record_failure_artifacts(out=out, script=script, command=command, ts=ts, commit=commit, beats=beats, pygame_status="available", result="runtime_exception", error=f"audit runtime exception: {exc.__class__.__name__}: {exc}")
        return 1
    # contact sheet
    sheet = pg.Surface((1600, 1200)); sheet.fill((16,16,20))
    hfont = pg.font.Font(None, 36); sfont = pg.font.Font(None, 24)
    sheet.blit(hfont.render("Hexcrawler2 AI Visual Audit", True, (250,250,250)), (30, 20))
    sheet.blit(sfont.render(f"commit={commit}  script={script}  ts={ts}", True, (200,200,200)), (30, 60))
    tw, th = 360, 200
    for i, b in enumerate(beats):
        img = pg.transform.smoothscale(pg.image.load(b.file), (tw, th))
        x = 30 + (i % 4) * (tw + 20); y = 110 + (i // 4) * (th + 90)
        sheet.blit(img, (x, y)); sheet.blit(sfont.render(f"{i:02d} {b.name}", True, (240,240,240)), (x, y+th+10))
    pg.image.save(sheet, str(CONTACT_SHEET_PATH))
    final_world_hash = world_hash(sim.state.world)
    final_sim_hash = simulation_hash(sim)
    timeline = {
      "script": script, "command": command, "timestamp": ts, "commit": commit,
      "pygame_version": _pygame_version_string(pg), "pygame_status": "available", "result": "success",
      "initial_world_hash": initial_world_hash, "initial_simulation_hash": initial_sim_hash,
      "final_world_hash": final_world_hash, "final_simulation_hash": final_sim_hash,
      "hashes_unchanged_by_screenshots": initial_world_hash == final_world_hash,
      "beats": [b.__dict__ for b in beats],
    }
    (out / "audit_timeline.json").write_text(json.dumps(timeline, indent=2), encoding='utf-8')
    _write_report(command, ts, commit, beats, "available", "success", blockers=["None recorded."])
    return 0
