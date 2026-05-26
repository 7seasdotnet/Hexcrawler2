from pathlib import Path

from hexcrawler.cli.visual_audit import (
    DEFAULT_OUT,
    _advance_one_tick,
    _build_local_entity_probe,
    _get_space_role,
    _select_local_attack_targets,
    _write_report,
)
from hexcrawler.sim.core import EntityState
from hexcrawler.sim.world import CAMPAIGN_SPACE_ROLE, LOCAL_SPACE_ROLE, SpaceState
from hexcrawler.cli.play import _build_parser


class _SimAdvanceRecorder:
    def __init__(self) -> None:
        self.calls: list[int] = []

    def advance_ticks(self, ticks: int) -> None:
        self.calls.append(ticks)


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
