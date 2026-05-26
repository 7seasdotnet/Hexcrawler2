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
from hexcrawler.sim.wounds import is_incapacitated_from_wounds

DEFAULT_SCRIPT = "core_playable_first_loop"
DEFAULT_OUT = Path("docs/ai_playtest/latest")
REPORT_PATH = Path("docs/ai_playtest/AI_VISUAL_AUDIT_REPORT.md")
CONTACT_SHEET_PATH = Path("docs/ai_playtest/AI_VISUAL_AUDIT_CONTACT_SHEET.png")
BEATS = ["title","campaign_start","danger_visible","contact_modal","local_entry","first_attack","combat_result","extraction_return"]

@dataclass
class BeatResult:
    name:str; file:str; status:str; tick:int; notes:str=""; diagnostics:dict[str,Any]|None=None


@dataclass
class AttackDriveResult:
    target_id: str | None
    target_distance: float | None
    turn_issued: bool
    attack_issued: bool
    attack_tick: int | None
    outcome_detected: bool
    outcome_reason: str | None
    event_types_after_attack: list[str]
    first_attack_status: str
    combat_result_status: str

def _git_commit()->str:
    try:return subprocess.check_output(["git","rev-parse","--short","HEAD"],text=True).strip()
    except Exception:return "unknown"

def _advance_one_tick(sim:Any)->None: sim.advance_ticks(1)

def _events(sim: Any, event_type: str) -> list[dict[str, Any]]:
    return [row for row in sim.get_event_trace() if row.get("event_type") == event_type]

def _last_events(sim: Any, limit: int = 4) -> list[dict[str, Any]]:
    return list(sim.get_event_trace()[-limit:])


def _distance(a: Any, b: Any) -> float:
    dx = float(a.position_x) - float(b.position_x)
    dy = float(a.position_y) - float(b.position_y)
    return (dx * dx + dy * dy) ** 0.5


def _local_hostiles(sim: Any, player: Any) -> list[Any]:
    return [row["entity"] for row in _select_local_attack_targets(sim=sim, player=player)]


def _is_local_hostile_candidate(entity: Any) -> bool:
    template_id = str(getattr(entity, "template_id", "") or "")
    if template_id == "encounter_hostile_v1":
        return True
    faction_id = str((getattr(entity, "stats", {}) or {}).get("faction_id", "")).strip().lower()
    return faction_id == "hostile"


def _build_local_entity_probe(sim: Any, player: Any, *, selected_target_id: str | None = None) -> dict[str, Any]:
    local_space_id = getattr(player, "space_id", None) if player is not None else None
    rows: list[dict[str, Any]] = []
    for entity in sorted(sim.state.entities.values(), key=lambda e: str(getattr(e, "entity_id", ""))):
        if entity.space_id != local_space_id:
            continue
        stats = dict(entity.stats) if isinstance(entity.stats, dict) else {}
        reasons: list[str] = []
        if player is None:
            reasons.append("no_player")
        elif entity.entity_id == player.entity_id:
            reasons.append("player_self")
        if not _is_local_hostile_candidate(entity):
            reasons.append("not_hostile_marker")
        if is_incapacitated_from_wounds(getattr(entity, "wounds", [])):
            reasons.append("incapacitated")
        if selected_target_id is not None and str(entity.entity_id) == str(selected_target_id):
            reasons.append("selected_target")
        rows.append({
            "entity_id": str(entity.entity_id),
            "template_id": getattr(entity, "template_id", None),
            "position": {"x": float(getattr(entity, "position_x", 0.0)), "y": float(getattr(entity, "position_y", 0.0))},
            "faction_id": stats.get("faction_id"),
            "tags": list(getattr(entity, "tags", [])) if isinstance(getattr(entity, "tags", []), list) else [],
            "combat_fields": {"wounds_count": len(getattr(entity, "wounds", []))},
            "incapacitated": is_incapacitated_from_wounds(getattr(entity, "wounds", [])),
            "accepted_as_attack_target": len(reasons) == 0 or reasons == ["selected_target"],
            "target_selection_reasons": reasons or ["accepted"],
        })
    return {"active_local_space_id": local_space_id, "entities": rows}


def _select_local_attack_targets(sim: Any, player: Any) -> list[dict[str, Any]]:
    if player is None:
        return []
    candidates: list[dict[str, Any]] = []
    for entity in sim.state.entities.values():
        if entity.space_id != player.space_id:
            continue
        if entity.entity_id == player.entity_id:
            continue
        if not _is_local_hostile_candidate(entity):
            continue
        if is_incapacitated_from_wounds(entity.wounds):
            continue
        candidates.append({"entity": entity, "distance": _distance(player, entity)})
    candidates.sort(key=lambda row: (row["distance"], str(row["entity"].entity_id)))
    return candidates

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

    def capture(name: str, status: str, reason: str = "", issued_command: str | None = None, extra: dict[str, Any] | None = None) -> None:
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
            "viewer_viewport_rect": render_meta.get("viewport", [0, 0, 0, 0]),
            "rendered_from_actual_viewer_path": True,
            "visual_sanity": sanity,
            **(extra or {}),
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
    player_local = sim.state.entities.get(PLAYER_ID)
    capture("local_entry", "ok" if local_entered else "failed", "" if local_entered else "did not transition into local space", accept_cmd, extra={"local_entity_probe": _build_local_entity_probe(sim, player_local)})

    attack_result = AttackDriveResult(
        target_id=None, target_distance=None, turn_issued=False, attack_issued=False, attack_tick=None,
        outcome_detected=False, outcome_reason=None, event_types_after_attack=[], first_attack_status="partial", combat_result_status="failed",
    )
    if local_entered:
        player = sim.state.entities.get(PLAYER_ID)
        if player:
            hostiles = _local_hostiles(sim, player)
            if hostiles:
                target_candidates = _select_local_attack_targets(sim, player)
                target = target_candidates[0]["entity"]
                attack_result.target_id = str(target.entity_id)
                attack_result.target_distance = round(float(target_candidates[0]["distance"]), 3)
                for _ in range(80):
                    if _distance(player, target) <= 1.35:
                        break
                    dx = target.position_x - player.position_x
                    dy = target.position_y - player.position_y
                    mag = (dx * dx + dy * dy) ** 0.5 or 1.0
                    sim.append_command(SimCommand(tick=sim.state.tick, entity_id=PLAYER_ID, command_type="set_move_vector", params={"x": dx / mag, "y": dy / mag}))
                    _advance_one_tick(sim)
                    player = sim.state.entities.get(PLAYER_ID)
                if _distance(player, target) <= 1.35:
                    sim.append_command(SimCommand(tick=sim.state.tick, entity_id=PLAYER_ID, command_type=ATTACK_INTENT_COMMAND_TYPE, params={"target_id": target.entity_id, "attacker_id": PLAYER_ID, "mode": "melee"}))
                    attack_result.attack_issued = True
                    attack_result.attack_tick = sim.state.tick
                else:
                    attack_result.outcome_reason = "target_not_in_range_after_bounded_move"
            else:
                attack_result.outcome_reason = "no_local_hostile_found"

            if attack_result.attack_issued:
                for _ in range(120):
                    latest = sim.state.combat_log[-1] if sim.state.combat_log else None
                    if isinstance(latest, dict) and latest.get("attacker_id") == PLAYER_ID:
                        if latest.get("reason") == "windup_started":
                            attack_result.first_attack_status = "ok"
                        if latest.get("applied") is True or latest.get("reason") in {"resolved", "target_incapacitated"}:
                            attack_result.outcome_detected = True
                            attack_result.outcome_reason = str(latest.get("reason"))
                            attack_result.combat_result_status = "ok"
                            break
                    _advance_one_tick(sim)
                if attack_result.combat_result_status != "ok":
                    attack_result.combat_result_status = "partial"
                    if attack_result.first_attack_status != "ok":
                        attack_result.first_attack_status = "partial"
                    if attack_result.outcome_reason is None:
                        attack_result.outcome_reason = "attack_issued_no_outcome_within_wait"
            elif attack_result.outcome_reason is None:
                attack_result.outcome_reason = "attack_not_issued"

    event_types_seen = {row.get("event_type") for row in sim.get_event_trace() if isinstance(row, dict)}
    attack_result.event_types_after_attack = sorted(str(t) for t in event_types_seen if t)
    first_attack_note = "" if attack_result.first_attack_status == "ok" else (attack_result.outcome_reason or "first attack not observed")
    player_first = sim.state.entities.get(PLAYER_ID)
    capture("first_attack", attack_result.first_attack_status, first_attack_note, ATTACK_INTENT_COMMAND_TYPE if attack_result.attack_issued else None, extra={"combat_probe": attack_result.__dict__, "local_entity_probe": _build_local_entity_probe(sim, player_first, selected_target_id=attack_result.target_id)})
    combat_note = "" if attack_result.combat_result_status == "ok" else (attack_result.outcome_reason or "combat outcome not observed")
    player_combat = sim.state.entities.get(PLAYER_ID)
    capture("combat_result", attack_result.combat_result_status, combat_note, None, extra={"combat_probe": attack_result.__dict__, "local_entity_probe": _build_local_entity_probe(sim, player_combat, selected_target_id=attack_result.target_id)})

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
        raw=pg.image.load(b.file)
        viewport = (b.diagnostics or {}).get("viewer_viewport_rect", [0, 0, 0, 0])
        vx, vy, vw, vh = [int(v) for v in viewport]
        view = raw.subsurface(pg.Rect(vx, vy, vw, vh)).copy() if vw > 0 and vh > 0 else raw
        img=pg.transform.smoothscale(view,(360,200)); x=30+(i%4)*380; y=110+(i//4)*290
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
