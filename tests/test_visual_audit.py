from pathlib import Path

from hexcrawler.cli.visual_audit import (
    DEFAULT_OUT,
    _advance_one_tick,
    _build_local_entity_probe,
    _find_local_return_context,
    _distance_to_return_exit,
    _at_return_exit,
    _player_local_coord,
    _get_space_role,
    _select_local_attack_targets,
    _write_report,
    _extract_cue_timeline,
)
from hexcrawler.sim.core import EntityState
from hexcrawler.sim.world import CAMPAIGN_SPACE_ROLE, LOCAL_SPACE_ROLE, SpaceState
from hexcrawler.cli.play import _build_parser


class _SimAdvanceRecorder:
    def __init__(self) -> None:
        self.calls: list[int] = []

    def advance_ticks(self, ticks: int) -> None:
        self.calls.append(ticks)



def test_visual_audit_cue_timeline_preserves_render_failure_and_weapon_diagnostics() -> None:
    diag = {
        "cue_count": 1,
        "active_cue_ids": ["52:scout:hostile"],
        "cue_rendered": True,
        "cue_render_failure_reason": None,
        "refresh_diagnostics": {"authoritative_evidence_count": 1, "generated_cue_count": 1},
        "rendered_cues": [
            {
                "phase": "impact",
                "age_ticks": 5,
                "attacker_id": "scout",
                "target_id": "hostile",
                "outcome_label": "WOUNDED",
                "evidence_source": "combat_log",
                "evidence_reason": "resolved",
                "evidence_applied": True,
                "weapon_profile_id": "default_melee",
                "motion_family": "slash",
                "attacker_screen_pos": {"x": 10, "y": 11},
                "target_screen_pos": {"x": 20, "y": 21},
                "arc_bbox": {"x": 1, "y": 2, "w": 3, "h": 4},
                "impact_bbox": {"x": 5, "y": 6, "w": 7, "h": 8},
                "motion_primitive": "arc",
                "weapon_motion_primitive": "arc",
                "motion_points": [{"x": 10, "y": 11}, {"x": 12, "y": 13}, {"x": 15, "y": 14}, {"x": 18, "y": 17}, {"x": 20, "y": 21}],
                "motion_stroke_width": 3,
                "arc_origin_actor_id": "scout",
                "arc_target_id": "hostile",
                "arc_committed_facing": {"x": 1.0, "y": 0.0},
                "actor_marker_layer_above_weapon_cue": True,
                "target_marker_remains_visible": True,
                "actor_marker_visible": True,
                "target_marker_visible": True,
                "large_impact_blob_detected": False,
                "badge_text": "WOUNDED",
                "badge_screen_pos": {"x": 20, "y": -10},
                "render_layer_used": "combat_cues_overlay",
            }
        ],
    }

    timeline = _extract_cue_timeline(diag)

    assert timeline["cue_rendered"] is True
    assert timeline["cue_count"] == 1
    assert timeline["evidence_source"] == "combat_log"
    assert timeline["evidence_reason"] == "resolved"
    assert timeline["weapon_profile_id"] == "default_melee"
    assert timeline["motion_family"] == "slash"
    assert timeline["motion_primitive"] == "arc"
    assert timeline["weapon_motion_primitive"] == "arc"
    assert timeline["arc_origin_actor_id"] == "scout"
    assert timeline["arc_target_id"] == "hostile"
    assert timeline["arc_committed_facing"] == {"x": 1.0, "y": 0.0}
    assert timeline["target_marker_remains_visible"] is True
    assert timeline["target_marker_visible"] is True
    assert timeline["actor_marker_layer_above_weapon_cue"] is True
    assert timeline["large_impact_blob_detected"] is False
    assert timeline["refresh_diagnostics"]["authoritative_evidence_count"] == 1

def test_visual_audit_default_out() -> None:
    parser = _build_parser()
    args = parser.parse_args([])
    assert args.out == str(DEFAULT_OUT)


def test_visual_audit_report_writer(tmp_path: Path, monkeypatch) -> None:
    import hexcrawler.cli.visual_audit as mod

    report_path = tmp_path / "AI_VISUAL_AUDIT_REPORT.md"
    monkeypatch.setattr(mod, "REPORT_PATH", report_path)
    _write_report("cmd", "ts", "abc", [], "available", "success")
    assert report_path.exists()
    text = report_path.read_text(encoding="utf-8")
    assert "Upload docs/ai_playtest/AI_VISUAL_AUDIT_CONTACT_SHEET.png to ChatGPT for visual critique." in text


def test_visual_audit_report_writer_records_runtime_blocker(tmp_path: Path, monkeypatch) -> None:
    import hexcrawler.cli.visual_audit as mod

    report_path = tmp_path / "AI_VISUAL_AUDIT_REPORT.md"
    monkeypatch.setattr(mod, "REPORT_PATH", report_path)
    _write_report("cmd", "ts", "abc", [], "available", "runtime_exception", blockers=["audit runtime exception: AttributeError"]) 

    text = report_path.read_text(encoding="utf-8")
    assert "Result: runtime_exception" in text
    assert "audit runtime exception: AttributeError" in text
    assert "Known Blockers" in text


def test_advance_one_tick_uses_authoritative_advance_ticks_api() -> None:
    sim = _SimAdvanceRecorder()

    _advance_one_tick(sim)

    assert sim.calls == [1]


def test_get_space_role_reads_canonical_space_state_role() -> None:
    class _World:
        def __init__(self) -> None:
            self.spaces = {"overworld": SpaceState(space_id="overworld", topology_type="hex", role=CAMPAIGN_SPACE_ROLE), "local:test": SpaceState(space_id="local:test", topology_type="square_grid", role=LOCAL_SPACE_ROLE, topology_params={"width": 2, "height": 2})}

    class _State:
        def __init__(self) -> None:
            self.world = _World()

    class _Sim:
        def __init__(self) -> None:
            self.state = _State()

    sim = _Sim()
    assert _get_space_role(sim, "overworld") == CAMPAIGN_SPACE_ROLE
    assert _get_space_role(sim, "local:test") == LOCAL_SPACE_ROLE
    assert _get_space_role(sim, "missing") is None


def test_visual_audit_report_writer_failed_result_does_not_report_none_blocker(tmp_path: Path, monkeypatch) -> None:
    import hexcrawler.cli.visual_audit as mod

    report_path = tmp_path / "AI_VISUAL_AUDIT_REPORT.md"
    monkeypatch.setattr(mod, "REPORT_PATH", report_path)
    _write_report("cmd", "ts", "abc", [], "available", "failed")

    text = report_path.read_text(encoding="utf-8")
    assert "Result: failed" in text
    assert "None recorded." not in text
    assert "Audit failed before blockers were fully recorded." in text


def test_visual_audit_target_discovery_uses_canonical_hostile_fields() -> None:
    class _State:
        def __init__(self) -> None:
            self.entities = {
                "scout": EntityState(entity_id="scout", position_x=0.0, position_y=0.0, space_id="local:a"),
                "encounter_participant:1": EntityState(
                    entity_id="encounter_participant:1",
                    position_x=1.0,
                    position_y=0.0,
                    space_id="local:a",
                    template_id="encounter_hostile_v1",
                ),
                "transition_marker": EntityState(entity_id="transition_marker", position_x=0.5, position_y=0.5, space_id="local:a"),
            }

    class _Sim:
        def __init__(self) -> None:
            self.state = _State()

    sim = _Sim()
    player = sim.state.entities["scout"]
    targets = _select_local_attack_targets(sim, player)
    assert [row["entity"].entity_id for row in targets] == ["encounter_participant:1"]


def test_local_entity_probe_records_rejection_reasons() -> None:
    class _State:
        def __init__(self) -> None:
            self.entities = {
                "scout": EntityState(entity_id="scout", position_x=0.0, position_y=0.0, space_id="local:a"),
                "neutral": EntityState(entity_id="neutral", position_x=1.0, position_y=0.0, space_id="local:a"),
                "hostile_dead": EntityState(
                    entity_id="hostile_dead",
                    position_x=2.0,
                    position_y=0.0,
                    space_id="local:a",
                    template_id="encounter_hostile_v1",
                    wounds=[{"severity": 4, "region": "torso"}],
                ),
            }

    class _Sim:
        def __init__(self) -> None:
            self.state = _State()

    sim = _Sim()
    probe = _build_local_entity_probe(sim, sim.state.entities["scout"])
    by_id = {row["entity_id"]: row for row in probe["entities"]}
    assert "player_self" in by_id["scout"]["target_selection_reasons"]
    assert "not_hostile_marker" in by_id["neutral"]["target_selection_reasons"]
    assert "incapacitated" in by_id["hostile_dead"]["target_selection_reasons"]


def test_find_local_return_context_reads_existing_active_context() -> None:
    class _Sim:
        class _State:
            class _Entities(dict):
                pass
            entities = {"scout": EntityState(entity_id="scout", position_x=0.0, position_y=0.0, space_id="local:a")}
        state = _State()

        def get_rules_state(self, name: str):
            assert name == "local_encounter_instance"
            return {"active_by_local_space": {"local:a": {"return_exit_coord": {"x": 1, "y": 2}}}}

    sim = _Sim()
    player = sim.state.entities["scout"]
    context = _find_local_return_context(sim, player)
    assert context is not None
    assert context["return_exit_coord"] == {"x": 1, "y": 2}


def test_distance_to_return_exit_returns_none_without_coord() -> None:
    class _State:
        entities = {"scout": EntityState(entity_id="scout", position_x=0.0, position_y=0.0, space_id="local:a")}
        class _World:
            spaces = {}
        world = _World()

    class _Sim:
        state = _State()

    sim = _Sim()
    player = sim.state.entities["scout"]
    assert _distance_to_return_exit(sim, player, None) is None


def test_distance_to_return_exit_uses_canonical_square_grid_world_mapping() -> None:
    class _State:
        entities = {"scout": EntityState(entity_id="scout", position_x=2.5, position_y=3.5, space_id="local:a")}
        class _World:
            spaces = {}
        world = _World()

    class _Sim:
        state = _State()

    sim = _Sim()
    player = sim.state.entities["scout"]
    assert _distance_to_return_exit(sim, player, {"x": 2, "y": 3}) == 0.0


def test_at_return_exit_uses_cell_semantics_not_visual_distance() -> None:
    class _Sim:
        class _State:
            entities = {"scout": EntityState(entity_id="scout", position_x=2.99, position_y=3.99, space_id="local:a")}
        state = _State()

        class _Ref:
            coord = {"x": 2, "y": 3}

        def _entity_location_ref(self, entity):
            return self._Ref()

    sim = _Sim()
    player = sim.state.entities["scout"]
    assert _player_local_coord(sim, player) == {"x": 2, "y": 3}
    assert _at_return_exit(sim, player, {"x": 2, "y": 3}) is True

def test_melee_readability_script_uses_dedicated_default_artifact_path() -> None:
    import hexcrawler.cli.visual_audit as mod

    assert str(mod.MELEE_READABILITY_OUT) == "docs/ai_playtest/melee_readability/latest"
    assert mod.MELEE_READABILITY_SCRIPT == "melee_readability_proving_ground"
