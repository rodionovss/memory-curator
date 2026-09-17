"""E2E: полный жизненный цикл знания — всё заявленное, один связный сценарий.

Сценарий = capture review → approval → semantic docs → complete → query →
improve (дубликаты + противоречия + eval-гейт). Отдельно: decay по usage.

Изоляция: HOME → tmp. Все ~/.curator/... пути (usage, логи) и базы
живут в песочнице — реальное окружение пользователя не затрагивается.
"""

import json
import time
from pathlib import Path

import pytest

from curator.backend.local import LocalBackend
from curator.gatekeeper import Gatekeeper
from curator.improve_loop import ImproveLoop
from curator.models import FactQuery, StructuredFact
from curator.sync_engine import SyncEngine
from curator.retrieval_feedback import RetrievalFeedback

A_TITLE = "Правило про kotlin inline классы и sealed interface"
B_TITLE = A_TITLE + " бокс"  # near-дубликат A, similarity > 0.8
WINNER_TITLE = "Никогда не используй rxjava в новых модулях"
LOSER_TITLE = "Всегда используй rxjava в новых модулях"
STYLE_TITLE = "Стиль git коммитов в рабочих проектах"


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path


def _wire_server(monkeypatch, be: LocalBackend, md_dir: Path, usage_path: Path):
    """Подменить глобальные зависимости MCP-сервера на песочницу."""
    import curator.server as server_mod

    monkeypatch.setattr(server_mod, "backend", be)
    monkeypatch.setattr(server_mod, "improve", ImproveLoop(be))
    monkeypatch.setattr(server_mod, "gatekeeper", Gatekeeper(be))
    monkeypatch.setattr(server_mod, "base_dir", md_dir)
    monkeypatch.setattr(server_mod, "feedback", RetrievalFeedback(str(usage_path)))
    monkeypatch.setenv("CURATOR_BASE_DIR", str(md_dir))
    map_path = md_dir / "DOCUMENTATION-MAP.md"
    if map_path.is_file():
        monkeypatch.setenv("CURATOR_MAP", str(map_path))
    else:
        monkeypatch.delenv("CURATOR_MAP", raising=False)
    with server_mod._captures_lock:
        server_mod._pending_captures.clear()
    return server_mod


class TestDeclaredLifecycle:
    """Capture, semantic write-back, query и backend improve через server seams."""

    def test_full_story(self, tmp_path, monkeypatch):
        home = tmp_path
        md_dir = home / "learnings"
        md_dir.mkdir()
        (md_dir / "DOCUMENTATION-MAP.md").write_text(
            """---
topics:
  - name: durable-knowledge
    watch_for: Устойчивые знания и правила
    targets:
      - path: docs/knowledge.md
        captures: [knowledge, rules]
        mode: update
        instructions: Обнови документ в его существующем стиле
---
""",
            encoding="utf-8",
        )
        be = LocalBackend(str(home / "db" / "knowledge.db"))
        usage_path = home / "usage.json"
        server_mod = _wire_server(monkeypatch, be, md_dir, usage_path)

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
        reviewed = json.loads(server_mod._session_capture({"candidates": candidates}))
        assert reviewed["status"] == "needs_human_approval"
        assert len(reviewed["eligible"]) == 5
        assert len(reviewed["rejected"]) == 2
        assert "Слишком короткий заголовок" in reviewed["rejected"][0]["reason"]
        assert be.query_facts(FactQuery()) == [], "review не пишет backend"

        selected_ids = [fact["candidate_id"] for fact in reviewed["eligible"]]
        approved = json.loads(server_mod._capture_approve({
            "capture_id": reviewed["capture_id"],
            "selected_candidate_ids": selected_ids,
        }))
        assert approved["status"] == "update_project_docs"
        assert approved["next_action"] == "curator-update-docs"
        assert be.query_facts(FactQuery()) == [], "approval не пишет backend"

        semantic_doc = md_dir / "docs" / "knowledge.md"
        semantic_doc.parent.mkdir()
        semantic_doc.write_text(
            "# Знания проекта\n\n" + "\n".join(f"- {fact['title']}" for fact in approved["facts"]) + "\n",
            encoding="utf-8",
        )
        placements = [{
            "candidate_id": fact["candidate_id"],
            "topic": "durable-knowledge",
            "target": "docs/knowledge.md",
            "capture": "knowledge",
            "canonical_file": "docs/knowledge.md",
            "changed_files": ["docs/knowledge.md"],
        } for fact in approved["facts"]]
        completed = json.loads(server_mod._capture_complete({
            "capture_id": reviewed["capture_id"],
            "placements": placements,
        }))
        assert completed["status"] == "completed"
        assert completed["saved"] == 5
        assert len(be.query_facts(FactQuery())) == 5
        assert not (md_dir / "session").exists(), "semantic flow не использует fallback"

        # ---- Шаг 2: query находит, usage-телеметрия пишется
        out = server_mod._query({"search": "kotlin"})
        assert "Найдено: 2" in out and A_TITLE in out
        stats = RetrievalFeedback(str(usage_path)).get_stats(10)
        assert {s["title"] for s in stats} == {A_TITLE, B_TITLE}
        assert all(s["count"] == 1 for s in stats)

        # ---- Шаг 2а: наблюдаемость (сохранённое видно через тулзы)
        out = server_mod._status()
        assert "Всего фактов: 5" in out, "status отражает то, что сохранили"
        assert "Типы (словарь для агента):" in out
        assert "Reference —" in out, "описания типов — контракт для агента"
        out = server_mod._feedback()
        assert "kotlin" in out or A_TITLE in out, "телеметрия запросов живая"

        # ---- Шаг 3: improve меняет backend, но не semantic project docs.
        semantic_before_improve = semantic_doc.read_text(encoding="utf-8")
        out = server_mod._improve()
        assert "Найдено дубликатов: 1" in out
        assert "Противоречия" in out
        assert WINNER_TITLE in out
        assert "Метрики (до → после)" in out, "замер пользы обязана быть в отчёте"

        by_title = {f.title: f for f in be.query_facts(FactQuery())}
        assert by_title[B_TITLE].status == "deprecated", "dup-проигравший устаревает"
        assert by_title[A_TITLE].status == "verified"
        assert by_title[LOSER_TITLE].status == "deprecated", "проигравший противоречия устаревает"
        assert by_title[WINNER_TITLE].status == "verified"
        assert semantic_doc.read_text(encoding="utf-8") == semantic_before_improve
        assert not (md_dir / "index.md").exists()


class TestUsageTelemetry:
    """Семантика D: телеметрия — observability, не приговор. 40/100 дней без
    запросов не меняют статусы (таймерного decay нет); семантическое
    устаревание (hypothesis по eval-гейту) работает как раньше."""

    def test_telemetry_does_not_punish(self, tmp_path, monkeypatch):
        home = tmp_path
        md_dir = home / "learnings"
        md_dir.mkdir()
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
        usage_path = home / ".curator" / "usage.json"
        usage_path.parent.mkdir(parents=True)
        now = time.time()
        usage_path.write_text(json.dumps({
            fact_verified.title: {"count": 1, "last_access": now - 40 * 86400},
            fact_hyp.title: {"count": 0, "last_access": now - 100 * 86400},
        }))

        from curator import worker
        data = worker.run_improve_cycle(be, home / "reports", base_dir=md_dir)

        by_title = {f.title: f for f in be.query_facts(FactQuery())}
        assert by_title[fact_verified.title].status == "verified", \
            "таймерного decay нет: 40 дней молчания не деградируют verified"
        assert by_title[fact_hyp.title].status == "hypothesis", \
            "ценное знание (покрывает запрос) eval-гейт защищает и от таймера, и от депрекации"
        assert "auto_decay" not in data
        assert list((home / "reports").glob("improve_*.json")), "отчёт цикла обязан писаться"

        # человек видит статистику — но сам решает
        fb = RetrievalFeedback(str(usage_path))
        unused = fb.get_unused(30)
        assert fact_verified.title in unused and fact_hyp.title in unused, \
            "телеметрия обязана показывать забытое человеку"

        # .md не врёт: секции нетронуты — ни [УСТАРЕЛО], ни смены статуса
        md_text = (md_dir / "session" / "reference.md").read_text(encoding="utf-8")
        assert "[УСТАРЕЛО]" not in md_text
        assert "*Статус:* Подтверждено" in md_text



class TestMapRoutingE2E:
    """Semantic placement проверяется по карте до сохранения в backend."""

    def test_capture_routes_via_map(self, tmp_path, monkeypatch):
        home = tmp_path
        md_dir = home / "learnings"
        md_dir.mkdir()
        (md_dir / "DOCUMENTATION-MAP.md").write_text(
            "---\n"
            "status: draft\n"
            "categories: [knowledge, rules, records]\n"
            "modes: [update, append, readonly]\n"
            "on_unmatched: report\n"
            "topics:\n"
            "  - name: kotlin\n"
            "    watch_for: знания о kotlin\n"
            "    targets:\n"
            "      - path: docs/kotlin.md\n"
            "        captures: [knowledge]\n"
            "        mode: update\n"
            "  - name: journal\n"
            "    watch_for: исторические записи\n"
            "    targets:\n"
            "      - path: docs/journal.md\n"
            "        captures: [records]\n"
            "        mode: append\n"
            "  - name: context\n"
            "    watch_for: только контекст\n"
            "    targets:\n"
            "      - path: docs/context.md\n"
            "        captures: [knowledge]\n"
            "        mode: readonly\n"
            "---\n",
            encoding="utf-8",
        )

        be = LocalBackend(str(home / "db" / "knowledge.db"))
        server_mod = _wire_server(monkeypatch, be, md_dir, home / "usage.json")
        from curator.routing.map_router import MapRouter
        monkeypatch.setattr(server_mod, "router", MapRouter(md_dir / "DOCUMENTATION-MAP.md"))

        candidates = [
            {"type": "Reference", "title": "Правило про kotlin inline классы и sealed",
             "content_summary": "JvmInline внутри sealed interface боксируется всегда.",
             "tags": ["kotlin"]},
            {"type": "Spec", "title": "Решение журнала про стек тестирования",
             "content_summary": "Историческое решение: выбираем junit5 для новых модулей.",
             "tags": ["journal"]},
            {"type": "Reference", "title": "Контекстный факт readonly таргета",
             "content_summary": "Этот факт попадает в readonly таргет и не пишется в .md.",
             "tags": ["context"]},
        ]
        reviewed = json.loads(server_mod._session_capture({"candidates": candidates}))
        approved = json.loads(server_mod._capture_approve({
            "capture_id": reviewed["capture_id"],
            "selected_candidate_ids": ["fact_1", "fact_2"],
        }))
        assert be.query_facts(FactQuery()) == []

        docs = md_dir / "docs"
        docs.mkdir()
        (docs / "kotlin.md").write_text("# Kotlin\n\nInline-классы боксируются в sealed API.\n", encoding="utf-8")
        (docs / "journal.md").write_text("# Журнал\n\nВыбран JUnit 5.\n", encoding="utf-8")
        completed = json.loads(server_mod._capture_complete({
            "capture_id": reviewed["capture_id"],
            "placements": [
                {
                    "candidate_id": "fact_1", "topic": "kotlin", "target": "docs/kotlin.md",
                    "capture": "knowledge", "canonical_file": "docs/kotlin.md",
                    "changed_files": ["docs/kotlin.md"],
                },
                {
                    "candidate_id": "fact_2", "topic": "journal", "target": "docs/journal.md",
                    "capture": "records", "canonical_file": "docs/journal.md",
                    "changed_files": ["docs/journal.md"],
                },
            ],
        }))
        assert completed["status"] == "completed"
        assert completed["saved"] == 2
        assert [fact["candidate_id"] for fact in approved["facts"]] == ["fact_1", "fact_2"]

        by_title = {f.title: f for f in be.query_facts(FactQuery())}
        assert by_title["Правило про kotlin inline классы и sealed"].source_file == "docs/kotlin.md"
        assert by_title["Решение журнала про стек тестирования"].source_file == "docs/journal.md"
        # OKF-инвариант: карта решает только путь, тип факта не мутируется
        assert by_title["Правило про kotlin inline классы и sealed"].type == "Reference"
        assert by_title["Решение журнала про стек тестирования"].type == "Spec"

        assert "Контекстный факт readonly таргета" not in by_title
        assert not (md_dir / "docs" / "context.md").exists(), "readonly не пишет .md"
        assert not (md_dir / "session").exists(), "semantic flow не использует fallback"

        # routes: темы карты с mode видны до сохранения
        out = server_mod._routes()
        assert "docs/kotlin.md (mode: update)" in out
        assert "docs/journal.md (mode: append)" in out
        assert "kotlin" in out

    def test_routes_see_map_edits_without_restart(self, tmp_path, monkeypatch):
        """Регрессия #4: curator_routes перечитывает карту при вызове,
        а не служит снапшотом старта сервера."""
        home = tmp_path
        md_dir = home / "learnings"
        md_dir.mkdir()
        map_path = md_dir / "DOCUMENTATION-MAP.md"
        map_path.write_text(
            "---\n"
            "topics:\n"
            "  - name: alpha\n"
            "    watch_for: alpha\n"
            "    targets:\n"
            "      - path: docs/alpha.md\n"
            "        captures: [knowledge]\n"
            "        mode: update\n"
            "---\n",
            encoding="utf-8",
        )
        be = LocalBackend(str(home / "db" / "knowledge.db"))
        server_mod = _wire_server(monkeypatch, be, md_dir, home / "usage.json")
        from curator.routing.map_router import MapRouter
        monkeypatch.setattr(server_mod, "router", MapRouter(map_path))
        assert "Маршрутов: 1" in server_mod._routes()

        # правка карты без перезапуска сервера
        map_path.write_text(
            "---\n"
            "topics:\n"
            "  - name: alpha\n"
            "    watch_for: alpha\n"
            "    targets:\n"
            "      - path: docs/alpha.md\n"
            "        captures: [knowledge]\n"
            "        mode: update\n"
            "  - name: beta\n"
            "    watch_for: beta\n"
            "    targets:\n"
            "      - path: docs/beta.md\n"
            "        captures: [knowledge]\n"
            "        mode: update\n"
            "---\n",
            encoding="utf-8",
        )
        out = server_mod._routes()
        assert "Маршрутов: 2" in out, "правка карты видна без перезапуска сервера (#4)"
        assert "docs/beta.md" in out
