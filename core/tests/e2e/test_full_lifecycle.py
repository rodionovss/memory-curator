"""E2E: полный жизненный цикл знания через CLI (единственный вход после
ухода от MCP-сервера, решение 2026-10-03 «ноль фоновых процессов»).

save (gatekeeper + маршрутизация по карте + write-back) → get → improve
(отчёт пишется, таймерного decay нет) → status.
"""

import json
import time

from curator.backend.local import LocalBackend
from curator.models import FactQuery, StructuredFact
from curator.retrieval_feedback import RetrievalFeedback
from curator.sync_engine import SyncEngine
import curator.control as control


A_TITLE = "Правило про kotlin inline классы и sealed interface"
B_TITLE = A_TITLE + " бокс"  # near-дубликат A, similarity > 0.8
STYLE_TITLE = "Стиль git коммитов в рабочих проектах"
LOSER_TITLE = "Всегда используй rxjava в новых модулях"
WINNER_TITLE = "Никогда не используй rxjava в новых модулях"


def _env(monkeypatch, home):
    monkeypatch.setenv("CURATOR_DB_PATH", str(home / "db" / "knowledge.db"))
    monkeypatch.setenv("CURATOR_BASE_DIR", str(home / "learnings"))
    monkeypatch.setenv("CURATOR_USAGE_PATH", str(home / "usage.json"))
    monkeypatch.setenv("CURATOR_STATE_DIR", str(home / ".curator"))
    monkeypatch.delenv("CURATOR_MAP", raising=False)
    (home / "learnings").mkdir(exist_ok=True)
    (home / "db").mkdir(exist_ok=True)


class TestDeclaredLifecycle:
    """Save → write-back по карте → query → improve, всё через CLI."""

    def test_full_story(self, tmp_path, monkeypatch, capsys):
        home = tmp_path
        _env(monkeypatch, home)
        (home / "learnings" / "DOCUMENTATION-MAP.md").write_text(
            """---
topics:
  - name: durable-knowledge
    watch_for: kotlin, git, rx, java
    targets:
      - path: docs/knowledge.md
        captures: [knowledge, rules]
        mode: update
        instructions: Обнови документ в его существующем стиле
---
""",
            encoding="utf-8",
        )

        # ---- Шаг 1: агент сохраняет кандидатов: 5 валидных + 2 мусорных.
        # Near-дубликаты A/B проходят одним батчем (gatekeeper смотрит базу,
        # не батч) — их консолидирует improve loop, это заявленный кейс.
        candidates = [
            {"type": "Reference", "title": A_TITLE,
             "content_summary": "JvmInline value class внутри sealed interface боксируется. Проверено исходниками.",
             "tags": ["kotlin"], "evidence": "сессия"},
            {"type": "Reference", "title": B_TITLE,
             "content_summary": "Бокс при использовании value class внутри sealed interface неизбежен.",
             "tags": ["kotlin"]},
            {"type": "Style", "title": STYLE_TITLE,
             "content_summary": "Коммит содержит модуль и Jira-ключ: type[module]: AAA-000.",
             "tags": ["git"]},
            # противоречивая пара: победителя выбирает improve (длиннее сводка)
            {"type": "Reference", "title": LOSER_TITLE,
             "content_summary": "Короткая сводка про rxjava.",
             "tags": ["rx", "java"]},
            {"type": "Reference", "title": WINNER_TITLE,
             "content_summary": "Подробная сводка: rxjava запрещена в новых модулях, только coroutines flow.",
             "tags": ["rx", "java"]},
            # мусор: слишком короткий title и мета-строка в summary
            {"type": "Reference", "title": "Коротко",
             "content_summary": "сводка нормальной длины", "tags": ["x"]},
            {"type": "Reference", "title": "Заголовок достаточно длинный",
             "content_summary": "*Тип:* Reference подделка", "tags": ["x"]},
        ]
        control.cmd_save(auto_yes=True, raw=json.dumps(candidates))
        out = capsys.readouterr().out

        assert "Одобрено: 5" in out, "5 валидных кандидатов прошло gatekeeper"
        assert "Отклонено: 2" in out, "мусор отсечён gatekeeper-ом"
        assert "docs/knowledge.md" in out, "маршрутизация по карте видна в preview"

        be = LocalBackend(str(home / "db" / "knowledge.db"))
        assert len(be.query_facts(FactQuery())) == 5
        semantic_doc = home / "learnings" / "docs" / "knowledge.md"
        assert semantic_doc.exists(), "write-back по таргету карты"
        md_text = semantic_doc.read_text(encoding="utf-8")
        assert A_TITLE in md_text and WINNER_TITLE in md_text
        assert not (home / "learnings" / "session").exists(), \
            "карта закрыла все факты — fallback-приёмник не нужен"
        catalog = home / "learnings" / "knowledge-routes.md"
        assert catalog.exists(), "каталог маршрутов регенерируется save-ом"

        # ---- Шаг 2: query находит сохранённое
        control.cmd_get("kotlin")
        out = capsys.readouterr().out
        assert "Найдено: 2" in out and "inline классы" in out

        # ---- Шаг 3: improve меняет backend, но не semantic project docs
        semantic_before_improve = md_text
        control.cmd_improve()
        out = capsys.readouterr().out
        assert "Дубликатов: 1" in out
        assert "Противоречий: 1" in out

        by_title = {f.title: f for f in be.query_facts(FactQuery())}
        assert by_title[B_TITLE].status == "deprecated", "dup-проигравший устаревает"
        assert by_title[A_TITLE].status == "verified"
        assert by_title[LOSER_TITLE].status == "deprecated", "проигравший противоречия устаревает"
        assert by_title[WINNER_TITLE].status == "verified"
        assert semantic_doc.read_text(encoding="utf-8") == semantic_before_improve, \
            "semantic docs не переписываются improve-ом"
        assert list((home / ".curator" / "reports").glob("improve_*.json")), \
            "отчёт цикла обязан писаться"


class TestUsageTelemetry:
    """Телеметрия — observability, не приговор: 40/100 дней без запросов не
    меняют статусы; ценную hypothesis eval-гейт защищает и от депрекации."""

    def test_telemetry_does_not_punish(self, tmp_path, monkeypatch, capsys):
        home = tmp_path
        _env(monkeypatch, home)
        md_dir = home / "learnings"
        be = LocalBackend(str(home / "db" / "knowledge.db"))

        fact_verified = StructuredFact(type="Reference", title="Проверенное правило про compose рекомпозицию",
                                       tags=["compose"], status="verified",
                                       content_summary="Рекомпозиция в compose управляется stability входов.",
                                       source_file="session/reference.md")
        # «architecture» в title: покрывает тестовый запрос гейта →
        # семантическая депрекация блокируется (coverage упал бы)
        fact_hyp = StructuredFact(type="Reference", title="Старая гипотеза про architecture модулей",
                                  tags=["architecture"], status="hypothesis",
                                  content_summary="Гипотеза: слои обязаны делиться по модулям.",
                                  source_file="session/reference.md")
        for f in (fact_verified, fact_hyp):
            be.store_fact(f)
            SyncEngine(be, md_dir).write_fact_to_md(f)

        # usage-сид: verified не трогали 40 дней, hypothesis — 100 дней
        usage_path = home / "usage.json"
        now = time.time()
        usage_path.write_text(json.dumps({
            fact_verified.title: {"count": 1, "last_access": now - 40 * 86400},
            fact_hyp.title: {"count": 0, "last_access": now - 100 * 86400},
        }))

        control.cmd_improve()
        capsys.readouterr()

        by_title = {f.title: f for f in be.query_facts(FactQuery())}
        assert by_title[fact_verified.title].status == "verified", \
            "таймерного decay нет: 40 дней молчания не деградируют verified"
        assert by_title[fact_hyp.title].status == "hypothesis", \
            "ценное знание (покрывает запрос) eval-гейт защищает и от таймера, и от депрекации"

        # человек видит статистику — но сам решает
        fb = RetrievalFeedback(str(usage_path))
        unused = fb.get_unused(30)
        assert fact_verified.title in unused and fact_hyp.title in unused, \
            "телеметрия обязана показывать забытое человеку"

        # .md не врёт: секции нетронуты — ни [УСТАРЕЛО], ни смены статуса
        md_text = (md_dir / "session" / "reference.md").read_text(encoding="utf-8")
        assert "[УСТАРЕЛО]" not in md_text
