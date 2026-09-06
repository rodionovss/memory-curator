"""NICE TO HAVE требования хакатона — design/requirements.md, «Дополнительные блоки».

| ID | Требование | Источник |
|----|-----------|----------|
| N1 | Забывание и устаревание | доп. блок 1 |
| N2 | Разрешение противоречий | доп. блок 2 |
| N3 | Эвалы для изменений поведения | доп. блок 3 |
| N4 | Human-in-the-loop | доп. блок 4 |
| N5 | Observability | доп. блок 5 |
"""

import json
import time

from curator.backend.local import LocalBackend
from curator.eval_runner import EvalRunner
from curator.improve_loop import ImproveLoop
from curator.models import StructuredFact, FactQuery
import curator.server as server_mod
import curator.worker as worker_mod

CANDIDATE = {
    "type": "Reference",
    "title": "MCP SDK v2: правильная сигнатура хендлеров",
    "content_summary": "Хендлеры принимают (ctx, request), первый — ServerRequestContext. Запуск через async with stdio_server().",
    "tags": ["python", "mcp"],
}


def _fact(title: str, tags: list[str], status: str = "verified", summary: str = "Проверенное знание для теста требования.") -> StructuredFact:
    return StructuredFact(type="Reference", title=title, tags=tags, status=status, content_summary=summary)


class TestNiceToHave:
    def test_N1_забывание_семантическое(self, iso_feedback, iso_observability, tmp_path):
        """N1: устаревание — семантическое (неподтверждённая гипотеза → deprecated
        по eval-гейту). Таймерного decay нет: время не делает факт ложным —
        неиспользуемое verified-знание не деградирует, телеметрия остаётся
        observability для человека."""
        be = LocalBackend(":memory:")
        # verified + 40 дней без запросов — обязан остаться verified
        be.store_fact(_fact("Правило про использование Retrofit в сетевом модуле", ["android"]))
        # hypothesis без покрытия тестовых запросов: депрекация улучшает
        # метрики → eval-гейт одобряет семантическое устаревание
        be.store_fact(_fact("Неподтверждённая гипотеза про docker деплой", ["docker"], status="hypothesis"))

        now = time.time()
        iso_feedback.write_text(json.dumps({
            "Правило про использование Retrofit в сетевом модуле": {"count": 1, "last_access": now - 40 * 86400},
            "Неподтверждённая гипотеза про docker деплой": {"count": 0, "last_access": now - 100 * 86400},
        }), encoding="utf-8")

        worker_mod.run_improve_cycle(be, tmp_path / "reports")

        statuses = {f.title: f.status for f in be.query_facts(FactQuery())}
        assert statuses["Правило про использование Retrofit в сетевом модуле"] == "verified", \
            "таймерного decay нет: 40 дней без запросов не деградируют verified"
        assert statuses["Неподтверждённая гипотеза про docker деплой"] == "deprecated", \
            "семантическое устаревание: гипотеза без ценности уходит по гейту"

    def test_N2_противоречия_разрешаются(self, iso_observability):
        """N2: конфликт «использовать X» vs «не использовать X» — побеждает verified."""
        be = LocalBackend(":memory:")
        be.store_fact(_fact("Использовать Retrofit для сетевых запросов", ["android"],
                            summary="Стандарт команды: сетевой слой на Retrofit."))
        # «kotlin» в заголовке — stale-депрекация заблокируется eval-ом, деградирует только resolution
        be.store_fact(_fact("Не использовать Retrofit для сетевых запросов на kotlin", ["android", "kotlin"],
                            status="hypothesis", summary="Гипотеза: перейти на Ktor."))

        report = ImproveLoop(be).run()

        assert report.stats["contradictions_found"] == 1
        assert report.resolutions[0].winner.title == "Использовать Retrofit для сетевых запросов"
        assert "verified" in report.resolutions[0].reason
        statuses = {f.title: f.status for f in be.query_facts(FactQuery())}
        assert statuses["Не использовать Retrofit для сетевых запросов на kotlin"] == "deprecated"

    def test_N3_eval_блокирует_ухудшение(self):
        """N3: изменение памяти применяется только если метрики не ухудшились."""
        runner = EvalRunner()
        valuable = _fact("Проверенное правило про kotlin-коллекции", ["kotlin"], status="hypothesis",
                         summary="Гипотеза о выборе коллекций, единственный результат kotlin-запроса.")
        junk = _fact("Гипотеза про устаревший docker-деплой", ["docker"], status="hypothesis",
                     summary="Никому не нужная гипотеза про деплой.")

        blocking = runner.evaluate_deprecation([valuable], [valuable])
        assert not blocking.improved, "coverage падает (kotlin-запрос теряет единственный результат) — gate обязан блокировать"

        allowing = runner.evaluate_deprecation([valuable, junk], [junk])
        assert allowing.improved, "удаление мусора не роняет метрики — gate обязан разрешить"

    def test_N4_human_in_the_loop(self, server_memory):
        """N4: review требует явного human approval и ничего не сохраняет."""
        out = json.loads(server_mod._session_capture({"candidates": [CANDIDATE]}))
        assert out["status"] == "needs_human_approval"
        assert len(out["eligible"]) == 1
        assert len(server_memory.query_facts(FactQuery())) == 0, "база обязана остаться пустой без approve"

    def test_N5_observability_логирует_улучшения(self, iso_observability):
        """N5: каждое improve-действие попадает в JSONL-лог с трейсом."""
        be = LocalBackend(":memory:")
        be.store_fact(_fact("Правило организации сетевого слоя на Retrofit в проекте", ["android"]))
        be.store_fact(_fact("Правило организации сетевого слоя на Retrofit в проекте копия", ["android"]))

        ImproveLoop(be).run()

        assert iso_observability.exists(), "improve-цикл обязан писать observability-лог"
        events = [json.loads(line) for line in iso_observability.read_text().splitlines() if line.strip()]
        assert events, "лог не может быть пустым после цикла с дубликатами"
        assert any(e["action"] == "consolidate" for e in events)
        assert all("ts" in e for e in events)
