from __future__ import annotations

import json

from hexcrawler.cli.durability_audit import run_durability_audit


def test_durability_audit_writes_metrics_and_report(tmp_path) -> None:
    out = tmp_path / "durability"
    code = run_durability_audit(days=1, out_dir=str(out))
    assert code == 0
    assert (out / "DURABILITY_REPORT.md").exists()
    metrics = json.loads((out / "durability_metrics.json").read_text(encoding="utf-8"))
    assert metrics
    assert (out / "durability_summary.csv").exists()

