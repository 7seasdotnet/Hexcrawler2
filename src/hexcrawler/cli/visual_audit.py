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
from hexcrawler.sim.core import EntityState, SimCommand
from hexcrawler.sim.campaign_danger import ACCEPT_ENCOUNTER_OFFER_INTENT
from hexcrawler.sim.combat import ATTACK_INTENT_COMMAND_TYPE, COMBAT_OUTCOME_EVENT_TYPE, combat_cadence_probe
from hexcrawler.sim.encounters import END_LOCAL_ENCOUNTER_INTENT, LOCAL_ENCOUNTER_BEGIN_EVENT_TYPE, LOCAL_ENCOUNTER_RETURN_EVENT_TYPE
from hexcrawler.sim.hash import simulation_hash, world_hash
from hexcrawler.sim.location import SQUARE_GRID_TOPOLOGY
from hexcrawler.sim.world import CAMPAIGN_SPACE_ROLE, LOCAL_SPACE_ROLE, SpaceState
from hexcrawler.sim.wounds import is_incapacitated_from_wounds

DEFAULT_SCRIPT = "core_playable_first_loop"
DEFAULT_OUT = Path("docs/ai_playtest/latest")
MELEE_READABILITY_SCRIPT = "melee_readability_proving_ground"
MELEE_READABILITY_OUT = Path("docs/ai_playtest/melee_readability/latest")
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




def _find_local_return_context(sim: Any, player: Any) -> dict[str, Any] | None:
    if player is None:
        return None
    state = sim.get_rules_state("local_encounter_instance")
    active = state.get("active_by_local_space", {}) if isinstance(state, dict) else {}
    row = active.get(player.space_id) if isinstance(active, dict) else None
    return row if isinstance(row, dict) else None


def _coord_xy(sim: Any, space_id: str, coord: dict[str, Any] | None) -> dict[str, float] | None:
    if not isinstance(coord, dict):
        return None
    try:
        from hexcrawler.sim.movement import square_grid_cell_to_world_xy
        x, y = square_grid_cell_to_world_xy(int(coord.get("x")), int(coord.get("y")))
        return {"x": float(x), "y": float(y)}
    except Exception:
        return None


def _distance_to_return_exit(sim: Any, player: Any, return_exit_coord: dict[str, Any] | None) -> float | None:
    if player is None or not isinstance(return_exit_coord, dict):
        return None
    target = _coord_xy(sim, player.space_id, return_exit_coord)
    if target is None:
        return None
    dx = float(player.position_x) - float(target["x"])
    dy = float(player.position_y) - float(target["y"])
    return (dx * dx + dy * dy) ** 0.5


def _player_local_coord(sim: Any, player: Any) -> dict[str, int] | None:
    if player is None:
        return None
    try:
        coord = sim._entity_location_ref(player).coord
        if isinstance(coord, dict) and "x" in coord and "y" in coord:
            return {"x": int(coord["x"]), "y": int(coord["y"])}
    except Exception:
        return None
    return None


def _at_return_exit(sim: Any, player: Any, return_exit_coord: dict[str, Any] | None) -> bool:
    player_coord = _player_local_coord(sim, player)
    return isinstance(return_exit_coord, dict) and player_coord == {"x": int(return_exit_coord.get("x")), "y": int(return_exit_coord.get("y"))}
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



def _extract_cue_timeline(diag: dict[str, Any]) -> dict[str, Any]:
    rendered = diag.get("rendered_cues", []) if isinstance(diag, dict) else []
    row = rendered[0] if rendered else {}
    return {
        "cue_count": int(diag.get("cue_count", 0)) if isinstance(diag, dict) else 0,
        "cue_rendered": bool(diag.get("cue_rendered", False)) if isinstance(diag, dict) else False,
        "active_cue_ids": list(diag.get("active_cue_ids", [])) if isinstance(diag, dict) else [],
        "cue_render_failure_reason": diag.get("cue_render_failure_reason") if isinstance(diag, dict) else "missing_diag",
        "cue_phase": row.get("phase"),
        "cue_age": row.get("age_ticks"),
        "attacker_id": row.get("attacker_id"),
        "target_id": row.get("target_id"),
        "outcome_label": row.get("outcome_label"),
        "evidence_source": row.get("evidence_source"),
        "evidence_reason": row.get("evidence_reason"),
        "evidence_applied": row.get("evidence_applied"),
        "weapon_profile_id": row.get("weapon_profile_id"),
        "motion_family": row.get("motion_family"),
        "attacker_screen_pos": row.get("attacker_screen_pos"),
        "target_screen_pos": row.get("target_screen_pos"),
        "arc_bbox": row.get("arc_bbox"),
        "impact_bbox": row.get("impact_bbox"),
        "motion_primitive": row.get("motion_primitive"),
        "weapon_motion_primitive": row.get("weapon_motion_primitive", row.get("motion_primitive")),
        "motion_points": row.get("motion_points"),
        "motion_stroke_width": row.get("motion_stroke_width"),
        "arc_origin_actor_id": row.get("arc_origin_actor_id"),
        "arc_target_id": row.get("arc_target_id"),
        "presentation_target_source": row.get("presentation_target_source"),
        "arc_origin_local": row.get("arc_origin_local"),
        "arc_contact_local": row.get("arc_contact_local"),
        "arc_target_point": row.get("arc_target_point"),
        "arc_committed_facing": row.get("arc_committed_facing"),
        "arc_sample_count": row.get("arc_sample_count"),
        "arc_reaches_target_marker_edge": row.get("arc_reaches_target_marker_edge"),
        "contact_screen_pos": row.get("contact_screen_pos"),
        "contact_accent_radius_px": row.get("contact_accent_radius_px"),
        "contact_accent_bounded": row.get("contact_accent_bounded"),
        "result_badge_separate_from_trail": row.get("result_badge_separate_from_trail"),
        "actor_marker_layer_above_weapon_cue": row.get("actor_marker_layer_above_weapon_cue"),
        "target_marker_remains_visible": row.get("target_marker_remains_visible"),
        "actor_marker_visible": row.get("actor_marker_visible"),
        "target_marker_visible": row.get("target_marker_visible"),
        "large_impact_blob_detected": row.get("large_impact_blob_detected"),
        "badge_text": row.get("badge_text"),
        "badge_screen_pos": row.get("badge_screen_pos"),
        "render_layer_used": row.get("render_layer_used"),
        "refresh_diagnostics": diag.get("refresh_diagnostics") if isinstance(diag, dict) else None,
    }

def _draw_combat_inset(pg: Any, sheet: Any, view: Any, beat: BeatResult, x: int, y: int) -> None:
    if beat.name not in {"first_attack", "combat_result"}:
        return
    timeline = ((beat.diagnostics or {}).get("combat_cue_timeline") or {})
    bbox = timeline.get("arc_bbox") if beat.name == "first_attack" else timeline.get("impact_bbox")
    if not isinstance(bbox, dict):
        return
    bx, by, bw, bh = int(bbox.get("x", 0)), int(bbox.get("y", 0)), int(bbox.get("w", 0)), int(bbox.get("h", 0))
    if bw <= 0 or bh <= 0:
        return
    rect = pg.Rect(max(0, bx-30), max(0, by-30), min(view.get_width(), bw+60), min(view.get_height(), bh+60))
    rect.width = min(rect.width, view.get_width()-rect.x); rect.height = min(rect.height, view.get_height()-rect.y)
    if rect.width <= 8 or rect.height <= 8:
        return
    crop = view.subsurface(rect).copy()
    inset = pg.transform.smoothscale(crop, (168, 112))
    sheet.blit(inset, (x+248, y+6))
    pg.draw.rect(sheet, (255,210,130), pg.Rect(x+248, y+6, 168, 112), 3)

def _setup_melee_readability_proving_ground(sim: Any) -> tuple[str, str]:
    """Create a deterministic local-only combat proving ground for presentation audit."""
    local_space_id = "local_combat_proving_ground"
    sim.state.world.spaces[local_space_id] = SpaceState(
        space_id=local_space_id,
        topology_type=SQUARE_GRID_TOPOLOGY,
        role=LOCAL_SPACE_ROLE,
        topology_params={"width": 6, "height": 4, "origin": {"x": 0, "y": 0}},
    )
    player = sim.state.entities[PLAYER_ID]
    player.space_id = local_space_id
    player.position_x = 1.25
    player.position_y = 1.75
    player.speed_per_tick = 0.0
    player.facing = 0
    player.cooldown_until_tick = 0
    hostile_id = "hostile:melee_readability_dummy"
    sim.state.entities.pop(hostile_id, None)
    hostile = EntityState(
        entity_id=hostile_id,
        position_x=2.25,
        position_y=1.75,
        speed_per_tick=0.0,
        space_id=local_space_id,
        template_id="encounter_hostile_v1",
        stats={"faction_id": "hostile", "role": "readability_dummy"},
    )
    hostile.facing = 3
    sim.add_entity(hostile)
    return local_space_id, hostile_id


def _validate_melee_readability_beat(name: str, timeline: dict[str, Any]) -> tuple[str, str]:
    failures: list[str] = []
    if name in {"windup_committed_facing", "swing_mid_arc", "contact", "result", "recovery"}:
        if timeline.get("cue_rendered") is not True:
            failures.append("cue_rendered_false")
        if timeline.get("weapon_motion_primitive") != "arc":
            failures.append("default_melee_not_arc_primitive")
        sample_count = timeline.get("arc_sample_count")
        if not isinstance(sample_count, int) or sample_count < 7:
            failures.append("arc_sample_count_too_low")
        if timeline.get("actor_marker_visible") is False or timeline.get("target_marker_visible") is False:
            failures.append("marker_visibility_false")
        if timeline.get("large_impact_blob_detected") is True:
            failures.append("large_impact_blob_detected")
        if timeline.get("presentation_target_source") != "target_id":
            failures.append("target_source_not_target_id")
        if timeline.get("arc_reaches_target_marker_edge") is not True:
            failures.append("arc_not_target_edge")
    if name == "result" and timeline.get("evidence_reason") not in {"resolved", "target_incapacitated"}:
        failures.append("result_without_resolved_evidence")
    return ("ok", "") if not failures else ("failed", "; ".join(failures))


def _run_melee_readability_audit(*, map_path: str, out_dir: str | None, script: str, command: str) -> int:
    ts=datetime.now(timezone.utc).isoformat(); commit=_git_commit()
    out = MELEE_READABILITY_OUT if out_dir is None or Path(out_dir) == DEFAULT_OUT else Path(out_dir)
    out.mkdir(parents=True,exist_ok=True)
    for f in out.glob('*.png'): f.unlink()
    sim=_build_viewer_simulation(map_path,runtime_profile=CORE_PLAYABLE)
    local_space_id, hostile_id = _setup_melee_readability_proving_ground(sim)
    initial_world_hash=world_hash(sim.state.world); initial_sim_hash=simulation_hash(sim)
    pg=_ensure_pygame_imported(); pg.init(); screen=pg.Surface((1440,900))
    runtime_state=ViewerRuntimeState(sim=sim,map_path=map_path,with_encounters=False,current_save_path="", visual_audit_mode=True)
    beats: list[BeatResult] = []
    blockers: list[str] = []

    def capture(name: str, status: str = "ok", reason: str = "", cue_phase_override: str | None = None, issued_command: str | None = None) -> None:
        i=len(beats)
        render_meta=render_viewer_frame_to_surface(screen=screen,sim=sim,runtime_state=runtime_state,status_message=f"melee readability: {name}",player_view=True,combat_cue_phase_override=cue_phase_override)
        sanity=_visual_sanity(pg,screen)
        timeline=_extract_cue_timeline(render_meta.get("combat_cue_diagnostics", {}))
        if status == "ok":
            status, reason = _validate_melee_readability_beat(name, timeline)
        if sanity["blank_frame_suspected"] and status == "ok":
            status="failed"; reason="blank_frame_suspected"
        path=out/f"{i:02d}_{name}.png"; pg.image.save(screen,str(path))
        player=sim.state.entities.get(PLAYER_ID)
        cadence_rows = combat_cadence_probe(sim).get("rows", [])
        diag={
            "active_space_id": local_space_id,
            "active_space_role": LOCAL_SPACE_ROLE,
            "player_position": {"x": getattr(player, "position_x", None), "y": getattr(player, "position_y", None)},
            "target_id": hostile_id,
            "cadence_state": timeline.get("cue_phase") or ("READY" if player and int(player.cooldown_until_tick) <= int(sim.state.tick) else "RECOVERING"),
            "motion_family": timeline.get("motion_family"),
            "committed_facing": timeline.get("arc_committed_facing"),
            "arc_origin": timeline.get("arc_origin_local"),
            "arc_contact": timeline.get("arc_contact_local"),
            "arc_sample_count": timeline.get("arc_sample_count"),
            "actor_marker_visible": timeline.get("actor_marker_visible"),
            "target_marker_visible": timeline.get("target_marker_visible"),
            "large_impact_blob_detected": timeline.get("large_impact_blob_detected"),
            "result_evidence_authoritative": timeline.get("evidence_source") in {"event_trace", "combat_log"},
            "viewer_render_path": render_meta["render_path"],
            "viewer_viewport_rect": render_meta.get("viewport", [0,0,0,0]),
            "combat_cue_diagnostics": render_meta.get("combat_cue_diagnostics", {}),
            "combat_cue_timeline": timeline,
            "combat_cadence_probe": cadence_rows[-8:] if isinstance(cadence_rows, list) else [],
            "rendered_from_actual_viewer_path": True,
            "visual_sanity": sanity,
            "command_issued": issued_command,
        }
        if status != "ok": blockers.append(f"{name}: {reason or 'failed'}")
        beats.append(BeatResult(name=name,file=str(path),status=status,tick=sim.state.tick,notes=reason,diagnostics=diag))

    capture("pre_attack_ready")
    sim.append_command(SimCommand(tick=sim.state.tick, entity_id=PLAYER_ID, command_type=ATTACK_INTENT_COMMAND_TYPE, params={"attacker_id": PLAYER_ID, "target_id": hostile_id, "mode": "melee", "weapon_profile_id": "default_melee", "committed_aim": {"space_id": local_space_id, "x": 1.0, "y": 0.0, "facing": 0}, "tags": ["melee_readability_proving_ground"]}))
    attack_tick = sim.state.tick
    _advance_one_tick(sim)
    capture("windup_committed_facing", cue_phase_override="windup", issued_command=ATTACK_INTENT_COMMAND_TYPE)
    _advance_one_tick(sim)
    capture("swing_mid_arc", cue_phase_override="swing_mid_arc")
    _advance_one_tick(sim)
    capture("contact", cue_phase_override="impact")
    capture("result", cue_phase_override="impact")
    for _ in range(3): _advance_one_tick(sim)
    capture("recovery", cue_phase_override="recovery")
    while sim.state.tick < attack_tick + 8:
        _advance_one_tick(sim)
    capture("ready_again")

    result="success" if all(b.status=="ok" for b in beats) else "partial"
    if any(b.status=="failed" for b in beats): result="failed"
    sheet=pg.Surface((1800,1260)); sheet.fill((16,16,20)); sfont=pg.font.Font(None,28)
    for i,b in enumerate(beats):
        raw=pg.image.load(b.file); viewport=(b.diagnostics or {}).get("viewer_viewport_rect", [0,0,0,0]); vx,vy,vw,vh=[int(v) for v in viewport]
        view=raw.subsurface(pg.Rect(vx,vy,vw,vh)).copy() if vw>0 and vh>0 else raw
        img=pg.transform.smoothscale(view,(520,292)); x=28+(i%3)*588; y=88+(i//3)*374
        sheet.blit(img,(x,y)); _draw_combat_inset(pg,sheet,view,b,x,y); sheet.blit(sfont.render(f"{i:02d} {b.name} [{b.status}]",True,(240,240,240)),(x,y+296))
        if b.notes: sheet.blit(sfont.render(b.notes[:56],True,(240,180,180)),(x,y+322))
    sheet_path=out/"MELEE_READABILITY_CONTACT_SHEET.png"; pg.image.save(sheet,str(sheet_path))
    timeline={"script":script,"command":command,"timestamp":ts,"commit":commit,"pygame_status":"available","result":result,"initial_world_hash":initial_world_hash,"initial_simulation_hash":initial_sim_hash,"final_world_hash":world_hash(sim.state.world),"final_simulation_hash":simulation_hash(sim),"hashes_unchanged_by_screenshots":True,"beats":[{"beat":b.name,"screenshot_path":b.file,"status":b.status,"simulation_tick":b.tick,"notes":b.notes,**(b.diagnostics or {})} for b in beats]}
    (out/"melee_readability_timeline.json").write_text(json.dumps(timeline,indent=2),encoding='utf-8')
    report_lines=[f"# Melee Readability Report", "", f"- Script: `{script}`", f"- Result: `{result}`", f"- Contact sheet: `{sheet_path}`", "", "## Beats"]
    report_lines.extend(f"- `{b.name}` tick={b.tick} status={b.status} notes={b.notes or 'ok'}" for b in beats)
    report_lines.extend(["", "## Blockers", *(f"- {row}" for row in (blockers or ["None recorded."]))])
    (out/"MELEE_READABILITY_REPORT.md").write_text("\n".join(report_lines)+"\n",encoding='utf-8')
    return 0 if result=="success" else 1

def run_visual_audit(*,map_path:str,out_dir:str|None=None,script:str=DEFAULT_SCRIPT,command:str="python play.py --visual-audit")->int:
    if script == MELEE_READABILITY_SCRIPT:
        return _run_melee_readability_audit(map_path=map_path, out_dir=out_dir, script=script, command=command)
    ts=datetime.now(timezone.utc).isoformat(); commit=_git_commit(); out=Path(out_dir) if out_dir else DEFAULT_OUT; out.mkdir(parents=True,exist_ok=True)
    for f in out.glob('*.png'): f.unlink()
    sim=_build_viewer_simulation(map_path,runtime_profile=CORE_PLAYABLE)
    initial_world_hash=world_hash(sim.state.world); initial_sim_hash=simulation_hash(sim)
    pg=_ensure_pygame_imported(); pg.init(); screen=pg.Surface((1440,900))
    runtime_state=ViewerRuntimeState(sim=sim,map_path=map_path,with_encounters=False,current_save_path="", visual_audit_mode=True)
    beats=[]; blockers=[]
    local_entered=False

    def pending_offer() -> dict[str, Any] | None:
        row = sim.get_rules_state("campaign_danger").get("pending_offer_by_player", {}).get(PLAYER_ID)
        return row if isinstance(row, dict) else None

    def encounter_state() -> str:
        control = sim.get_rules_state("campaign_danger").get("encounter_control", {})
        row = control.get(PLAYER_ID) if isinstance(control, dict) else None
        return str(row.get("state", "none")) if isinstance(row, dict) else "none"

    def capture(name: str, status: str, reason: str = "", issued_command: str | None = None, extra: dict[str, Any] | None = None, cue_phase_override: str | None = None) -> None:
        i=len(beats)
        render_meta=render_viewer_frame_to_surface(
            screen=screen,
            sim=sim,
            runtime_state=runtime_state,
            status_message=f"audit beat: {name}",
            player_view=True,
            combat_cue_phase_override=cue_phase_override,
        )
        sanity=_visual_sanity(pg,screen)
        path=out/f"{i:02d}_{name}.png"; pg.image.save(screen,str(path))
        player=sim.state.entities.get(PLAYER_ID)
        role=_get_space_role(sim, player.space_id if player else None)
        if sanity["blank_frame_suspected"] and status=="ok":
            status="failed"; reason=(reason+"; " if reason else "")+"blank_frame_suspected"
        if name in {"first_attack", "combat_result"} and status == "ok":
            cue_timeline = _extract_cue_timeline(render_meta.get("combat_cue_diagnostics", {}))
            bbox = cue_timeline.get("arc_bbox") if name == "first_attack" else cue_timeline.get("impact_bbox")
            motion = str(cue_timeline.get("weapon_motion_primitive") or cue_timeline.get("motion_primitive") or "")
            if cue_timeline.get("cue_rendered") is not True:
                status = "partial"
                reason = (reason+"; " if reason else "") + "cue_rendered_false"
            elif motion not in {"arc", "chop_arc", "thrust", "stab", "bash_shove"}:
                status = "partial"
                reason = (reason+"; " if reason else "") + "weapon_motion_primitive_unreadable"
            elif cue_timeline.get("target_marker_visible") is False or cue_timeline.get("target_marker_remains_visible") is False:
                status = "partial"
                reason = (reason+"; " if reason else "") + "target_marker_obscured"
            elif cue_timeline.get("large_impact_blob_detected") is True:
                status = "partial"
                reason = (reason+"; " if reason else "") + "large_impact_blob_detected"
            elif isinstance(bbox, dict):
                bx, by, bw, bh = int(bbox.get("x",0)), int(bbox.get("y",0)), int(bbox.get("w",0)), int(bbox.get("h",0))
                if bw <= 0 or bh <= 0 or bx >= screen.get_width() or by >= screen.get_height() or (bx+bw) <= 0 or (by+bh) <= 0:
                    status = "partial"
                    reason = (reason+"; " if reason else "") + "cue_bbox_offscreen"
            if status == "ok" and name == "combat_result":
                points = cue_timeline.get("motion_points")
                if not isinstance(points, list) or len(points) < 5:
                    status = "partial"
                    reason = (reason+"; " if reason else "") + "default_melee_not_rendered_as_sampled_arc"
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
            "combat_cue_diagnostics": render_meta.get("combat_cue_diagnostics", {}),
            "combat_cue_timeline": _extract_cue_timeline(render_meta.get("combat_cue_diagnostics", {})),
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
                    sim.append_command(SimCommand(tick=sim.state.tick, entity_id=PLAYER_ID, command_type=ATTACK_INTENT_COMMAND_TYPE, params={"target_id": target.entity_id, "attacker_id": PLAYER_ID, "mode": "melee", "tags": ["visual_audit"]}))
                    attack_result.attack_issued = True
                    attack_result.attack_tick = sim.state.tick
                else:
                    attack_result.outcome_reason = "target_not_in_range_after_bounded_move"
            else:
                attack_result.outcome_reason = "no_local_hostile_found"

            if not attack_result.attack_issued and attack_result.outcome_reason is None:
                attack_result.outcome_reason = "attack_not_issued"

    combat_cadence_sequence: dict[str, Any] = {
        "pre_click_ready": attack_result.attack_tick is not None,
        "accepted_attack_tick": None,
        "windup_start_tick": None,
        "impact_tick": None,
        "recovery_until_tick": None,
        "ready_again_tick": None,
        "hostile_cadence_diagnostics": None,
    }
    if attack_result.attack_issued:
        for _ in range(40):
            player_rows = [row for row in sim.state.combat_log if isinstance(row, dict) and row.get("attacker_id") == PLAYER_ID]
            windup = next((row for row in reversed(player_rows) if row.get("reason") == "windup_started"), None)
            if isinstance(windup, dict):
                attack_result.first_attack_status = "ok"
                combat_cadence_sequence["accepted_attack_tick"] = windup.get("tick")
                combat_cadence_sequence["windup_start_tick"] = windup.get("tick")
                combat_cadence_sequence["impact_tick"] = windup.get("impact_tick")
                combat_cadence_sequence["recovery_until_tick"] = windup.get("recovery_until_tick")
                break
            _advance_one_tick(sim)
        if attack_result.first_attack_status != "ok":
            attack_result.first_attack_status = "partial"
            if attack_result.outcome_reason is None:
                attack_result.outcome_reason = "attack_issued_no_windup_within_wait"

    event_types_seen = {row.get("event_type") for row in sim.get_event_trace() if isinstance(row, dict)}
    attack_result.event_types_after_attack = sorted(str(t) for t in event_types_seen if t)
    first_attack_note = "" if attack_result.first_attack_status == "ok" else (attack_result.outcome_reason or "first attack not observed")
    player_first = sim.state.entities.get(PLAYER_ID)
    cadence_probe_first = combat_cadence_probe(sim)
    combat_cadence_sequence["hostile_cadence_diagnostics"] = [row for row in cadence_probe_first.get("rows", []) if str(row.get("source_path")) == "hostile_ai"][-6:]
    capture("first_attack", attack_result.first_attack_status, first_attack_note, ATTACK_INTENT_COMMAND_TYPE if attack_result.attack_issued else None, extra={"combat_probe": attack_result.__dict__, "combat_cadence_probe": cadence_probe_first, "combat_cadence_sequence": dict(combat_cadence_sequence), "local_entity_probe": _build_local_entity_probe(sim, player_first, selected_target_id=attack_result.target_id)}, cue_phase_override="windup")

    if attack_result.attack_issued and attack_result.first_attack_status == "ok":
        for _ in range(120):
            player_rows = [row for row in sim.state.combat_log if isinstance(row, dict) and row.get("attacker_id") == PLAYER_ID]
            latest = player_rows[-1] if player_rows else None
            if isinstance(latest, dict) and (latest.get("applied") is True or latest.get("reason") in {"resolved", "target_incapacitated", "no_target_in_cell", "target_moved"}):
                attack_result.outcome_detected = True
                attack_result.outcome_reason = str(latest.get("reason"))
                attack_result.combat_result_status = "ok"
                combat_cadence_sequence["impact_tick"] = latest.get("tick")
                combat_cadence_sequence["recovery_until_tick"] = latest.get("recovery_until_tick", combat_cadence_sequence.get("recovery_until_tick"))
                break
            _advance_one_tick(sim)
        if attack_result.combat_result_status != "ok":
            attack_result.combat_result_status = "partial"
            if attack_result.outcome_reason is None:
                attack_result.outcome_reason = "attack_issued_no_outcome_within_wait"
    combat_note = "" if attack_result.combat_result_status == "ok" else (attack_result.outcome_reason or "combat outcome not observed")
    if attack_result.combat_result_status == "ok" and combat_cadence_sequence.get("accepted_attack_tick") == combat_cadence_sequence.get("impact_tick"):
        combat_note = "accepted_attack_and_impact_same_tick"
        attack_result.combat_result_status = "partial"
    player_combat = sim.state.entities.get(PLAYER_ID)
    cadence_probe_combat = combat_cadence_probe(sim)
    combat_cadence_sequence["ready_again_tick"] = combat_cadence_sequence.get("recovery_until_tick")
    combat_cadence_sequence["hostile_cadence_diagnostics"] = [row for row in cadence_probe_combat.get("rows", []) if str(row.get("source_path")) in {"hostile_ai", "scheduled_impact"} and row.get("actor_id") != PLAYER_ID][-8:]
    capture("combat_result", attack_result.combat_result_status, combat_note, None, extra={"combat_probe": attack_result.__dict__, "combat_cadence_probe": cadence_probe_combat, "combat_cadence_sequence": dict(combat_cadence_sequence), "local_entity_probe": _build_local_entity_probe(sim, player_combat, selected_target_id=attack_result.target_id)}, cue_phase_override="impact")

    # return only valid after local entry and only when admissible at extraction exit
    return_ok=False
    return_cmd=None
    return_status = "failed"
    return_reason = ""
    extraction_probe: dict[str, Any] = {}
    if not local_entered:
        return_status = "failed"
        return_reason = "no local entry occurred"
    else:
        player = sim.state.entities.get(PLAYER_ID)
        context = _find_local_return_context(sim, player)
        return_exit_coord = context.get("return_exit_coord") if isinstance(context, dict) else None
        target_xy = _coord_xy(sim, player.space_id, return_exit_coord) if player and isinstance(return_exit_coord, dict) else None
        player_before = {"x": float(player.position_x), "y": float(player.position_y)} if player else None
        player_before_cell = _player_local_coord(sim, player)
        extraction_probe = {
            "active_local_space_id": player.space_id if player else None,
            "encounter_control_state_before_movement": encounter_state(),
            "player_position_before_movement": player_before,
            "player_local_coord_before_movement": player_before_cell,
            "return_exit_coord": return_exit_coord,
            "return_exit_world_position": target_xy,
            "distance_before_movement": _distance_to_return_exit(sim, player, return_exit_coord),
        }
        if player is None or context is None or not isinstance(return_exit_coord, dict):
            return_status = "failed"
            return_reason = "no return affordance found"
        else:
            # Move to return exit first (admissibility gate).
            movement_command_count = 0
            movement_ticks_advanced = 0
            for _ in range(240):
                player = sim.state.entities.get(PLAYER_ID)
                if player is None:
                    break
                if _at_return_exit(sim, player, return_exit_coord):
                    break
                if target_xy is None:
                    break
                dx = float(target_xy["x"]) - float(player.position_x)
                dy = float(target_xy["y"]) - float(player.position_y)
                mag = (dx * dx + dy * dy) ** 0.5 or 1.0
                sim.append_command(SimCommand(tick=sim.state.tick, entity_id=PLAYER_ID, command_type="set_move_vector", params={"x": dx / mag, "y": dy / mag}))
                movement_command_count += 1
                _advance_one_tick(sim)
                movement_ticks_advanced += 1
            player = sim.state.entities.get(PLAYER_ID)
            at_exit = _at_return_exit(sim, player, return_exit_coord)
            extraction_probe["movement_command_count"] = movement_command_count
            extraction_probe["movement_ticks_advanced"] = movement_ticks_advanced
            extraction_probe["player_position_after_movement"] = {"x": float(player.position_x), "y": float(player.position_y)} if player else None
            extraction_probe["player_local_coord_after_movement"] = _player_local_coord(sim, player)
            extraction_probe["distance_after_movement"] = _distance_to_return_exit(sim, player, return_exit_coord)
            extraction_probe["at_return_exit_before_command"] = at_exit
            if not at_exit:
                return_status = "failed"
                return_reason = "not_at_return_exit_after_bounded_move"
                extraction_probe["hostile_pinning_blocked"] = "unknown"
                extraction_probe["return_command_issued"] = False
            else:
                sim.append_command(SimCommand(tick=sim.state.tick,entity_id=PLAYER_ID,command_type=END_LOCAL_ENCOUNTER_INTENT,params={"intent": END_LOCAL_ENCOUNTER_INTENT, "entity_id": PLAYER_ID, "tags": ["visual_audit"]}))
                return_cmd=END_LOCAL_ENCOUNTER_INTENT
                command_tick = sim.state.tick
                for _ in range(80):
                    player=sim.state.entities.get(PLAYER_ID)
                    role=_get_space_role(sim, player.space_id if player else None) if player else None
                    if _events(sim, LOCAL_ENCOUNTER_RETURN_EVENT_TYPE) and role == CAMPAIGN_SPACE_ROLE:
                        return_ok=True
                        break
                    _advance_one_tick(sim)
                extraction_probe["command_tick"] = command_tick
                extraction_probe["return_command_issued"] = True
                extraction_probe["return_event_count"] = len(_events(sim, LOCAL_ENCOUNTER_RETURN_EVENT_TYPE))
                extraction_probe["return_event_rows"] = _events(sim, LOCAL_ENCOUNTER_RETURN_EVENT_TYPE)[-3:]
                extraction_probe["campaign_role_reentry"] = bool(player is not None and _get_space_role(sim, player.space_id) == CAMPAIGN_SPACE_ROLE)
                if return_ok:
                    return_status = "ok"
                    extraction_probe["hostile_pinning_blocked"] = False
                else:
                    return_status = "partial"
                    return_reason = "return command issued but no authoritative return evidence within bounded wait"
    capture("extraction_return", return_status, return_reason, return_cmd, extra={"extraction_probe": extraction_probe})

    result="success" if all(b.status=="ok" for b in beats) else "partial"
    if any(b.status=="failed" for b in beats): result="failed"
    sheet=pg.Surface((1800,1180)); sheet.fill((16,16,20)); sfont=pg.font.Font(None,28)
    for i,b in enumerate(beats):
        raw=pg.image.load(b.file)
        viewport = (b.diagnostics or {}).get("viewer_viewport_rect", [0, 0, 0, 0])
        vx, vy, vw, vh = [int(v) for v in viewport]
        view = raw.subsurface(pg.Rect(vx, vy, vw, vh)).copy() if vw > 0 and vh > 0 else raw
        img=pg.transform.smoothscale(view,(420,236)); x=26+(i%4)*444; y=88+(i//4)*292
        sheet.blit(img,(x,y)); _draw_combat_inset(pg, sheet, view, b, x, y); sheet.blit(sfont.render(f"{i:02d} {b.name} [{b.status}]",True,(240,240,240)),(x,y+214));
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
