"""Deterministic metrics for evaluating curator-save predictions.

This module deliberately does not infer semantic quality. A human or an
external evaluator must provide the optional ``evaluation`` annotations on
predictions for evidence, abstraction, atomicity, and error labels.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


POSITIVE_LABEL = "should_save"


@dataclass(frozen=True)
class Match:
    session_id: str
    gold_id: str
    prediction_index: int


@dataclass
class MatchResult:
    matches: list[Match] = field(default_factory=list)
    unmatched_gold: list[dict[str, Any]] = field(default_factory=list)
    unmatched_predictions: list[dict[str, Any]] = field(default_factory=list)
    negative_matches: list[dict[str, Any]] = field(default_factory=list)


def load_records(path: str) -> Any:
    """Load JSON data and raise a readable ValueError for malformed input."""
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in {path}: {exc.msg}") from exc


def validate_corpus(corpus: Any) -> list[str]:
    errors: list[str] = []
    sessions = corpus.get("sessions") if isinstance(corpus, dict) else None
    if not isinstance(sessions, list):
        return ["corpus.sessions must be an array"]

    seen_sessions: set[str] = set()
    seen_gold: set[tuple[str, str]] = set()
    for session_index, session in enumerate(sessions):
        prefix = f"sessions[{session_index}]"
        if not isinstance(session, dict):
            errors.append(f"{prefix} must be an object")
            continue
        session_id = session.get("id")
        if not isinstance(session_id, str) or not session_id.strip():
            errors.append(f"{prefix}.id must be a non-empty string")
            continue
        if session_id in seen_sessions:
            errors.append(f"{prefix}.id is duplicated: {session_id}")
        seen_sessions.add(session_id)
        if not isinstance(session.get("transcript"), str):
            errors.append(f"{prefix}.transcript must be a string")
        gold = session.get("gold")
        if not isinstance(gold, list):
            errors.append(f"{prefix}.gold must be an array")
            continue
        for gold_index, item in enumerate(gold):
            item_prefix = f"{prefix}.gold[{gold_index}]"
            if not isinstance(item, dict):
                errors.append(f"{item_prefix} must be an object")
                continue
            required = ("id", "type", "title", "summary", "evidence", "scope", "should_save")
            for key in required:
                if key not in item:
                    errors.append(f"{item_prefix}.{key} is required")
            item_id = item.get("id")
            if not isinstance(item_id, str) or not item_id.strip():
                errors.append(f"{item_prefix}.id must be a non-empty string")
            elif (session_id, item_id) in seen_gold:
                errors.append(f"{item_prefix}.id is duplicated: {item_id}")
            else:
                seen_gold.add((session_id, item_id))
            if not isinstance(item.get("should_save"), bool):
                errors.append(f"{item_prefix}.should_save must be boolean")
    return errors


def validate_predictions(predictions: Any) -> list[str]:
    if not isinstance(predictions, list):
        return ["predictions must be an array"]
    errors: list[str] = []
    for index, prediction in enumerate(predictions):
        prefix = f"predictions[{index}]"
        if not isinstance(prediction, dict):
            errors.append(f"{prefix} must be an object")
            continue
        for key in ("session_id", "type", "title", "content_summary"):
            if not isinstance(prediction.get(key), str) or not prediction[key].strip():
                errors.append(f"{prefix}.{key} must be a non-empty string")
        tags = prediction.get("tags")
        if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
            errors.append(f"{prefix}.tags must be an array of strings")
        evaluation = prediction.get("evaluation", {})
        if not isinstance(evaluation, dict):
            errors.append(f"{prefix}.evaluation must be an object")
        if "labels" in evaluation and not isinstance(evaluation["labels"], list):
            errors.append(f"{prefix}.evaluation.labels must be an array")
    return errors


def _normalise_title(value: str) -> str:
    value = value.casefold().replace("ё", "е")
    return re.sub(r"[^\w\s]", " ", value, flags=re.UNICODE).strip()


def _flatten_gold(corpus: dict[str, Any]) -> list[dict[str, Any]]:
    result = []
    for session in corpus["sessions"]:
        for item in session["gold"]:
            result.append({**item, "session_id": session["id"]})
    return result


def match_predictions(gold: list[dict[str, Any]], predictions: list[dict[str, Any]]) -> MatchResult:
    result = MatchResult()
    used_gold: set[tuple[str, str]] = set()
    for index, prediction in enumerate(predictions):
        session_id = prediction["session_id"]
        explicit_id = prediction.get("gold_id")
        candidates = [
            item for item in gold
            if item["session_id"] == session_id
            and (session_id, item["id"]) not in used_gold
            and (
                explicit_id == item["id"]
                or (
                    not explicit_id
                    and item["should_save"]
                    and _normalise_title(item["title"]) == _normalise_title(prediction["title"])
                )
            )
        ]
        if candidates:
            item = candidates[0]
            used_gold.add((session_id, item["id"]))
            if item["should_save"]:
                result.matches.append(Match(session_id, item["id"], index))
            else:
                result.negative_matches.append(prediction)
        else:
            result.unmatched_predictions.append(prediction)

    result.unmatched_gold = [
        item for item in gold
        if item["should_save"] and (item["session_id"], item["id"]) not in used_gold
    ]
    return result


def _prediction_by_index(result: MatchResult, predictions: list[dict[str, Any]], index: int) -> dict[str, Any]:
    return predictions[index]


def calculate_metrics(result: MatchResult, predictions: list[dict[str, Any]]) -> dict[str, float]:
    prediction_count = len(predictions)
    positive_gold_count = len(result.matches) + len(result.unmatched_gold)
    matched_count = len(result.matches)
    annotated = [
        _prediction_by_index(result, predictions, match.prediction_index)
        for match in result.matches
    ]

    def rate(key: str) -> float:
        values = [p["evaluation"][key] for p in annotated if key in p.get("evaluation", {})]
        return sum(bool(value) for value in values) / len(values) if values else 0.0

    labelled_noise = sum(
        bool(p.get("evaluation", {}).get("labels"))
        for p in predictions
    )
    return {
        "precision": matched_count / prediction_count if prediction_count else 0.0,
        "recall": matched_count / positive_gold_count if positive_gold_count else 0.0,
        "evidence_support_rate": rate("evidence_supported"),
        "abstraction_rate": rate("abstract"),
        "atomicity_rate": rate("atomic"),
        "noise_rate": labelled_noise / prediction_count if prediction_count else 0.0,
        "predictions": float(prediction_count),
        "matched": float(matched_count),
        "missed": float(len(result.unmatched_gold)),
        "negative_matches": float(len(result.negative_matches)),
    }


def render_report(metrics: dict[str, float], result: MatchResult) -> str:
    def percent(value: float) -> str:
        return f"{value * 100:.1f}%"

    lines = [
        "# Extraction Eval Report",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| Precision | {percent(metrics['precision'])} |",
        f"| Recall | {percent(metrics['recall'])} |",
        f"| Evidence support | {percent(metrics['evidence_support_rate'])} |",
        f"| Abstraction | {percent(metrics['abstraction_rate'])} |",
        f"| Atomicity | {percent(metrics['atomicity_rate'])} |",
        f"| Noise | {percent(metrics['noise_rate'])} |",
        "",
        f"Predictions: {int(metrics['predictions'])}",
        f"Matched: {int(metrics['matched'])}",
        f"Missed: {int(metrics['missed'])}",
        f"Predictions matched to negative gold: {int(metrics['negative_matches'])}",
    ]
    labels = Counter(
        label
        for prediction in result.unmatched_predictions + result.negative_matches
        for label in prediction.get("evaluation", {}).get("labels", [])
    )
    if labels:
        lines.extend(["", "## Error Labels", "", "| Label | Count |", "|---|---:|"])
        lines.extend(f"| {label} | {count} |" for label, count in sorted(labels.items()))
    return "\n".join(lines) + "\n"
