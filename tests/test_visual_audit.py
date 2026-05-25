from pathlib import Path

from hexcrawler.cli.visual_audit import DEFAULT_OUT, _advance_one_tick, _write_report
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
