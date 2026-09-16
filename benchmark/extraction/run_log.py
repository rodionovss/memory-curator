"""Local run-log writer for curator-save A/B experiments.

Run records intentionally contain candidates and decisions, but never session
transcripts. The directory is ignored by git because it can contain private
knowledge and user decisions.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from benchmark.extraction.evaluator import validate_predictions


REQUIRED_FIELDS = (
    "schema_version",
    "run_id",
    "version",
    "skill_version",
    "skill_commit",
    "session_id",
    "session_hash",
    "started_at",
    "decision",
    "selected_candidate_ids",
    "rejection_reasons",
    "predictions",
)
DECISIONS = {"rejected", "approved", "cancelled", "error"}


def validate_run_record(record: Any) -> list[str]:
    if not isinstance(record, dict):
        return ["run record must be an object"]
    errors = [f"{field} is required" for field in REQUIRED_FIELDS if field not in record]
    if record.get("schema_version") != 2:
        errors.append("schema_version must be 2")
    if "transcript" in record:
        errors.append("transcript must not be stored in a run record")
    if record.get("decision") not in DECISIONS:
        errors.append(f"decision must be one of {sorted(DECISIONS)}")
    if not isinstance(record.get("selected_candidate_ids"), list):
        errors.append("selected_candidate_ids must be an array")
    if not isinstance(record.get("rejection_reasons"), dict):
        errors.append("rejection_reasons must be an object")
    if "predictions" in record:
        errors.extend(validate_predictions(record["predictions"]))
        for index, prediction in enumerate(record["predictions"]):
            if not isinstance(prediction.get("evidence"), str) or not prediction["evidence"].strip():
                errors.append(f"predictions[{index}].evidence must be a non-empty string")
    return errors


def write_run_record(path: str | Path, record: dict[str, Any]) -> None:
    errors = validate_run_record(record)
    if errors:
        raise ValueError("; ".join(errors))
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write a local curator-save A/B run record")
    parser.add_argument("--path", required=True, help="JSON output path")
    args = parser.parse_args(argv)
    try:
        record = json.load(sys.stdin)
        write_run_record(args.path, record)
    except (json.JSONDecodeError, ValueError) as error:
        print(f"validation error: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
