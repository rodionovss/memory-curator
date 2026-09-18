"""Тесты context cards API (ADR 002, issue #27): fetch_context, CLI, MCP.

Контракт: API принимает текст задачи, возвращает стабильный JSON,
соблюдает limit/token budget, пустой результат валиден,
полный Markdown читается отдельно через source_file.
"""

import json

import pytest

import curator.server as server_mod
import curator.control as control_mod
from curator.delivery import ContextCard, fetch_context, fetch_context_safe
from curator.backend.local import LocalBackend
from curator.models import StructuredFact
from curator.server import _context


def _fact(
    title: str,
    tags: list[str],
    status: str = "verified",
    summary: str = "Знание про хендлеры и сигнатуры MCP-сервера на Python.",
    source_file: str | None = None,
) -> StructuredFact:
    return StructuredFact(
        type="Reference", title=title, tags=tags, status=status,
        content_summary=summary, source_file=source_file,
    )


class TestFetchContext:
    def test_принимает_текст_и_возвращает_карточки(self, tmpdir):
        be = LocalBackend(str(tmpdir / "db.db"))
        be.store_fact(_fact("Хендлеры MCP", ["mcp"], source_file="session/tool.md"))
        cards = fetch_context("хендлеры MCP", backend=be, feedback=None)
        assert len(cards) == 1
        card = cards[0]
        assert isinstance(card, ContextCard)
        assert card.title == "Хендлеры MCP"
        assert card.source_file == "session/tool.md"

    def test_limit_и_токен_бюджет_соблюдаются(self, tmpdir):
        be = LocalBackend(str(tmpdir / "db.db"))
        for i in range(5):
            be.store_fact(_fact(f"Хендлеры MCP {i}", ["mcp"]))
        cards = fetch_context("хендлеры MCP", backend=be, feedback=None, limit=2)
        assert len(cards) == 2

    def test_пустой_результат_валиден(self, tmpdir):
        be = LocalBackend(str(tmpdir / "db.db"))
        cards = fetch_context("хендлеры MCP", backend=be, feedback=None)
        assert cards == []

    def test_deprecated_не_доставляется(self, tmpdir):
        be = LocalBackend(str(tmpdir / "db.db"))
        be.store_fact(_fact("Хендлеры MCP", ["mcp"], status="deprecated"))
        cards = fetch_context("хендлеры MCP", backend=be, feedback=None)
        assert cards == []

    def test_usage_телеметрия_записывается_на_доставку(self, tmpdir):
        be = LocalBackend(str(tmpdir / "db.db"))
        be.store_fact(_fact("Хендлеры MCP", ["mcp"]))
        from curator.retrieval_feedback import RetrievalFeedback
        fb = RetrievalFeedback()
        fetch_context("хендлеры MCP", backend=be, feedback=fb)
        stats = fb.get_stats(top_n=10)
        assert any(s["title"] == "Хендлеры MCP" and s["count"] >= 1 for s in stats)

    def test_ошибка_бэкенда_не_ломает_вызов(self):
        class _Broken:
            def query_facts(self, query):
                raise RuntimeError("db corrupted")

        cards = fetch_context_safe("хендлеры MCP", backend=_Broken(), feedback=None)
        assert cards == []


class TestMcpContextTool:
    def test_mcp_возвращает_стабильный_json(self, tmpdir, monkeypatch):
        be = LocalBackend(str(tmpdir / "db.db"))
        be.store_fact(_fact("Хендлеры MCP", ["mcp"], source_file="session/tool.md"))
        monkeypatch.setattr(server_mod, "backend", be)

        result = json.loads(_context({"trigger": "хендлеры MCP"}))
        assert result["cards"][0]["title"] == "Хендлеры MCP"
        for card in result["cards"]:
            assert set(card) == {
                "title", "summary", "tags", "type", "status",
                "source_file", "score", "reason",
            }

    def test_mcp_пустой_триггер_пустой_json(self, monkeypatch):
        monkeypatch.setattr(server_mod, "backend", LocalBackend(":memory:"))
        result = json.loads(_context({"trigger": ""}))
        assert result["cards"] == []

    def test_mcp_ошибка_становится_ошибкой_в_json(self, tmpdir, monkeypatch):
        class _Broken:
            def query_facts(self, query):
                raise RuntimeError("boom")

        monkeypatch.setattr(server_mod, "backend", _Broken())
        result = json.loads(_context({"trigger": "хендлеры MCP"}))
        assert result["cards"] == []
        assert "error" in result


class TestCliContext:
    """CLI `curator context` — транспорт плагина: режим доставки задаёт
    CURATOR_DELIVERY_MODE (Task 10), карточки возвращаются в inject."""

    def test_cli_выводит_json(self, tmpdir, capsys, monkeypatch):
        be = LocalBackend(str(tmpdir / "db.db"))
        be.store_fact(_fact("Хендлеры MCP", ["mcp"]))
        monkeypatch.setattr(control_mod, "_make_backend", lambda: be)
        monkeypatch.setenv("CURATOR_DELIVERY_MODE", "inject")

        control_mod.cmd_context(["хендлеры", "MCP"])
        out = capsys.readouterr().out
        result = json.loads(out)
        assert result["cards"][0]["title"] == "Хендлеры MCP"
        assert result["count"] == 1

    def test_cli_пустой_параметр(self, capsys, monkeypatch):
        monkeypatch.setattr(control_mod, "_make_backend", lambda: LocalBackend(":memory:"))
        control_mod.cmd_context([])
        out = capsys.readouterr().out
        json.loads(out)


class TestFullMarkdownSeparate:
    def test_summary_это_выжимка_не_полный_md(self, tmpdir):
        be = LocalBackend(str(tmpdir / "db.db"))
        be.store_fact(_fact(
            "Хендлеры MCP", ["mcp"], source_file="session/tool.md",
            summary="Короткая выжимка про хендлеры в контексте MCP.",
        ))
        card = fetch_context("хендлеры MCP", backend=be, feedback=None)[0]
        assert card.source_file == "session/tool.md"
        assert len(card.summary) < 2000
