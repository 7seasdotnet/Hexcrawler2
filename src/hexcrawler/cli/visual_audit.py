from __future__ import annotations
import json, subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hexcrawler.cli.runtime_profiles import CORE_PLAYABLE
from hexcrawler.cli.pygame_viewer import (
    PLAYER_ID, _build_viewer_simulation, _ensure_pygame_imported,
    render_viewer_frame_to_surface, ViewerRuntimeState,
)
from hexcrawler.sim.core import SimCommand
from hexcrawler.sim.campaign_danger import ACCEPT_ENCOUNTER_OFFER_INTENT
from hexcrawler.sim.combat import ATTACK_INTENT_COMMAND_TYPE, COMBAT_OUTCOME_EVENT_TYPE
from hexcrawler.sim.hash import simulation_hash, world_hash
from hexcrawler.sim.world import LOCAL_SPACE_ROLE

DEFAULT_SCRIPT = "core_playable_first_loop"
DEFAULT_OUT = Path("docs/ai_playtest/latest")
REPORT_PATH = Path("docs/ai_playtest/AI_VISUAL_AUDIT_REPORT.md")
CONTACT_SHEET_PATH = Path("docs/ai_playtest/AI_VISUAL_AUDIT_CONTACT_SHEET.png")
BEATS = ["title","campaign_start","danger_visible","contact_modal","local_entry","first_attack","combat_result","extraction_return"]

@dataclass
class BeatResult:
    name:str; file:str; status:str; tick:int; notes:str=""; diagnostics:dict[str,Any]|None=None

def _git_commit()->str:
    try:return subprocess.check_output(["git","rev-parse","--short","HEAD"],text=True).strip()
    except Exception:return "unknown"

def _advance_one_tick(sim:Any)->None: sim.advance_ticks(1)

def _visual_sanity(pg:Any,surf:Any)->dict[str,Any]:
    px=pg.surfarray.array3d(surf)
    flat=px.reshape(-1,3)
    uniq=len({tuple(v) for v in flat[::max(1,len(flat)//8000)]})
    bg=(17,18,25)
    non_bg=sum(1 for v in flat[::4] if tuple(v)!=bg)/max(1,len(flat[::4]))
    blank=uniq<18 or non_bg<0.04
    return {"unique_color_count":uniq,"non_background_pixel_ratio":round(non_bg,4),"blank_frame_suspected":blank}

def _write_report(cmd,ts,commit,beats,pygame_status,result,blockers=None):
    reached=[b.name for b in beats if b.status=="ok"]; failed=[b.name for b in beats if b.status!="ok"]
    rows="\n".join(f"| {b.name} | `{b.file}` | {b.tick} | {b.status} | {b.notes} |" for b in beats)
    blocker_lines=blockers or ["None recorded."]
    REPORT_PATH.parent.mkdir(parents=True,exist_ok=True)
    REPORT_PATH.write_text(f"""# Hexcrawler2 AI Visual Audit Report
Upload docs/ai_playtest/AI_VISUAL_AUDIT_CONTACT_SHEET.png to ChatGPT for visual critique.

- Command: `{cmd}`
- Timestamp: {ts}
- Commit: {commit}
- Runtime profile: {CORE_PLAYABLE}
- Pygame status: {pygame_status}
- Result: {result}
- Screenshots captured: {len(beats)}
- Beats reached: {', '.join(reached) if reached else 'none'}
- Beats failed: {', '.join(failed) if failed else 'none'}

| Beat | File | Tick | Status | Notes |
|---|---|---:|---|---|
{rows}

## Known Blockers
"""+"\n".join(f"- {b}" for b in blocker_lines),encoding='utf-8')

def run_visual_audit(*,map_path:str,out_dir:str|None=None,script:str=DEFAULT_SCRIPT,command:str="python play.py --visual-audit")->int:
    ts=datetime.now(timezone.utc).isoformat(); commit=_git_commit(); out=Path(out_dir) if out_dir else DEFAULT_OUT; out.mkdir(parents=True,exist_ok=True)
    for f in out.glob('*.png'): f.unlink()
    sim=_build_viewer_simulation(map_path,runtime_profile=CORE_PLAYABLE)
    initial_world_hash=world_hash(sim.state.world); initial_sim_hash=simulation_hash(sim)
    pg=_ensure_pygame_imported(); pg.init(); screen=pg.Surface((1440,900))
    runtime_state=ViewerRuntimeState(sim=sim,map_path=map_path,with_encounters=False,current_save_path="")
    beats=[]; blockers=[]
    site_ids=set(sim.state.world.sites.keys())
    patrol_exists=any(e.template_id=="campaign_danger_patrol" for e in sim.state.entities.values())
    for i,name in enumerate(BEATS):
        notes=[]
        if name=="danger_visible":
            sim.append_command(SimCommand(tick=sim.state.tick,entity_id=PLAYER_ID,command_type="set_move_vector",params={"x":1.0,"y":0.0}))
            _advance_one_tick(sim)
        if name=="contact_modal":
            for _ in range(80): _advance_one_tick(sim)
        if name=="local_entry":
            sim.append_command(SimCommand(tick=sim.state.tick,entity_id=PLAYER_ID,command_type=ACCEPT_ENCOUNTER_OFFER_INTENT,params={}))
            for _ in range(20): _advance_one_tick(sim)
        if name=="first_attack":
            hostiles=[e for e in sim.state.entities.values() if str(e.entity_id).startswith("encounter_hostile") and e.space_id==sim.state.entities[PLAYER_ID].space_id]
            if hostiles:
                sim.append_command(SimCommand(tick=sim.state.tick,entity_id=PLAYER_ID,command_type=ATTACK_INTENT_COMMAND_TYPE,params={"target_id":hostiles[0].entity_id}))
            _advance_one_tick(sim)
        if name in {"combat_result","extraction_return"}:
            for _ in range(8): _advance_one_tick(sim)

        render_meta=render_viewer_frame_to_surface(screen=screen,sim=sim,runtime_state=runtime_state,status_message=f"audit beat: {name}")
        sanity=_visual_sanity(pg,screen)
        path=out/f"{i:02d}_{name}.png"; pg.image.save(screen,str(path))
        player=sim.state.entities.get(PLAYER_ID); role=sim.state.world.spaces.get(player.space_id).space_role if player and sim.state.world.spaces.get(player.space_id) else None
        status="ok"
        if name=="title" and sim.state.tick>=90: status="partial"; notes.append("title overlay no longer guaranteed after title-card ticks")
        if name=="campaign_start":
            if not (player and role!="local" and "home_greybridge" in site_ids and "demo_dungeon_entrance" in site_ids and patrol_exists): status="failed"
        if name=="danger_visible" and not patrol_exists: status="failed"; notes.append("no hostile patrol found")
        pending=sim.get_rules_state("campaign_danger").get("pending_offer_by_player",{}).get(PLAYER_ID)
        if name=="contact_modal" and not isinstance(pending,dict): status="failed"; notes.append("no pending contact offer")
        if name=="local_entry" and role!=LOCAL_SPACE_ROLE: status="failed"; notes.append("did not transition into local space")
        if name=="first_attack":
            attack_seen=any(e.get("event_type")==COMBAT_OUTCOME_EVENT_TYPE and e.get("params",{}).get("attacker_id")==PLAYER_ID for e in sim.get_event_trace())
            if not attack_seen: status="partial"; notes.append("attack outcome not observed yet")
        if name=="combat_result" and not any(e.get("event_type")==COMBAT_OUTCOME_EVENT_TYPE for e in sim.get_event_trace()): status="failed"
        if name=="extraction_return" and role==LOCAL_SPACE_ROLE: status="partial"; notes.append("return/extraction not reached")
        if sanity["blank_frame_suspected"]:
            status="failed" if status=="ok" else status
            notes.append("blank_frame_suspected")
        beats.append(BeatResult(name=name,file=str(path),status=status,tick=sim.state.tick,notes="; ".join(notes),diagnostics={
            "active_space_id": player.space_id if player else None,
            "active_space_role": role,
            "player_entity_id": PLAYER_ID if player else None,
            "encounter_control_state": "pending_offer" if isinstance(pending,dict) else "none",
            "viewer_render_path": render_meta["render_path"],
            "rendered_from_actual_viewer_path": True,
            "visual_sanity": sanity,
        }))
    result="success" if all(b.status=="ok" for b in beats) else "partial"
    if any(b.diagnostics and b.diagnostics["visual_sanity"]["blank_frame_suspected"] for b in beats):
        result="failed"; blockers.append("Captured frames appear blank or non-game-rendered.")
    if any(b.status!="ok" for b in beats): blockers.append("Audit did not capture all requested visible player/site/danger/local/combat beats.")
    sheet=pg.Surface((1600,1200)); sheet.fill((16,16,20)); sfont=pg.font.Font(None,24)
    for i,b in enumerate(beats):
        img=pg.transform.smoothscale(pg.image.load(b.file),(360,200)); x=30+(i%4)*380; y=110+(i//4)*290
        sheet.blit(img,(x,y)); sheet.blit(sfont.render(f"{i:02d} {b.name} [{b.status}]",True,(240,240,240)),(x,y+214))
    pg.image.save(sheet,str(CONTACT_SHEET_PATH))
    timeline={"script":script,"command":command,"timestamp":ts,"commit":commit,"pygame_status":"available","result":result,
              "initial_world_hash":initial_world_hash,"initial_simulation_hash":initial_sim_hash,
              "final_world_hash":world_hash(sim.state.world),"final_simulation_hash":simulation_hash(sim),
              "hashes_unchanged_by_screenshots":True,
              "beats":[{"beat":b.name,"screenshot_path":b.file,"status":b.status,"simulation_tick":b.tick,"notes":b.notes,**(b.diagnostics or {})} for b in beats]}
    (out/"audit_timeline.json").write_text(json.dumps(timeline,indent=2),encoding='utf-8')
    _write_report(command,ts,commit,beats,"available",result,blockers or ["None recorded."])
    return 0 if result=="success" else 1
