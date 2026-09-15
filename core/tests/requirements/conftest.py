"""Общие фикстуры тестов требований: изоляция от реальных путей ~/.curator.

ImproveLoop/worker создают Observability и RetrievalFeedback с дефолтными
путями ВНУТРИ вызовов — патчим фабриками на tmp-пути, чтобы тесты
требований не писали в живую базу пользователя.
"""

import pytest

from curator.backend.local import LocalBackend
from curator.gatekeeper import Gatekeeper
from curator.observability import Observability
from curator.retrieval_feedback import RetrievalFeedback


@pytest.fixture
def iso_observability(tmp_path, monkeypatch):
    """ImproveLoop пишет improve-лог — изолируем в tmp."""
    events = tmp_path / "improve_events.jsonl"

    def factory(*args, **kwargs):
        return Observability(path=str(events))

    monkeypatch.setattr("curator.observability.Observability", factory)
    return events


@pytest.fixture
def iso_feedback(tmp_path, monkeypatch):
    """worker читает usage.json — изолируем в tmp."""
    usage = tmp_path / "usage.json"

    def factory(*args, **kwargs):
        return RetrievalFeedback(storage_path=str(usage))

    monkeypatch.setattr("curator.retrieval_feedback.RetrievalFeedback", factory)
    return usage


@pytest.fixture
def server_memory(tmp_path, monkeypatch):
    """MCP-функции сервера на :memory: бэкенде — без записи в реальную базу."""
    import curator.server as server_mod

    be = LocalBackend(":memory:")
    monkeypatch.setattr(server_mod, "backend", be)
    monkeypatch.setattr(server_mod, "gatekeeper", Gatekeeper(be))
    monkeypatch.setattr(server_mod, "feedback", RetrievalFeedback(storage_path=str(tmp_path / "usage.json")))
    monkeypatch.setattr(server_mod, "base_dir", tmp_path)
    monkeypatch.setenv("CURATOR_BASE_DIR", str(tmp_path))
    monkeypatch.delenv("CURATOR_MAP", raising=False)
    monkeypatch.delenv("AUTO_MODE", raising=False)
    with server_mod._captures_lock:
        server_mod._pending_captures.clear()
    return be


@pytest.fixture
def learnings_dir(tmp_path):
    """Нейтральные .md фикстуры по структуре реальной базы learnings.

    Личные learnings в репо не попадают — фикстуры повторяют формат
    (frontmatter + ### секции), но с нейтральным содержанием.
    """
    d = tmp_path / "learnings"
    d.mkdir()
    (d / "kotlin.md").write_text(
        "---\n"
        "type: Reference\n"
        "tags: [kotlin, jvm]\n"
        "---\n\n"
        "# Kotlin/JVM\n\n"
        "### JvmInline value class внутри sealed interface бесполезен\n\n"
        "Value class в иерархии sealed interface всегда боксируется при апкасте к интерфейсу. "
        "Для доменных типов-обёрток внутри иерархий использовать data class.\n\n"
        "### ImmutableList оправдан только для read-only данных\n\n"
        "Для стабильных read-only коллекций ImmutableList уместен. "
        "Для часто меняющихся данных — overhead без пользы, выбирать по паттерну доступа.\n",
        encoding="utf-8",
    )
    (d / "workflow.md").write_text(
        "---\n"
        "type: Style\n"
        "tags: [workflow, git]\n"
        "---\n\n"
        "# Workflow\n\n"
        "### Коммитить только по явной просьбе пользователя\n\n"
        "Никогда не коммитить автоматически после изменений. "
        "Только по /commit или явному запросу пользователя в чате.\n",
        encoding="utf-8",
    )
    return d
