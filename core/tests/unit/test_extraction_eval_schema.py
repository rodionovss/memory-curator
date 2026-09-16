import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmark.extraction.evaluator import validate_corpus, validate_predictions  # noqa: E402


VALID = {
    "sessions": [{
        "id": "session-1",
        "transcript": "user: a decision\nagent: evidence",
        "gold": [{
            "id": "knowledge-1",
            "type": "Reference",
            "title": "A reusable rule",
            "summary": "A rule that transfers to another task.",
            "evidence": "evidence",
            "scope": "general",
            "should_save": True,
        }],
    }],
}


def test_valid_corpus_has_no_validation_errors():
    assert validate_corpus(VALID) == []


def test_missing_session_id_is_reported():
    corpus = {"sessions": [{**VALID["sessions"][0], "id": ""}]}
    assert "id must be a non-empty string" in validate_corpus(corpus)[0]


def test_missing_gold_id_is_reported():
    item = {key: value for key, value in VALID["sessions"][0]["gold"][0].items() if key != "id"}
    corpus = {"sessions": [{**VALID["sessions"][0], "gold": [item]}]}
    assert any("sessions[0].gold[0].id is required" == error for error in validate_corpus(corpus))


def test_should_save_must_be_boolean():
    item = {**VALID["sessions"][0]["gold"][0], "should_save": "yes"}
    corpus = {"sessions": [{**VALID["sessions"][0], "gold": [item]}]}
    assert "should_save must be boolean" in validate_corpus(corpus)[0]


def test_prediction_requires_production_candidate_fields():
    prediction = {
        "session_id": "session-1",
        "title": "A reusable rule",
        "content_summary": "A transferable rule.",
        "type": "Reference",
        "tags": ["testing"],
    }
    assert validate_predictions([prediction]) == []

    missing_type = {key: value for key, value in prediction.items() if key != "type"}
    assert "type must be a non-empty string" in validate_predictions([missing_type])[0]


def test_prediction_tags_must_be_an_array_of_strings():
    prediction = {
        "session_id": "session-1",
        "title": "A reusable rule",
        "content_summary": "A transferable rule.",
        "type": "Reference",
        "tags": ["testing", 1],
    }
    errors = validate_predictions([prediction])
    assert "tags must be an array of strings" in errors[0]
