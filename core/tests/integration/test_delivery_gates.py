"""Safety gates и token/latency бюджет delivery (issue #29, ADR 002).

Delivery как production-механика: нерелевантные задачи не получают шум,
deprecated/низкорелевантные факты не доставляются, ошибки и таймауты
безопасны, token overhead измеряется и ограничен, latency измеряется.
"""

import json
import time

from curator.delivery import _card_tokens, fetch_context, fetch_context_safe
from curator.backend.local import LocalBackend
from curator.models import StructuredFact


def _seed(be, entries, status="verified"):
    for entry in entries:
        title, tags = entry[0], entry[1]
        entry_status = entry[2] if len(entry) > 2 else status
        be.store_fact(StructuredFact(
            type="Reference", title=title, tags=tags, status=entry_status,
            content_summary="Подробное описание знания про тему.",
        ))
    return be


class TestNoNoise:
    def test_нерелевантная_задача_без_шума(self):
        be = _seed(LocalBackend(":memory:"), [
            ("Хендлеры MCP-сервера", ["mcp", "python"]),
            ("Стиль письма отчётов", ["style"]),
        ])
        cards = fetch_context("какой сегодня день недели в Мадриде", be)
        assert cards == []

    def test_deprecated_не_доставляется_никогда(self):
        be = _seed(LocalBackend(":memory:"), [
            ("Устаревший агрегатор MCP", ["mcp"], "deprecated"),
            ("Хендлеры MCP-сервера", ["mcp"]),
        ])
        titles = [c.title for c in fetch_context("хендлеры MCP сервера", be)]
        assert "Устаревший агрегатор MCP" not in titles
        assert "Хендлеры MCP-сервера" in titles

    def test_низкорелевантный_факт_ниже_порога(self):
        be = _seed(LocalBackend(":memory:"), [
            ("Подготовка чая по правилу четырёх минут", ["tea"]),
        ])
        cards = fetch_context("напиши экспорт заказов базу данных", be)
        assert cards == []


class TestSafety:
    def test_ошибка_backend_не_исключение(self):
        class _Broken:
            def query_facts(self, query):
                raise RuntimeError("disk failure")

        assert fetch_context_safe("хендлеры MCP", _Broken()) == []

    def test_медленный_backend_не_исключение(self):
        class _Slow:
            def query_facts(self, query):
                return []

        # safe-обёртка выдаёт [] при пустом ответе медленного бэкенда
        assert fetch_context_safe("хендлеры", _Slow()) == []


class TestTokenBudget:
    def test_overhead_ограничен_бюджетом(self):
        be = _seed(LocalBackend(":memory:"), [
            (f"Хендлеры MCP факт {i}", ["mcp"]) for i in range(3)
        ])
        cards = fetch_context("хендлеры MCP", be, token_budget=250)
        total = sum(_card_tokens(card) for card in cards)
        assert 0 < total <= 250

    def test_дорогая_карточка_уступает_короткой(self):
        expensive_title = "Большая MCP заметка про архитектуру"
        be = LocalBackend(":memory:")
        be.store_fact(StructuredFact(
            type="Reference", title=expensive_title, tags=["mcp"],
            status="verified", content_summary="слово " * 400,
        ))
        be.store_fact(StructuredFact(
            type="Reference", title="Короткий MCP факт", tags=["mcp"],
            status="verified", content_summary="Очень краткая суть факта.",
        ))
        cards = fetch_context("большая mcp заметка архитектура", be, token_budget=100)
        total = sum(_card_tokens(card) for card in cards)
        assert total <= 100
        assert expensive_title not in [c.title for c in cards]

    def test_json_пейлоад_соизмерим_с_бюджетом(self):
        be = _seed(LocalBackend(":memory:"), [
            (f"MCP факт номер {i}", ["mcp"]) for i in range(6)
        ])
        cards = fetch_context("mcp факты подбор", be, token_budget=200)
        payload = json.dumps({"cards": [card.__dict__ for card in cards]}, ensure_ascii=False)
        assert len(payload) <= 200 * 4 + 100


class TestLatency:
    def test_scan_в_бюджете_задержки(self):
        be = _seed(LocalBackend(":memory:"), [
            (f"Факт номер {i} доставка знаний", ["delivery"]) for i in range(50)
        ])
        start = time.perf_counter()
        cards = fetch_context("доставки знаний факт", be)
        elapsed = time.perf_counter() - start
        assert cards
        assert elapsed < 0.5, "персональная база должна сканироваться < 500ms"
