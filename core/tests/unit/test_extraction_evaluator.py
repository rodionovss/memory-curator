import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmark.extraction.evaluator import (  # noqa: E402
    calculate_metrics,
    match_predictions,
    render_report,
)


def gold_item(session_id, item_id, title, should_save=True):
    return {
        "session_id": session_id,
        "id": item_id,
        "type": "Reference",
        "title": title,
        "summary": "A reusable rule.",
        "evidence": "The evidence.",
        "scope": "general",
        "should_save": should_save,
    }


def prediction(session_id, title, **evaluation):
    gold_id = evaluation.pop("gold_id", None)
    labels = evaluation.pop("noise", None)
    result = {
        "session_id": session_id,
        "title": title,
        "content_summary": "A reusable rule.",
        "evidence": "The evidence.",
        "evaluation": evaluation,
    }
    if gold_id:
        result["gold_id"] = gold_id
    if labels is not None:
        result["evaluation"]["labels"] = labels
    return result


def test_perfect_match_by_explicit_id():
    gold = [gold_item("s1", "g1", "Reusable rule")]
    predictions = [prediction("s1", "Different title", gold_id="g1", evidence_supported=True, abstract=True, atomic=True)]

    result = match_predictions(gold, predictions)
    metrics = calculate_metrics(result, predictions)

    assert metrics["precision"] == 1.0
    assert metrics["recall"] == 1.0
    assert metrics["evidence_support_rate"] == 1.0


def test_title_match_is_limited_to_same_session():
    gold = [gold_item("s1", "g1", "Reusable rule")]
    predictions = [prediction("s2", "Reusable rule")]

    result = match_predictions(gold, predictions)

    assert result.matches == []
    assert len(result.unmatched_predictions) == 1
    assert len(result.unmatched_gold) == 1


def test_extra_prediction_and_missed_knowledge_reduce_scores():
    gold = [gold_item("s1", "g1", "Reusable rule")]
    predictions = [prediction("s1", "Task detail", noise=["task_residue"])]

    result = match_predictions(gold, predictions)
    metrics = calculate_metrics(result, predictions)

    assert metrics["precision"] == 0.0
    assert metrics["recall"] == 0.0
    assert metrics["noise_rate"] == 1.0


def test_negative_gold_is_not_counted_as_recall():
    gold = [gold_item("s1", "g1", "Task detail", should_save=False)]
    predictions = [prediction("s1", "Task detail", gold_id="g1", noise=["task_residue"])]

    result = match_predictions(gold, predictions)
    metrics = calculate_metrics(result, predictions)

    assert len(result.negative_matches) == 1
    assert metrics["recall"] == 0.0
    assert metrics["negative_matches"] == 1.0


def test_duplicate_predictions_match_gold_once():
    gold = [gold_item("s1", "g1", "Reusable rule")]
    predictions = [prediction("s1", "Reusable rule"), prediction("s1", "Reusable rule")]

    result = match_predictions(gold, predictions)

    assert len(result.matches) == 1
    assert len(result.unmatched_predictions) == 1


def test_empty_eval_is_stable():
    result = match_predictions([], [])
    metrics = calculate_metrics(result, [])

    assert metrics["precision"] == 0.0
    assert metrics["recall"] == 0.0
    assert "# Extraction Eval Report" in render_report(metrics, result)


def test_report_contains_error_label_counts():
    gold = [gold_item("s1", "g1", "Reusable rule")]
    predictions = [prediction("s1", "Task detail", noise=["task_residue"])]
    result = match_predictions(gold, predictions)
    metrics = calculate_metrics(result, predictions)

    assert "| task_residue | 1 |" in render_report(metrics, result)
