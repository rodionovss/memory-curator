"""Unit-тесты route-aware candidate generation в retrieval v2.

Пайплайн: direct-кандидаты (title/summary/tags) → метаданные маршрутов
(description/when_to_use/contains) → факты из сматченных файлов →
переранжирование каждого факта → threshold + limit + token budget.

Инварианты: маршрут поднимает кандидата, но никогда не минует порог;
deprecated исключён; порядок детерминирован.
"""

from curator.delivery import ContextQuery, retrieve
from curator.knowledge_routes import build_routes
from curator.models import StructuredFact


def _fact(
    title: str,
    tags: list[str],
    summary: str,
    source_file: str | None,
    status: str = "verified",
) -> StructuredFact:
    return StructuredFact(
        type="Reference", title=title, tags=tags, status=status,
        content_summary=summary, source_file=source_file,
    )


def _tool_facts() -> list[StructuredFact]:
    """Целевой факт + сосед: парапфраз проходит только через маршрут."""
    return [
        _fact(
            "Сигнатуры хендлеров", ["sdk", "python"],
            "Хендлеры принимают типизированные аргументы и возвращают результат.",
            "session/tool.md",
        ),
        _fact(
            "Тулинг сервера через SDK", ["tooling"],
            "Настройка тулинга сервера: запуск и отладка.",
            "session/tool.md",
        ),
    ]


def _compose_facts() -> list[StructuredFact]:
    """Широкая тема-файл: три факта, триггер осмысленно матчит только один."""
    return [
        _fact(
            "Coalescing в Compose списках", ["compose", "recomposition"],
            "Коалесценция recomposition влияет на производительность списков Compose.",
            "session/compose.md",
        ),
        _fact(
            "Preview-аннотации экранов", ["compose", "preview"],
            "Превью экранов: параметры и шрифты.", "session/compose.md",
        ),
        _fact(
            "RTL-раскладка строк", ["compose", "rtl"],
            "Поддержка RTL в раскладках строк.", "session/compose.md",
        ),
    ]


# Слова триггера есть в метаданных маршрута (теги + заголовок соседа),
# но прямого совпадения с целевым фактом не хватает до порога.
PARAPHRASE = "sdk сервера тулинг"


class TestRouteCandidates:
    def test_парапфраз_находит_факт_через_метаданные_маршрута(self, tmp_path):
        facts = _tool_facts()
        routes = build_routes(facts, tmp_path).routes
        cards = retrieve(ContextQuery(trigger=PARAPHRASE), facts, routes=routes)
        assert any(c.title == "Сигнатуры хендлеров" for c in cards)

    def test_без_маршрутов_парапфраз_не_проходит_порог(self):
        # baseline того же триггера: без маршрутов — тишна, не шум
        facts = _tool_facts()
        cards = retrieve(ContextQuery(trigger=PARAPHRASE), facts, routes=())
        assert not any(c.title == "Сигнатуры хендлеров" for c in cards)

    def test_routes_по_умолчанию_сохраняют_поведение(self):
        facts = _tool_facts()
        explicit = retrieve(ContextQuery(trigger=PARAPHRASE), facts, routes=())
        default = retrieve(ContextQuery(trigger=PARAPHRASE), facts)
        assert [c.title for c in explicit] == [c.title for c in default]


class TestRouteRules:
    def test_чужая_задача_не_тянет_весь_широкий_файл(self, tmp_path):
        facts = _compose_facts()
        routes = build_routes(facts, tmp_path).routes
        cards = retrieve(
            ContextQuery(trigger="почему recomposition медленный в списке"),
            facts, routes=routes,
        )
        titles = [c.title for c in cards]
        assert "Coalescing в Compose списках" in titles
        assert "Preview-аннотации экранов" not in titles
        assert "RTL-раскладка строк" not in titles

    def test_маршрут_не_минует_переранжирование_каждого_факта(self, tmp_path):
        # файл сматчен целиком (coverage 1.0), но факт без своего совпадения
        # остаётся ниже порога — буст кандидатуры, а не обход скоринга
        facts = [
            _fact("SDK сервера тулинг", ["sdk"], "Тулинг SDK сервера.",
                  "session/tool.md"),
            _fact("Настройка окон приложения", ["ui"],
                  "Окна приложения и их настройка.", "session/tool.md"),
        ]
        routes = build_routes(facts, tmp_path).routes
        cards = retrieve(ContextQuery(trigger=PARAPHRASE), facts, routes=routes)
        titles = [c.title for c in cards]
        assert "SDK сервера тулинг" in titles
        assert "Настройка окон приложения" not in titles

    def test_deprecated_в_сматченном_файле_исключён(self, tmp_path):
        facts = [
            _fact("Старые сигнатуры хендлеров", ["sdk"], "Устаревшие сигнатуры.",
                  "session/tool.md", status="deprecated"),
            _fact("SDK сервера тулинг", ["sdk"], "Тулинг SDK сервера.",
                  "session/tool.md"),
        ]
        routes = build_routes(facts, tmp_path).routes
        cards = retrieve(ContextQuery(trigger=PARAPHRASE), facts, routes=routes)
        titles = [c.title for c in cards]
        assert "Старые сигнатуры хендлеров" not in titles
        assert "SDK сервера тулинг" in titles

    def test_буст_применяется_только_к_своему_файлу(self, tmp_path):
        facts = _tool_facts() + [
            _fact("Превью экранов", ["compose", "preview"],
                  "Превью Compose-экранов.", "session/compose.md"),
        ]
        routes = build_routes(facts, tmp_path).routes
        cards = retrieve(ContextQuery(trigger=PARAPHRASE), facts, routes=routes)
        titles = [c.title for c in cards]
        assert any(t == "Сигнатуры хендлеров" for t in titles)
        assert "Превью экранов" not in titles


class TestRouteCardContract:
    def test_source_file_сохранён_и_route_фрагмент_в_reason(self, tmp_path):
        facts = _tool_facts()
        routes = build_routes(facts, tmp_path).routes
        cards = retrieve(ContextQuery(trigger=PARAPHRASE), facts, routes=routes)
        target = next(c for c in cards if c.title == "Сигнатуры хендлеров")
        assert target.source_file == "session/tool.md"
        assert target.status == "verified"
        assert "route:session/tool.md" in target.reason
        # существующие фрагменты остаются валидными для вызывающих
        assert "теги: sdk" in target.reason

    def test_прямой_кандидат_без_маршрутного_фрагмента(self, tmp_path):
        facts = _tool_facts()
        routes = build_routes(facts, tmp_path).routes
        cards = retrieve(ContextQuery(trigger=PARAPHRASE), facts, routes=routes)
        sibling = next(c for c in cards if c.title == "Тулинг сервера через SDK")
        assert "совпадение в заголовке" in sibling.reason
        assert "route:" not in sibling.reason


class TestRouteDeterminism:
    def test_повторные_вызовы_идентичны(self, tmp_path):
        facts = _tool_facts() + _compose_facts()
        routes = build_routes(facts, tmp_path).routes
        q = ContextQuery(trigger=PARAPHRASE)
        result1 = retrieve(q, facts, routes=routes)
        result2 = retrieve(q, facts, routes=routes)
        assert [(c.title, c.score) for c in result1] == \
               [(c.title, c.score) for c in result2]

    def test_порядок_score_desc_затем_title(self, tmp_path):
        facts = _tool_facts() + _compose_facts()
        routes = build_routes(facts, tmp_path).routes
        cards = retrieve(ContextQuery(trigger=PARAPHRASE), facts, routes=routes)
        keys = [(-c.score, c.title) for c in cards]
        assert keys == sorted(keys)
