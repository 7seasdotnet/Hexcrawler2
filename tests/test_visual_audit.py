from pathlib import Path

from hexcrawler.cli.visual_audit import DEFAULT_OUT, _write_report
from hexcrawler.cli.play import _build_parser


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
