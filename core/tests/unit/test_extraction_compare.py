import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmark.extraction.compare_versions import compare_run_directory  # noqa: E402


def _prediction(session_id, title, gold_id):
        return {
        "session_id": session_id,
        "gold_id": gold_id,
        "type": "Reference",
        "title": title,
        "content_summary": "A transferable rule.",
        "tags": ["general"],
        "evidence": "The session explicitly confirms the rule.",
        "evaluation": {
            "evidence_supported": True,
            "abstract": True,
            "atomic": True,
            "labels": [],
        },
    }


def test_compare_run_directory_reports_each_version(tmp_path):
    gold_path = tmp_path / "gold.json"
    gold_path.write_text(json.dumps({
        "sessions": [{
            "id": "session-1",
            "transcript": "private",
            "gold": [{
                "id": "knowledge-1",
                "type": "Reference",
                "title": "Reusable rule",
                "summary": "A transferable rule.",
                "evidence": "Evidence.",
                "scope": "general",
                "should_save": True,
            }],
        }],
    }), encoding="utf-8")
    runs = tmp_path / "runs"
    runs.mkdir()
    for version in ("original", "experiment"):
        (runs / f"{version}.json").write_text(json.dumps({
            "schema_version": 2,
            "run_id": version,
            "version": version,
            "skill_version": version,
            "skill_commit": "abc",
            "session_id": "session-1",
            "session_hash": "sha256:test",
            "started_at": "2026-09-16T10:00:00Z",
            "decision": "rejected",
            "selected_candidate_ids": [],
            "rejection_reasons": {},
            "predictions": [_prediction("session-1", "Reusable rule", "knowledge-1")],
        }), encoding="utf-8")

    report = compare_run_directory(gold_path, runs)

    assert "| original |" in report
    assert "| experiment |" in report
    assert "100.0%" in report


def test_compare_run_directory_skips_legacy_records_without_evidence(tmp_path):
    gold_path = tmp_path / "gold.json"
    gold_path.write_text(json.dumps({"sessions": []}), encoding="utf-8")
    runs = tmp_path / "runs"
    runs.mkdir()
    (runs / "legacy.json").write_text(json.dumps({"version": "original"}), encoding="utf-8")

    try:
        compare_run_directory(gold_path, runs)
    except ValueError as error:
        assert "no current run records" in str(error)
    else:
        raise AssertionError("legacy-only directory must not produce a comparison")
