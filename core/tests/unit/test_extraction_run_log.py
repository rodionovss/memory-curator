import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmark.extraction.run_log import write_run_record  # noqa: E402


def _record(**overrides):
    record = {
        "run_id": "run-1",
        "version": "original",
        "skill_version": "0.1.0-original",
        "skill_commit": "8e912f7",
        "session_id": "session-1",
        "session_hash": "sha256:abc",
        "started_at": "2026-09-16T10:00:00Z",
        "decision": "rejected",
        "selected_candidate_ids": [],
        "rejection_reasons": {"fact_1": "task_residue"},
        "predictions": [{
            "session_id": "session-1",
            "type": "Reference",
            "title": "Reusable rule",
            "content_summary": "A transferable rule.",
            "tags": ["general"],
            "evaluation": {
                "evidence_supported": True,
                "abstract": True,
                "atomic": True,
                "labels": [],
            },
        }],
    }
    record.update(overrides)
    return record


def test_write_run_record_persists_version_and_decision(tmp_path):
    path = tmp_path / "runs" / "run-1.json"

    write_run_record(path, _record())

    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["version"] == "original"
    assert saved["decision"] == "rejected"
    assert saved["rejection_reasons"] == {"fact_1": "task_residue"}
    assert "transcript" not in saved


def test_write_run_record_rejects_private_transcript(tmp_path):
    record = _record(transcript="private text")

    try:
        write_run_record(tmp_path / "run.json", record)
    except ValueError as error:
        assert "transcript" in str(error)
    else:
        raise AssertionError("private transcript must not be written to run log")
