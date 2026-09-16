"""Compare original and experiment curator-save run logs."""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from benchmark.extraction.evaluator import (
    calculate_metrics,
    load_records,
    match_predictions,
    validate_corpus,
)
from benchmark.extraction.run_log import validate_run_record


METRIC_COLUMNS = (
    "precision",
    "recall",
    "evidence_support_rate",
    "abstraction_rate",
    "atomicity_rate",
    "noise_rate",
)


def _percent(value: float) -> str:
    return f"{value * 100:.1f}%"


def _load_runs(directory: Path) -> tuple[dict[str, list[dict[str, Any]]], list[str]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    legacy: list[str] = []
    for path in sorted(directory.glob("*.json")):
        record = load_records(str(path))
        if isinstance(record, dict) and "schema_version" not in record:
            legacy.append(path.name)
            continue
        errors = validate_run_record(record)
        if errors:
            raise ValueError(f"{path}: {'; '.join(errors)}")
        grouped[record["version"]].append(record)
    if not grouped:
        raise ValueError(f"no current run records found in {directory}; legacy files: {legacy}")
    return grouped, legacy


def compare_run_directory(gold_path: str | Path, runs_directory: str | Path) -> str:
    corpus = load_records(str(gold_path))
    corpus_errors = validate_corpus(corpus)
    if corpus_errors:
        raise ValueError("; ".join(corpus_errors))
    gold = [
        {**item, "session_id": session["id"]}
        for session in corpus["sessions"]
        for item in session["gold"]
    ]
    grouped, legacy = _load_runs(Path(runs_directory))

    lines = [
        "# Curator Save Version Comparison",
        "",
        "| Version | Skill version | Commit | Runs | Predictions | Precision | Recall | Evidence | Abstraction | Atomicity | Noise |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for version, records in sorted(grouped.items()):
        predictions = [prediction for record in records for prediction in record["predictions"]]
        result = match_predictions(gold, predictions)
        metrics = calculate_metrics(result, predictions)
        skill_versions = sorted({record["skill_version"] for record in records})
        commits = sorted({record["skill_commit"] for record in records})
        lines.append(
            "| {version} | {skill_version} | {commit} | {runs} | {predictions} | {precision} | "
            "{recall} | {evidence} | {abstraction} | {atomicity} | {noise} |".format(
                version=version,
                skill_version=", ".join(skill_versions),
                commit=", ".join(commits),
                runs=len(records),
                predictions=int(metrics["predictions"]),
                precision=_percent(metrics["precision"]),
                recall=_percent(metrics["recall"]),
                evidence=_percent(metrics["evidence_support_rate"]),
                abstraction=_percent(metrics["abstraction_rate"]),
                atomicity=_percent(metrics["atomicity_rate"]),
                noise=_percent(metrics["noise_rate"]),
            )
        )
    lines.extend([
        "",
        "Metrics are computed against the same gold corpus. Run records contain",
        "candidates and decisions, but never session transcripts.",
    ])
    if legacy:
        lines.extend([
            "",
            "Legacy run records skipped (missing schema v2/evidence): "
            + ", ".join(legacy),
        ])
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compare curator-save A/B run logs")
    parser.add_argument("--gold", required=True)
    parser.add_argument("--runs", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args(argv)
    try:
        report = compare_run_directory(args.gold, args.runs)
        Path(args.report).write_text(report, encoding="utf-8")
    except (OSError, ValueError) as error:
        print(f"validation error: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
