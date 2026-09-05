"""Тесты телеметрии кандидатов: предложил / сохранил / отказал + причина."""

from curator.models import ProposedFact
from curator import candidates_log


def _fact(title="JvmInline в sealed interface", ftype="Reference"):
    return ProposedFact(type=ftype, title=title, content_summary="суть",
                        tags=["kotlin"], evidence="")


class TestLogCapture:
    def test_entry_written(self):
        candidates = [
            (_fact("Сохранится"), "approved", ""),
            (_fact("Дубликат"), "rejected", "Дубликат: уже есть 'X'"),
        ]
        candidates_log.log_capture("mining", candidates, saved=1,
                                   final_status="hypothesis", session_id="ses_1")
        entries = candidates_log.read_entries()
        assert len(entries) == 1
        e = entries[0]
        assert e["source"] == "mining"
        assert e["session"] == "ses_1"
        assert e["proposed"] == 2
        assert e["saved"] == 1
        assert e["final_status"] == "hypothesis"
        assert e["candidates"][1]["reason"] == "Дубликат: уже есть 'X'"

    def test_human_decline_recorded(self):
        candidates_log.log_capture("cli", [(_fact(), "approved", "")], saved=0,
                                   final_status="verified", declined_by_human=True)
        e = candidates_log.read_entries()[-1]
        assert e["declined_by_human"] is True

    def test_broken_lines_skipped(self, tmp_path, monkeypatch):
        log = tmp_path / "candidates.jsonl"
        log.write_text("не json\n", encoding="utf-8")
        monkeypatch.setenv("CURATOR_CANDIDATES_PATH", str(log))
        candidates_log.log_capture("cli", [(_fact(), "approved", "")], saved=1,
                                   final_status="verified")
        entries = candidates_log.read_entries()
        assert len(entries) == 1  # битая строка не в счёт

    def test_logging_failure_does_not_raise(self, monkeypatch):
        # Недоступный путь — телеметрия глушится, capture продолжается
        monkeypatch.setenv("CURATOR_CANDIDATES_PATH", "/dev/null/не/существует/ф.jsonl")
        candidates_log.log_capture("cli", [(_fact(), "approved", "")], saved=1,
                                   final_status="verified")


class TestPrecisionStats:
    def test_aggregation(self, monkeypatch, tmp_path):
        monkeypatch.setenv("CURATOR_CANDIDATES_PATH", str(tmp_path / "candidates.jsonl"))
        # Вызов 1: майнинг, 3 предложено, 1 дубликат, 2 сохранено как hypothesis
        candidates_log.log_capture("mining", [
            (_fact("A"), "approved", ""),
            (_fact("B"), "approved", ""),
            (_fact("C"), "rejected", "Дубликат: уже есть 'A'"),
        ], saved=2, final_status="hypothesis", session_id="ses_1")
        # Вызов 2: CLI, 1 предложено, человек отказал
        candidates_log.log_capture("cli", [(_fact("D", "Style"), "approved", "")],
                                   saved=0, final_status="verified",
                                   declined_by_human=True)

        stats = candidates_log.precision_stats()
        assert stats["calls"] == 2
        assert stats["proposed"] == 4
        assert stats["saved"] == 2
        assert stats["rejected_by_gatekeeper"] == 1
        assert stats["declined_by_human"] == 1
        assert stats["precision_pct"] == 50.0
        assert stats["by_reason"]["Дубликат"] == 1
        assert stats["by_source"] == {"mining": 1, "cli": 1}
        assert stats["by_type_approved"] == {"Reference": 2, "Style": 1}

    def test_empty_log(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CURATOR_CANDIDATES_PATH", str(tmp_path / "none.jsonl"))
        stats = candidates_log.precision_stats()
        assert stats["calls"] == 0
        assert stats["precision_pct"] == 0.0
