import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
RUNNER = ROOT / "benchmark" / "extraction" / "run_eval.py"


def test_cli_writes_report(tmp_path):
    gold = tmp_path / "gold.json"
    predictions = tmp_path / "predictions.json"
    report = tmp_path / "report.md"
    gold.write_text(json.dumps({"sessions": [{
        "id": "s1",
        "transcript": "anonymous",
        "gold": [{
            "id": "g1", "type": "Reference", "title": "Reusable rule",
            "summary": "Summary", "evidence": "Evidence", "scope": "general",
            "should_save": True,
        }],
        }]}), encoding="utf-8")
    predictions.write_text(json.dumps([{
        "session_id": "s1", "gold_id": "g1", "type": "Reference",
        "title": "Reusable rule", "tags": ["general"],
        "content_summary": "Summary", "evaluation": {
            "evidence_supported": True, "abstract": True, "atomic": True,
        },
    }]), encoding="utf-8")

    completed = subprocess.run(
        [sys.executable, str(RUNNER), "--gold", str(gold), "--predictions", str(predictions), "--report", str(report)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0
    assert "Precision | 100.0%" in report.read_text(encoding="utf-8")


def test_cli_returns_2_for_invalid_json(tmp_path):
    gold = tmp_path / "gold.json"
    predictions = tmp_path / "predictions.json"
    report = tmp_path / "report.md"
    gold.write_text("{broken", encoding="utf-8")
    predictions.write_text("[]", encoding="utf-8")

    completed = subprocess.run(
        [sys.executable, str(RUNNER), "--gold", str(gold), "--predictions", str(predictions), "--report", str(report)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 2
    assert "validation error" in completed.stderr
