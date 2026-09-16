#!/usr/bin/env python3
"""Run extraction metrics without importing the curator development package."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from benchmark.extraction.evaluator import (  # noqa: E402
    _flatten_gold,
    calculate_metrics,
    load_records,
    match_predictions,
    render_report,
    validate_corpus,
    validate_predictions,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold", required=True, help="gold corpus JSON")
    parser.add_argument("--predictions", required=True, help="predictions JSON")
    parser.add_argument("--report", required=True, help="output Markdown report")
    args = parser.parse_args(argv)

    try:
        corpus = load_records(args.gold)
        predictions = load_records(args.predictions)
        errors = validate_corpus(corpus) + validate_predictions(predictions)
        if errors:
            raise ValueError("; ".join(errors))
        gold = _flatten_gold(corpus)
        result = match_predictions(gold, predictions)
        metrics = calculate_metrics(result, predictions)
        report_path = Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(render_report(metrics, result), encoding="utf-8")
    except ValueError as exc:
        print(f"validation error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
