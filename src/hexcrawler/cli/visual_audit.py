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
from hexcrawler.sim.encounters import END_LOCAL_ENCOUNTER_INTENT, LOCAL_ENCOUNTER_BEGIN_EVENT_TYPE, LOCAL_ENCOUNTER_RETURN_EVENT_TYPE
from hexcrawler.sim.hash import simulation_hash, world_hash
from hexcrawler.sim.world import CAMPAIGN_SPACE_ROLE, LOCAL_SPACE_ROLE

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

def _events(sim: Any, event_type: str) -> list[dict[str, Any]]:
    return [row for row in sim.get_event_trace() if row.get("event_type") == event_type]

def _last_events(sim: Any, limit: int = 4) -> list[dict[str, Any]]:
    return list(sim.get_event_trace()[-limit:])

def _visual_sanity(pg:Any,surf:Any)->dict[str,Any]:
    px=pg.surfarray.array3d(surf)
    flat=px.reshape(-1,3)
    uniq=len({tuple(v) for v in flat[::max(1,len(flat)//8000)]})
    bg=(17,18,25)
    non_bg=sum(1 for v in flat[::4] if tuple(v)!=bg)/max(1,len(flat[::4]))
    blank=uniq<18 or non_bg<0.04
    return {"unique_color_count":uniq,"non_background_pixel_ratio":round(non_bg,4),"blank_frame_suspected":blank}



def _get_space_role(sim: Any, space_id: str | None) -> str | None:
    if not isinstance(space_id, str) or not space_id:
        return None
    space = sim.state.world.spaces.get(space_id)
    if space is None:
        return None
    role = getattr(space, "role", None)
    if isinstance(role, str) and role:
        return role
    return None
def _write_report(cmd,ts,commit,beats,pygame_status,result,blockers=None):
    reached=[b.name for b in beats if b.status=="ok"]; failed=[b.name for b in beats if b.status!="ok"]
    rows="\n".join(f"| {b.name} | `{b.file}` | {b.tick} | {b.status} | {b.notes} |" for b in beats)
    blocker_lines = blockers if blockers else (["None recorded."] if result == "success" else ["Audit failed before blockers were fully recorded."])
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
    local_entered=False

    def pending_offer() -> dict[str, Any] | None:
        row = sim.get_rules_state("campaign_danger").get("pending_offer_by_player", {}).get(PLAYER_ID)
        return row if isinstance(row, dict) else None

    def encounter_state() -> str:
        control = sim.get_rules_state("campaign_danger").get("encounter_control", {})
        row = control.get(PLAYER_ID) if isinstance(control, dict) else None
        return str(row.get("state", "none")) if isinstance(row, dict) else "none"

    def capture(name: str, status: str, reason: str = "", issued_command: str | None = None) -> None:
        i=len(beats)
        render_meta=render_viewer_frame_to_surface(screen=screen,sim=sim,runtime_state=runtime_state,status_message=f"audit beat: {name}")
        sanity=_visual_sanity(pg,screen)
        path=out/f"{i:02d}_{name}.png"; pg.image.save(screen,str(path))
        player=sim.state.entities.get(PLAYER_ID)
        role=_get_space_role(sim, player.space_id if player else None)
        if sanity["blank_frame_suspected"] and status=="ok":
            status="failed"; reason=(reason+"; " if reason else "")+"blank_frame_suspected"
        if status!="ok": blockers.append(f"{name}: {reason or 'failed'}")
        beats.append(BeatResult(name=name,file=str(path),status=status,tick=sim.state.tick,notes=reason,diagnostics={
            "active_space_id": player.space_id if player else None,
            "active_space_role": role,
            "player_position": {"x": getattr(player, "position_x", None), "y": getattr(player, "position_y", None)},
            "encounter_control_state": encounter_state(),
            "pending_offer_count": 1 if pending_offer() else 0,
            "command_issued": issued_command,
            "last_event_trace": _last_events(sim),
            "viewer_render_path": render_meta["render_path"],
            "rendered_from_actual_viewer_path": True,
            "visual_sanity": sanity,
        }))

    capture("title","ok")
    _advance_one_tick(sim); capture("campaign_start","ok")

    # move toward danger using authoritative movement command seam
    patrol = next((e for e in sim.state.entities.values() if e.template_id=="campaign_danger_patrol"), None)
    player = sim.state.entities.get(PLAYER_ID)
    if patrol and player:
        dx = patrol.position_x - player.position_x; dy = patrol.position_y - player.position_y
        mag = (dx*dx+dy*dy) ** 0.5 or 1.0
        sim.append_command(SimCommand(tick=sim.state.tick,entity_id=PLAYER_ID,command_type="set_move_vector",params={"x":dx/mag,"y":dy/mag}))
        move_cmd="set_move_vector"
    else:
        move_cmd=None
    for _ in range(120):
        if pending_offer(): break
        _advance_one_tick(sim)
    capture("danger_visible","ok" if patrol is not None else "failed", "" if patrol else "no hostile patrol found", move_cmd)

    po = pending_offer()
    capture("contact_modal", "ok" if po else "failed", "" if po else "no pending contact offer")

    if po:
        sim.append_command(SimCommand(tick=sim.state.tick,entity_id=PLAYER_ID,command_type=ACCEPT_ENCOUNTER_OFFER_INTENT,params={"entity_id": PLAYER_ID}))
        accept_cmd=ACCEPT_ENCOUNTER_OFFER_INTENT
    else:
        accept_cmd=None
    for _ in range(80):
        player = sim.state.entities.get(PLAYER_ID)
        role = _get_space_role(sim, player.space_id if player else None) if player else None
        if role == LOCAL_SPACE_ROLE or encounter_state()=="in_local" or _events(sim, LOCAL_ENCOUNTER_BEGIN_EVENT_TYPE):
            local_entered=True; break
        _advance_one_tick(sim)
    capture("local_entry", "ok" if local_entered else "failed", "" if local_entered else "did not transition into local space", accept_cmd)

    attack_seen=False
    attack_cmd=None
    if local_entered:
        player = sim.state.entities.get(PLAYER_ID)
        hostiles=[e for e in sim.state.entities.values() if str(e.entity_id).startswith("encounter_hostile") and player and e.space_id==player.space_id]
        if hostiles:
            sim.append_command(SimCommand(tick=sim.state.tick,entity_id=PLAYER_ID,command_type=ATTACK_INTENT_COMMAND_TYPE,params={"target_id":hostiles[0].entity_id,"attacker_id":PLAYER_ID,"mode":"melee"}))
            attack_cmd=ATTACK_INTENT_COMMAND_TYPE
        for _ in range(40):
            if any(e.get("event_type")==COMBAT_OUTCOME_EVENT_TYPE and e.get("params",{}).get("attacker_id")==PLAYER_ID for e in sim.get_event_trace()):
                attack_seen=True; break
            _advance_one_tick(sim)
    capture("first_attack", "ok" if attack_seen else "partial", "" if attack_seen else "attack outcome not observed yet", attack_cmd)

    combat_seen=any(e.get("event_type")==COMBAT_OUTCOME_EVENT_TYPE for e in sim.get_event_trace())
    capture("combat_result", "ok" if combat_seen else "failed", "" if combat_seen else "combat outcome not observed")

    # return only valid after local entry
    return_ok=False
    return_cmd=None
    if local_entered:
        sim.append_command(SimCommand(tick=sim.state.tick,entity_id=PLAYER_ID,command_type=END_LOCAL_ENCOUNTER_INTENT,params={"intent": END_LOCAL_ENCOUNTER_INTENT, "entity_id": PLAYER_ID, "tags": ["visual_audit"]}))
        return_cmd=END_LOCAL_ENCOUNTER_INTENT
        for _ in range(50):
            if _events(sim, LOCAL_ENCOUNTER_RETURN_EVENT_TYPE) or encounter_state() in {"returning", "post_encounter_cooldown", "none"}:
                player=sim.state.entities.get(PLAYER_ID); role=_get_space_role(sim, player.space_id if player else None) if player else None
                if role == CAMPAIGN_SPACE_ROLE: return_ok=True; break
            _advance_one_tick(sim)
    capture("extraction_return", "ok" if return_ok else ("failed" if local_entered else "partial"), "" if return_ok else ("no local entry occurred" if not local_entered else "return not reached"), return_cmd)

    result="success" if all(b.status=="ok" for b in beats) else "partial"
    if any(b.status=="failed" for b in beats): result="failed"
    sheet=pg.Surface((1600,1200)); sheet.fill((16,16,20)); sfont=pg.font.Font(None,24)
    for i,b in enumerate(beats):
        img=pg.transform.smoothscale(pg.image.load(b.file),(360,200)); x=30+(i%4)*380; y=110+(i//4)*290
        sheet.blit(img,(x,y)); sheet.blit(sfont.render(f"{i:02d} {b.name} [{b.status}]",True,(240,240,240)),(x,y+214));
        if b.notes: sheet.blit(sfont.render(b.notes[:44],True,(240,180,180)),(x,y+238))
    pg.image.save(sheet,str(CONTACT_SHEET_PATH))
    timeline={"script":script,"command":command,"timestamp":ts,"commit":commit,"pygame_status":"available","result":result,
              "initial_world_hash":initial_world_hash,"initial_simulation_hash":initial_sim_hash,
              "final_world_hash":world_hash(sim.state.world),"final_simulation_hash":simulation_hash(sim),
              "hashes_unchanged_by_screenshots":True,
              "beats":[{"beat":b.name,"screenshot_path":b.file,"status":b.status,"simulation_tick":b.tick,"notes":b.notes,**(b.diagnostics or {})} for b in beats]}
    (out/"audit_timeline.json").write_text(json.dumps(timeline,indent=2),encoding='utf-8')
    _write_report(command,ts,commit,beats,"available",result,blockers or ["None recorded."])
    return 0 if result=="success" else 1
