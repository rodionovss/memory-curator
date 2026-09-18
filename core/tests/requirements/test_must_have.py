"""MUST HAVE требования — design/requirements.md, «Минимальные требования».

1 тест = 1 требование. Только публичные API (ingest, MCP-функции сервера,
backend Protocol) — рефакторинг внутренностей не может «обнулить» тест.

| ID | Требование | Источник |
|----|-----------|----------|
| R1 | Обрабатывать поток задач из выбранного источника | requirements.md #1 |
| R2 | Цикл «выполнил → оценил → извлёк урок» | requirements.md #2 |
| R3 | Менять поведение на основе опыта | requirements.md #3 |
| R4 | Хранить память между рестартами | requirements.md #4 |
| R5 | Поработать с реальными данными | requirements.md #5 |
| R6 | Демонстрация дельты «до/после» | requirements.md #6 |
"""

import json

from curator.analyzers.ingest import ingest_directory
from curator.backend.local import LocalBackend
from curator.demo import run_demo
from curator.gatekeeper import Gatekeeper
from curator.improve_loop import ImproveLoop
from curator.models import StructuredFact, FactQuery
import curator.server as server_mod

CANDIDATE = {
    "type": "Reference",
    "title": "MCP SDK v2: правильная сигнатура хендлеров",
    "content_summary": "Хендлеры принимают (ctx, request), первый — ServerRequestContext. Запуск через async with stdio_server().",
    "tags": ["python", "mcp"],
    "evidence": "агент: add_request_handler(ctx, request)",
}


def _fact(title: str, tags: list[str], status: str = "verified", summary: str = "Проверенное знание для теста требования.") -> StructuredFact:
    return StructuredFact(type="Reference", title=title, tags=tags, status=status, content_summary=summary)


class TestMustHave:
    def test_R1_поток_задач_из_источника_ingest(self, learnings_dir):
        """R1: источник (.md файлы learnings) → факты в памяти."""
        be = LocalBackend(":memory:")
        saved = ingest_directory(learnings_dir, be, Gatekeeper(be))
        assert saved == 3, "должны извлечься все 3 секции фикстур"
        found = be.query_facts(FactQuery(search="value class"))
        assert len(found) == 1
        assert found[0].source_file == "kotlin.md", "факт обязан знать свой источник"

    def test_R2_цикл_выполнил_оценил_извлёк_урок(self, server_memory, tmp_path, monkeypatch):
        """R2: review → human approval → semantic docs → backend; шум отсечён."""
        noise = {
            "type": "Reference",
            "title": "Поправить верстку кнопки на экране входа",
            "content_summary": "Мелкая правка интерфейса в рамках задачи.",
            "tags": ["ui"],
        }
        map_path = tmp_path / "DOCUMENTATION-MAP.md"
        map_path.write_text(
            """---
topics:
  - name: mcp
    targets:
      - path: docs/mcp.md
        captures: [knowledge]
        mode: update
---
""",
            encoding="utf-8",
        )
        monkeypatch.setenv("CURATOR_MAP", str(map_path))

        reviewed = json.loads(server_mod._session_capture({"candidates": [CANDIDATE, noise]}))
        assert len(reviewed["eligible"]) == 1
        assert len(reviewed["rejected"]) == 1, "шум-кандидат обязан быть отклонён gatekeeper-ом"
        assert server_memory.query_facts(FactQuery()) == []

        approved = json.loads(server_mod._capture_approve({
            "capture_id": reviewed["capture_id"],
            "selected_candidate_ids": ["1"],
        }))
        assert approved["status"] == "update_project_docs"
        target = tmp_path / "docs" / "mcp.md"
        target.parent.mkdir()
        target.write_text("# MCP\n\nХендлеры принимают ctx и request.\n", encoding="utf-8")
        completed = json.loads(server_mod._capture_complete({
            "capture_id": reviewed["capture_id"],
            "placements": [{
                "candidate_id": "1", "topic": "mcp", "target": "docs/mcp.md",
                "capture": "knowledge", "canonical_file": "docs/mcp.md",
                "changed_files": ["docs/mcp.md"],
            }],
        }))
        assert completed["status"] == "completed"
        assert len(server_memory.query_facts(FactQuery(search="MCP"))) == 1
        assert not (tmp_path / "session").exists()

    def test_R3_поведение_меняется_на_основе_опыта(self, iso_observability):
        """R3: improve loop сам находит дубликаты и консолидирует их."""
        be = LocalBackend(":memory:")
        be.store_fact(_fact("Правило организации сетевого слоя на Retrofit в проекте", ["android"]))
        be.store_fact(_fact("Правило организации сетевого слоя на Retrofit в проекте копия", ["android"]))
        be.store_fact(_fact("Отдельное правило про Coroutines и холодные Flow", ["kotlin"]))

        report = ImproveLoop(be).run()

        assert report.stats["duplicates_found"] == 1
        statuses = {f.title: f.status for f in be.query_facts(FactQuery())}
        pair = ["Правило организации сетевого слоя на Retrofit в проекте",
                "Правило организации сетевого слоя на Retrofit в проекте копия"]
        assert sum(1 for t in pair if statuses[t] == "deprecated") == 1, \
            f"консолидация обязана пометить дубликат: {statuses}"
        assert statuses["Отдельное правило про Coroutines и холодные Flow"] == "verified"

    def test_R4_память_между_рестартами(self, tmp_path):
        """R4: факт переживает «рестарт» — новый экземпляр бэкенда на том же файле видит его.

        Персистентность SQLite-файла — единственный persistence backend:
        `:memory:` как хранилище продукта недопустим (реальная регрессия).
        """
        db = str(tmp_path / "kb.db")
        LocalBackend(db).store_fact(_fact("Знание переживает рестарт процесса куратора", ["durability"]))

        restarted = LocalBackend(db)
        assert len(restarted.query_facts(FactQuery(search="рестарт"))) == 1

    def test_R5_реальные_данные_структуры_learnings(self, learnings_dir):
        """R5: извлечение на данных, повторяющих структуру реальной базы learnings."""
        be = LocalBackend(":memory:")
        saved = ingest_directory(learnings_dir, be, Gatekeeper(be))
        assert saved >= 3

        by_title = {f.title: f for f in be.query_facts(FactQuery())}
        jvm = by_title["JvmInline value class внутри sealed interface бесполезен"]
        assert jvm.type == "Reference"
        assert "kotlin" in jvm.tags
        assert by_title["Коммитить только по явной просьбе пользователя"].type == "Style"

    def test_R6_дельта_до_и_после(self):
        """R6: чистая память принимает факты, обученная — отклоняет дубликаты."""
        trained = LocalBackend(":memory:")
        trained.store_fact(StructuredFact(
            type="Style", title="Формат коммитов: Conventional Commits",
            tags=["git", "workflow"], status="verified",
            content_summary="Conventional Commits: type(scope): description, заголовок до 72 символов.",
        ))
        trained.store_fact(_fact("JvmInline value class внутри sealed interface бесполезен — бокс неизбежен",
                                  ["kotlin", "jvm"]))

        result = run_demo(backend_trained=trained, verbose=False)

        rejected = [c for c in result.comparisons if c.trained_rejected_reasons]
        assert rejected, "обученная память обязана отклонять дубликаты"
        comp = rejected[0]
        assert any("дубликат" in r.lower() for r in comp.trained_rejected_reasons)
        assert len(comp.clean_approved) >= 1, "чистая память те же факты принимает"
