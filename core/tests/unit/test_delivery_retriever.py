"""Unit-тесты retriever-а proactive delivery (ADR 002, issue #26).

Контракт: query → ranked context cards. Детерминированный ranking,
deprecated исключён, слабое совпадение — silence, а не шум.
"""

from curator.delivery import ContextCard, ContextQuery, retrieve
from curator.models import StructuredFact


def _fact(
    title: str,
    tags: list[str],
    summary: str = "Знание про хендлеры и сигнатуры MCP-сервера на Python.",
    status: str = "verified",
    type_: str = "Reference",
) -> StructuredFact:
    return StructuredFact(
        type=type_, title=title, tags=tags, status=status,
        content_summary=summary,
    )


def _usage(title: str, count: int, last_access: float) -> dict:
    return {title: {"count": count, "last_access": last_access}}


class TestRanking:
    def test_лучшее_совпадение_раньше_слабого(self):
        good = _fact("MCP SDK: правильная сигнатура хендлеров", ["python", "mcp"])
        weak = _fact("Устройство флоков в POSIX", ["posix"])
        cards = retrieve(
            ContextQuery(trigger="как правильно писать хендлеры MCP"),
            [good, weak],
            usage={},
        )
        # сильный факт выше порога, слабый не проходит — silence вместо шума
        assert len(cards) == 1
        assert cards[0].title == good.title
        assert isinstance(cards[0], ContextCard)

    def test_детерминированность_повторных_вызовов(self):
        facts = [
            _fact("Хендлеры MCP-сервера", ["python", "mcp"]),
            _fact("MCP SDK сигнатуры", ["python", "sdk"]),
            _fact("Токен-бюджет доставки", ["delivery", "tokens"]),
        ]
        q = ContextQuery(trigger="хендлеры MCP сигнатуры")
        result1 = retrieve(q, facts, usage={})
        result2 = retrieve(q, facts, usage={})
        assert [(c.title, c.score) for c in result1] == [(c.title, c.score) for c in result2]


class TestNormalization:
    def test_регистр_сводится_вниз(self):
        good = _fact("Хендлеры MCP-сервера", ["mcp"])
        cards = retrieve(
            ContextQuery(trigger="ХЕНДЛЕРЫ mcp"),
            [good],
            usage={},
        )
        assert cards[0].title == good.title

    def test_кириллица_матчится_без_SQL_LIKE(self):
        # регрессия: SQLite LIKE не матчит кириллицу — retrieval должен
        good = _fact("Правильная работа с флоками", ["posix"])
        cards = retrieve(
            ContextQuery(trigger="как правильно работать с ФЛОКАМИ"),
            [good],
            usage={},
        )
        assert any(c.title == good.title for c in cards)


class TestSearchCoverage:
    def test_факт_опознаваемый_только_тегами(self):
        # регрессия T09: факт, опознаваемый только тегами, не находился
        good = _fact("Маргинальная выгода в ленте", ["marginal-gain"])
        cards = retrieve(
            ContextQuery(trigger="как применить marginal-gain в ленте молчаний"),
            [good],
            usage={},
        )
        assert cards

    def test_совпадение_summary_считается(self):
        summary = "Коалесценция recomposition влияет на производительность Compose-списков."
        good = _fact("Coalescing в Compose", ["compose", "recomposition"], summary=summary)
        cards = retrieve(
            ContextQuery(trigger="почему recomposition медленный в списке"),
            [good],
            usage={},
        )
        assert any(c.title == good.title for c in cards)

    def test_title_весомее_summary(self):
        title_fact = _fact("recomposition производительность Compose", ["a"], summary="Нет слов из запроса вообще ни одного из них тут.")
        summary_fact = _fact("Совсем другой заголовок", ["b"], summary="recomposition производительность Compose кратко упомянуты в теле.")
        cards = retrieve(
            ContextQuery(trigger="recomposition производительность Compose"),
            [summary_fact, title_fact],
            usage={},
        )
        assert cards[0].title == title_fact.title


class TestFilters:
    def test_deprecated_исключён_всегда(self):
        deprecated = _fact("Хендлеры MCP (устарело)", ["mcp"], status="deprecated")
        cards = retrieve(
            ContextQuery(trigger="хендлеры MCP"),
            [deprecated],
            usage={},
        )
        assert not cards

    def test_hypothesis_скрыт_пока_явно_не_запрошен(self):
        hyp = _fact("Хендлеры MCP гипотеза", ["mcp"], status="hypothesis")
        cards = retrieve(ContextQuery(trigger="хендлеры MCP"), [hyp], usage={})
        assert not cards
        ok = retrieve(
            ContextQuery(trigger="хендлеры MCP", include_hypothesis=True),
            [hyp], usage={},
        )
        assert len(ok) == 1

    def test_types_фильтр(self):
        tool = _fact("Планировщик задач", ["cron"], type_="Tool")
        cards = retrieve(
            ContextQuery(trigger="планировщик задач cron", types=["Reference"]),
            [tool],
            usage={},
        )
        assert not cards
        ok = retrieve(
            ContextQuery(trigger="планировщик задач cron", types=["Tool"]),
            [tool],
            usage={},
        )
        assert len(ok) == 1

    def test_exclude_tags_исключает_факт(self):
        fact = _fact("Хендлеры MCP", ["mcp", "experimental"])
        cards = retrieve(
            ContextQuery(trigger="хендлеры MCP", exclude_tags=["experimental"]),
            [fact],
            usage={},
        )
        assert not cards


class TestBudget:
    def test_limit_ограничивает_выдачу(self):
        facts = [_fact(f"Хендлеры MCP {i}", ["mcp"]) for i in range(5)]
        cards = retrieve(
            ContextQuery(trigger="хендлеры MCP", limit=2),
            facts,
            usage={},
        )
        assert len(cards) == 2

    def test_токен_бюджет_отсекает_дорогую_карточку(self):
        long_summary = "хендлеры MCP " * 500  # ~ много токенов
        expensive = _fact("Хендлеры MCP A", ["mcp"], summary=long_summary)
        cheap = _fact("Хендлеры MCP B", ["mcp"])
        cards = retrieve(
            ContextQuery(trigger="хендлеры MCP", token_budget=100),
            [expensive, cheap],
            usage={},
        )
        titles = [c.title for c in cards]
        assert cheap.title in titles
        assert expensive.title not in titles

    def test_score_и_source_file_в_карточке(self):
        good = _fact("Хендлеры MCP", ["mcp"])
        good.source_file = "session/tool.md"
        cards = retrieve(
            ContextQuery(trigger="хендлеры MCP"),
            [good],
            usage=_usage("Хендлеры MCP", 7, 0.0),
        )
        card = cards[0]
        assert card.source_file == "session/tool.md"
        assert card.status == "verified"
        assert 0.0 < card.score <= 1.0
        assert card.reason


class TestSilence:
    def test_слабое_совпадение_тишина_не_шум(self):
        noise = _fact("Устройство флоков в POSIX", ["posix"])
        cards = retrieve(
            ContextQuery(trigger="как варить борщ и что такое сметана вообще"),
            [noise],
            usage={},
        )
        assert not cards

    def test_usage_поднимает_ранг_используемого_факта(self):
        both = _fact("Хендлеры MCP", ["mcp"])
        cards_no_usage = retrieve(
            ContextQuery(trigger="хендлеры MCP"),
            [both], usage={},
        )
        # свежее обращение: now фиксирован, last_access ровно сейчас
        u = _usage("Хендлеры MCP", 20, 0.0)
        cards_with_usage = retrieve(
            ContextQuery(trigger="хендлеры MCP"),
            [both],
            usage=u,
            now=0.0,
        )
        assert cards_with_usage[0].score > cards_no_usage[0].score


class TestNearMissTelemetry:
    """Кандидаты ниже порога: сбор для shadow-телеметрии, не для выдачи."""

    def test_near_miss_собирается_и_топ3(self):
        good = _fact("MCP SDK: правильная сигнатура хендлеров", ["python", "mcp"])
        near = [
            _fact(f"Слабый кандидат номер {i}", ["python", "mcp"],
                  summary="Смежное знание про MCP и сигнатуры хендлеров.")
            for i in range(1, 6)
        ]
        misses: list[tuple[str, float]] = []
        cards = retrieve(
            ContextQuery(trigger="как правильно писать хендлеры MCP"),
            [good] + near,
            usage={},
            near_misses=misses,
        )
        assert len(cards) == 1, "выдача без изменений: near-miss только телеметрия"
        assert 1 <= len(misses) <= 3, "топ-3, не больше"
        assert all(score < 0.4 for _, score in misses), "все ниже порога"
        scores = [s for _, s in misses]
        assert scores == sorted(scores, reverse=True), "score desc"

    def test_near_miss_пуст_когда_всё_выше_порога(self):
        good = _fact("Хендлеры MCP", ["mcp"])
        misses: list[tuple[str, float]] = []
        retrieve(
            ContextQuery(trigger="хендлеры MCP"),
            [good],
            usage={},
            near_misses=misses,
        )
        assert misses == [], "нет кандидатов ниже порога — сборщик пуст"

    def test_без_сборщика_поведение_не_меняется(self):
        good = _fact("Хендлеры MCP", ["mcp"])
        cards = retrieve(
            ContextQuery(trigger="хендлеры MCP"),
            [good], usage={},
        )
        assert cards, "обратная совместимость: параметр опционален"
