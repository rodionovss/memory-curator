"""Integration-тесты retrieval v2: fetch_context строит маршруты из фактов.

Отказоустойчивость RouteBuildResult (semantics задачи 7):
- ошибки валидации + есть маршруты → лог всех ошибок, частичные маршруты;
- ошибки + нет маршрутов → лог, fact-only fallback без исключения;
- падение сборки маршрутов → лог, fact-only fallback;
- пустые маршруты без ошибок → валидное состояние, не шумит.

Маршрут поднимает кандидатуру факта, но порог переранжирования не обходится.
"""

import curator.delivery as delivery
from curator.backend.local import LocalBackend
from curator.delivery import fetch_context
from curator.models import StructuredFact


def _fact(
    title: str,
    tags: list[str],
    summary: str,
    source_file: str | None = None,
    status: str = "verified",
) -> StructuredFact:
    return StructuredFact(
        type="Reference", title=title, tags=tags, status=status,
        content_summary=summary, source_file=source_file,
    )


def _seeded(facts: list[StructuredFact]) -> LocalBackend:
    be = LocalBackend(":memory:")
    for f in facts:
        be.store_fact(f)
    return be


def _tool_facts() -> list[StructuredFact]:
    return [
        _fact("Сигнатуры хендлеров", ["sdk", "python"],
              "Хендлеры принимают типизированные аргументы.",
              "session/tool.md"),
        _fact("Тулинг сервера через SDK", ["tooling"],
              "Настройка тулинга сервера.", "session/tool.md"),
    ]


PARAPHRASE = "sdk сервера тулинг"


class TestRouteDelivery:
    def test_fetch_context_находит_факт_через_маршрут(self, tmp_path):
        be = _seeded(_tool_facts())
        cards = fetch_context(PARAPHRASE, be, None, base_dir=tmp_path)
        assert any(c.title == "Сигнатуры хендлеров" for c in cards)
        assert all(c.source_file == "session/tool.md" for c in cards)

    def test_deprecated_в_сматченном_файле_не_доставляется(self, tmp_path):
        be = _seeded(_tool_facts() + [
            _fact("Старые сигнатуры хендлеров", ["sdk"],
                  "Устаревшие сигнатуры.", "session/tool.md", status="deprecated"),
        ])
        titles = [c.title for c in fetch_context(PARAPHRASE, be, None, base_dir=tmp_path)]
        assert "Старые сигнатуры хендлеров" not in titles
        assert "Сигнатуры хендлеров" in titles

    def test_детерминированность_fetch_context(self, tmp_path):
        be = _seeded(_tool_facts())
        r1 = fetch_context(PARAPHRASE, be, None, base_dir=tmp_path)
        r2 = fetch_context(PARAPHRASE, be, None, base_dir=tmp_path)
        assert [(c.title, c.score) for c in r1] == [(c.title, c.score) for c in r2]


class TestRouteFallbacks:
    def test_ошибки_без_маршрутов_fact_only_fallback(self, tmp_path, capsys):
        be = _seeded([_fact("Хендлеры MCP-сервера", ["mcp"],
                            "Сигнатуры хендлеров MCP-сервера.", source_file=None)])
        cards = fetch_context("хендлеры mcp сервера", be, None, base_dir=tmp_path)
        assert [c.title for c in cards] == ["Хендлеры MCP-сервера"]
        assert "отсутствует source_file" in capsys.readouterr().err

    def test_частичные_маршруты_используются_при_ошибках(self, tmp_path, capsys):
        be = _seeded(_tool_facts() + [
            _fact("Факт без файла", ["misc"], "Без source_file.", source_file=None),
        ])
        cards = fetch_context(PARAPHRASE, be, None, base_dir=tmp_path)
        assert any(c.title == "Сигнатуры хендлеров" for c in cards)
        assert "отсутствует source_file" in capsys.readouterr().err

    def test_падение_сборки_маршрутов_fact_only_fallback(self, tmp_path, monkeypatch, capsys):
        be = _seeded(_tool_facts())

        def _boom(facts, base_dir):
            raise RuntimeError("route build exploded")

        monkeypatch.setattr(delivery, "build_routes", _boom)
        cards = fetch_context(
            "тулинг сервера через sdk", be, None, base_dir=tmp_path,
        )
        assert [c.title for c in cards] == ["Тулинг сервера через SDK"]
        assert "route build exploded" in capsys.readouterr().err

    def test_пустые_маршруты_без_ошибок_не_шумят(self, tmp_path, capsys):
        # база без активных фактов: routes=(), errors=() — валидное состояние
        be = _seeded([_fact("Устаревшее знание", ["mcp"],
                            "Отсутствует в выдаче.", status="deprecated")])
        cards = fetch_context("устаревшее знание", be, None, base_dir=tmp_path)
        assert cards == []
        assert capsys.readouterr().err == ""
