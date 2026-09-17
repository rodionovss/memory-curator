"""Тесты CLI cmd_save: статус hypothesis для майнинга + телеметрия кандидатов."""

import json

import pytest

import curator.control as control
from curator.backend.local import LocalBackend
from curator.models import FactQuery


CANDIDATES = [{
    "type": "Reference",
    "title": "Cursor-based пагинация для стримов",
    "content_summary": "Стабильный порядок — offset, меняющиеся данные — cursor.",
    "tags": ["pagination", "api"],
    "evidence": "сессия про выбор пагинации",
}]


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("CURATOR_DB_PATH", str(tmp_path / "knowledge.db"))
    monkeypatch.setenv("CURATOR_BASE_DIR", str(tmp_path / "learnings"))
    monkeypatch.setenv("CURATOR_USAGE_PATH", str(tmp_path / "usage.json"))
    return tmp_path


class TestSaveHypothesis:
    def test_hypothesis_flag_stores_as_hypothesis(self, env, capsys):
        control.cmd_save(auto_yes=True, hypothesis=True, session_id="ses_1",
                         raw=json.dumps(CANDIDATES))
        out = capsys.readouterr().out
        assert "статус: hypothesis" in out

        backend = LocalBackend(str(env / "knowledge.db"))
        facts = backend.query_facts(FactQuery(search="Cursor-based"))
        assert len(facts) == 1
        assert facts[0].status == "hypothesis"

    def test_default_save_is_verified(self, env, capsys):
        control.cmd_save(auto_yes=True, raw=json.dumps(CANDIDATES))
        backend = LocalBackend(str(env / "knowledge.db"))
        facts = backend.query_facts(FactQuery(search="Cursor-based"))
        assert facts[0].status == "verified"

    def test_writeback_md_contains_hypothesis_status(self, env, capsys):
        control.cmd_save(auto_yes=True, hypothesis=True, session_id="ses_1",
                         raw=json.dumps(CANDIDATES))
        md_files = list((env / "learnings").rglob("*.md"))
        assert md_files, "write-back должен создать .md"
        content = "\n".join(p.read_text(encoding="utf-8") for p in md_files)
        assert "Cursor-based" in content
        assert "Гипотеза" in content  # лейбл статуса hypothesis в .md

    def test_candidates_log_written_on_save(self, env, capsys):
        control.cmd_save(auto_yes=True, hypothesis=True, session_id="ses_1",
                         raw=json.dumps(CANDIDATES))
        from curator import candidates_log
        entries = candidates_log.read_entries()
        assert len(entries) == 1
        e = entries[0]
        assert e["source"] == "mining"  # --session → источник mining
        assert e["session"] == "ses_1"
        assert e["saved"] == 1
        assert e["final_status"] == "hypothesis"

    def test_human_decline_logs_zero_saved(self, env, capsys, monkeypatch):
        monkeypatch.setattr("builtins.input", lambda: "n")
        control.cmd_save(auto_yes=False, raw=json.dumps(CANDIDATES))
        from curator import candidates_log
        entries = candidates_log.read_entries()
        assert entries[-1]["declined_by_human"] is True
        assert entries[-1]["saved"] == 0

    def test_exact_resave_is_upsert_not_duplicate(self, env, capsys):
        # Контракт: точное совпадение title — UPSERT (идемпотентный реингест),
        # дубликата в базе не появляется
        control.cmd_save(auto_yes=True, raw=json.dumps(CANDIDATES))
        control.cmd_save(auto_yes=True, raw=json.dumps(CANDIDATES))
        backend = LocalBackend(str(env / "knowledge.db"))
        facts = backend.query_facts(FactQuery(search="Cursor-based"))
        assert len(facts) == 1

    def test_near_duplicate_rejected_and_logged(self, env, capsys):
        control.cmd_save(auto_yes=True, raw=json.dumps(CANDIDATES))
        # Другой title, слово-пересечение > 0.6 — gatekeeper ловит как дубль
        near = dict(CANDIDATES[0])
        near["title"] = "Cursor-based пагинация для стримов и лент"
        control.cmd_save(auto_yes=True, raw=json.dumps([near]))
        from curator import candidates_log
        entries = candidates_log.read_entries()
        last = entries[-1]
        assert last["saved"] == 0
        rejected = [c for c in last["candidates"] if c["decision"] == "rejected"]
        assert rejected
        assert "дубликат" in rejected[0]["reason"].lower()
