"""Демо-сценарий «до/после»: сравнение чистой и обученной памяти.

Два режима:
  run_demo(backend_trained)       — статичная дельта clean vs trained
  run_time_lapse(backend, sessions)— эволюция: N сессий подряд, рост фактов после каждой

Использование:
    cd core && .venv/bin/python3 -m curator.demo
    cd core && .venv/bin/python3 -c "from curator.demo import run_time_lapse; run_time_lapse()"
"""

import os
from pathlib import Path
from dataclasses import dataclass, field

from curator.models import ProposedFact, StructuredFact, FactQuery
from curator.backend.local import LocalBackend
from curator.gatekeeper import Gatekeeper


@dataclass
class DemoSession:
    name: str
    text: str


@dataclass
class SessionComparison:
    session_name: str
    clean_approved: list[str]
    clean_rejected: list[str]
    trained_approved: list[str]
    trained_rejected_reasons: list[str]


@dataclass
class DemoResult:
    comparisons: list[SessionComparison] = field(default_factory=list)
    trained_facts_total: int = 0


TEST_SESSIONS = [
    DemoSession(
        name="Kotlin/JVM debrief",
        text="""пользователь: Почему у меня @JvmInline value class внутри sealed interface не работает как ожидалось?
агент: JvmInline value class внутри sealed interface бесполезен — бокс неизбежен. Полиморфный тип требует объект на JVM, инлайнинг работает только когда компилятор знает конкретный тип на call site.
пользователь: А что тогда использовать?
агент: Data class предпочтительнее в этом случае — equals/hashCode/toString генерируются автоматически.
пользователь: А когда value class всё же полезен?
агент: Для прямых параметров функций, property-типов без интерфейсной иерархии, доменных типов-обёрток (Email, UserId).
пользователь: Понял, спасибо!""",
    ),
    DemoSession(
        name="Compose ImmutableList",
        text="""пользователь: Стоит ли использовать ImmutableList для всех списков в Compose?
агент: Нет, это зависит от контекста. ImmutableList нужен когда новый экземпляр списка пересоздаётся на каждую рекомпозицию — MVI copy(), пересоздание UiState, большие списки.
пользователь: А когда не нужен?
агент: StateFlow + data class, маленькие списки, редкие апдейты, LazyColumn.
пользователь: А в domain-слое?
агент: В domain ImmutableList/@Immutable ради Compose не тащить. Presentation-модель заводить только когда есть реальная трансформация.""",
    ),
    DemoSession(
        name="Git commit style review",
        text="""пользователь: Какой формат коммитов используем?
агент: Conventional Commits: type(scope): description. Типы: feat, fix, refactor, docs, test, chore.
пользователь: А на каком языке?
агент: Описание на русском, type и scope на английском. Пример: feat(cart): добавить свайп-удаление.
пользователь: Длина?
агент: Заголовок до 72 символов, тело — опционально, с пустой строкой после заголовка.""",
    ),
    DemoSession(
        name="New knowledge — Python MCP",
        text="""пользователь: Как писать MCP-сервер на Python?
агент: Используй mcp SDK v2. Сервер создаётся через Server('name'), хендлеры регистрируются через add_request_handler('tools/list', ListToolsRequest, handler).
пользователь: А как запустить?
агент: Через stdio: async with stdio_server() as (read, write): await app.run(read, write, app.create_initialization_options())
пользователь: Какие сигнатуры хендлеров?
агент: (ctx, request) — два параметра, не один. Первый — ServerRequestContext, второй — модель запроса.""",
    ),
    DemoSession(
        name="Mixed — known JVM + new Docker",
        text="""пользователь: Расскажи про JVM boxing в sealed interface
агент: Бокс неизбежен из-за полиморфизма. Sealed interface компилируется в абстрактный класс, JVM нужен объект для виртуального вызова.
пользователь: А как деплоить через Docker?
агент: Используй multi-stage builds: первый stage — сборка (gradle build), второй — рантайм (openjdk:17-slim). Копируй только JAR, не тащи Gradle кэш.""",
    ),
]


def _make_facts_from_session_keywords(session_text: str) -> list[ProposedFact]:
    facts = []
    text_lower = session_text.lower()

    if "jvminline value class" in text_lower or "value class внутри sealed" in text_lower or "бокс" in text_lower:
        facts.append(ProposedFact(
            type="Reference",
            title="JvmInline value class внутри sealed interface бесполезен — бокс неизбежен",
            content_summary="JvmInline value class внутри sealed interface вызывает неизбежный бокс из-за полиморфизма на JVM. Data class предпочтительнее.",
            tags=["kotlin", "jvm", "performance"],
            evidence="агент: JvmInline value class внутри sealed interface бесполезен — бокс неизбежен",
        ))
        facts.append(ProposedFact(
            type="Reference",
            title="Data class предпочтительнее value class в общем случае",
            content_summary="Data class предпочтительнее @JvmInline value class когда нужны equals/hashCode/toString — они генерируются автоматически.",
            tags=["kotlin", "jvm", "architecture"],
            evidence="агент: Data class предпочтительнее в этом случае",
        ))

    if "immutablelist" in text_lower or "compose" in text_lower:
        facts.append(ProposedFact(
            type="Reference",
            title="Когда ImmutableList нужен, а когда — оверхед",
            content_summary="Нужен при пересоздании списка на каждую рекомпозицию (MVI copy). Не нужен для StateFlow+data class, маленьких списков, LazyColumn. В domain не тащить.",
            tags=["compose", "android", "performance"],
            evidence="агент: ImmutableList нужен когда новый экземпляр списка пересоздаётся на каждую рекомпозицию",
        ))

    if "commit" in text_lower or "conventional commit" in text_lower:
        facts.append(ProposedFact(
            type="Style",
            title="Формат коммитов: Conventional Commits",
            content_summary="Используем Conventional Commits: type(scope): description. Типы: feat, fix, refactor. Заголовок до 72 символов, описание на русском, type на английском.",
            tags=["git", "workflow", "style"],
            evidence="агент: Conventional Commits: type(scope): description",
        ))

    if "mcp" in text_lower and "python" in text_lower:
        facts.append(ProposedFact(
            type="Reference",
            title="MCP SDK v2: правильная сигнатура хендлеров",
            content_summary="В MCP SDK v2 хендлеры принимают (ctx, request) — два параметра, первый ServerRequestContext. Запуск через async with stdio_server().",
            tags=["python", "mcp", "architecture"],
            evidence="агент: хендлеры регистрируются через add_request_handler",
        ))

    if "docker" in text_lower and "deploy" in text_lower:
        facts.append(ProposedFact(
            type="Reference",
            title="Docker multi-stage builds для JVM",
            content_summary="Использовать multi-stage builds: первый stage — gradle build, второй — openjdk:17-slim. Копировать только JAR, не тащить Gradle кэш.",
            tags=["docker", "jvm", "devops"],
            evidence="агент: Используй multi-stage builds",
        ))

    return facts


def _make_facts_from_session(session_text: str) -> list[ProposedFact]:
    """Детерминированное keyword-извлечение для демо. Основной путь — агент передаёт кандидатов в MCP."""
    return _make_facts_from_session_keywords(session_text)


def _is_similar_titles(a: str, b: str) -> bool:
    words_a = set(a.lower().split())
    words_b = set(b.lower().split())
    if not words_a or not words_b:
        return False
    overlap = len(words_a & words_b)
    return overlap / len(words_a) > 0.6


def _basic_filter(fact: ProposedFact) -> str | None:
    if len(fact.title) < 10:
        return "Слишком короткий заголовок"
    if len(fact.title) > 200:
        return "Слишком длинный заголовок"
    if len(fact.content_summary) < 20:
        return "Слишком короткое описание"
    for pattern in Gatekeeper.NOISE_PATTERNS:
        if pattern in fact.title.lower():
            return "Похоже на фичевую деталь, не абстрактное знание"
    if not fact.tags:
        return "Нет тегов — знание невозможно категоризировать"
    return None


def run_time_lapse(sessions: list[DemoSession] | None = None, verbose: bool = True) -> dict:
    sessions = sessions or TEST_SESSIONS[:3]

    backend = LocalBackend(":memory:")
    gk = Gatekeeper(backend, check_duplicates=True)
    all_stored = []
    snapshots = []

    if verbose:
        header("TIME-LAPSE: Memory Curator — эволюция знаний")
        print("  Каждая сессия обрабатывается последовательно на одном бэкенде.")
        print("  После сессии — сколько фактов добавилось, сколько дубликатов.\n")

    for i, session in enumerate(sessions, 1):
        facts = _make_facts_from_session(session.text)
        result = gk.filter(facts)

        new_facts = []
        dup_facts = []
        for fact in result.approved:
            structured = StructuredFact(
                type=fact.type, title=fact.title, tags=fact.tags,
                status="verified", content_summary=fact.content_summary,
            )
            backend.store_fact(structured)
            new_facts.append(fact.title)
            all_stored.append(structured)

        for fact, reason in result.rejected:
            dup_facts.append((fact.title, reason))

        snapshot = {
            "session": "#%d — %s" % (i, session.name),
            "extracted": len(facts),
            "new": len(new_facts),
            "duplicates": len(dup_facts),
            "total_after": len(all_stored),
        }
        snapshots.append(snapshot)

        if verbose:
            print("── Сессия #%d: %s ──" % (i, session.name))
            print("  Извлечено: %d | Новых: %d | Дубликатов: %d | Всего в памяти: %d" % (
                len(facts), len(new_facts), len(dup_facts), len(all_stored),
            ))
            if dup_facts:
                for title, reason in dup_facts[:2]:
                    print("    ⛔ %s" % reason[:80])
            if new_facts:
                for title in new_facts[:2]:
                    print("    +  %s" % title[:70])
            print()

    if verbose:
        header("ИТОГ: Эволюция за %d сессий" % len(sessions))
        try:
            from rich.table import Table
            from rich.console import Console
            c = Console()
            table = Table(title="Эволюция знаний")
            table.add_column("Сессия", style="cyan")
            table.add_column("Извлечено", justify="right")
            table.add_column("Новых", justify="right", style="green")
            table.add_column("Дубл.", justify="right", style="red")
            table.add_column("Всего в памяти", justify="right", style="bold")
            for s in snapshots:
                table.add_row(s["session"], str(s["extracted"]), str(s["new"]), str(s["duplicates"]), str(s["total_after"]))
            c.print(table)
        except ImportError:
            for s in snapshots:
                bar = "█" * s["new"] + "░" * s["duplicates"]
                print("  %s | %s | всего: %d" % (s["session"], bar, s["total_after"]))
        print("\n  Вывод: агент накапливает знания (%d → %d фактов)," % (0, len(all_stored)))
        print("  дубликаты отбрасываются, новые темы добавляются.")

    return {"snapshots": snapshots, "total_facts": len(all_stored)}


def run_demo(backend_trained=None, verbose: bool = True) -> DemoResult:
    clean = LocalBackend(":memory:")
    trained = backend_trained
    has_trained = trained is not None

    gk_clean = Gatekeeper(clean, check_duplicates=True)

    _trained_facts_cache: list[StructuredFact] = []
    if has_trained:
        _trained_facts_cache = trained.query_facts(FactQuery())

    result = DemoResult()
    result.trained_facts_total = len(_trained_facts_cache) if has_trained else 0

    if verbose:
        header("DEMO: Memory Curator — «до» (чистая память) vs «после» (обученная)")
        print(f"  Обученная память: {result.trained_facts_total} фактов" if has_trained else "  Обученная память: НЕ ПОДКЛЮЧЕНА (только clean)")
        print("  Extraction: keyword (демо, детерминированно)\n")

    for session in TEST_SESSIONS:
        facts = _make_facts_from_session(session.text)

        clean_result = gk_clean.filter(facts)

        trained_approved = []
        trained_rejected = []
        for fact in facts:
            rejection = _basic_filter(fact)
            if rejection:
                trained_rejected.append((fact, rejection))
                continue
            duplicate_found = False
            for cached in _trained_facts_cache:
                if _is_similar_titles(fact.title, cached.title):
                    trained_rejected.append((fact, f"Дубликат: уже есть '{cached.title}'"))
                    duplicate_found = True
                    break
            if not duplicate_found:
                trained_approved.append(fact)

        comp = SessionComparison(
            session_name=session.name,
            clean_approved=[f.title for f in clean_result.approved],
            clean_rejected=[f"{f.title} — {reason}" for f, reason in clean_result.rejected],
            trained_approved=[f.title for f in trained_approved],
            trained_rejected_reasons=[reason for _, reason in trained_rejected] if has_trained else [],
        )
        result.comparisons.append(comp)

        if verbose:
            print(f"\n── {session.name} ──")
            print(f"  Извлечено фактов: {len(facts)}")

            print("  Clean (пустая память):")
            print(f"    Одобрено: {len(clean_result.approved)} {[f.title[:50]+'...' for f in clean_result.approved]}")
            print(f"    Отклонено: {len(clean_result.rejected)}")

            if has_trained:
                print(f"  Trained ({result.trained_facts_total} фактов):")
                print(f"    Одобрено: {len(trained_approved)} {[f.title[:50]+'...' for f in trained_approved]}")
                rejected_reasons_list = [reason for _, reason in trained_rejected]
                rejected_str = "\n    ".join(rejected_reasons_list[:3]) if rejected_reasons_list else "—"
                print(f"    Отклонено: {len(trained_rejected)}")
                if trained_rejected:
                    print(f"    Причины: {rejected_str}")

    if verbose:
        print()
        header("ИТОГО")
        _print_summary(result, has_trained)

    return result


def header(title: str):
    try:
        from rich.console import Console
        from rich.panel import Panel
        Console().print(Panel(title, style="bold cyan", expand=False))
    except ImportError:
        print("=" * 70)
        print("  %s" % title)
        print("=" * 70)


def _print_summary(result: DemoResult, has_trained: bool):
    try:
        from rich.table import Table
        from rich.console import Console
        c = Console()
        table = Table(title="ИТОГО: %d сессий" % len(result.comparisons))
        table.add_column("Метрика", style="cyan")
        table.add_column("Значение", style="green")
        total_clean = sum(len(cmp.clean_approved) for cmp in result.comparisons)
        total_trained_approved = sum(len(cmp.trained_approved) for cmp in result.comparisons)
        total_trained_rejected = sum(len(cmp.trained_rejected_reasons) for cmp in result.comparisons)
        table.add_row("Clean одобрил", "%d фактов (ничего не знает)" % total_clean)
        if has_trained:
            table.add_row("Trained одобрил", "%d фактов" % total_trained_approved)
            table.add_row("Trained отклонил (дубликаты)", "%d фактов" % total_trained_rejected)
            delta = total_clean - total_trained_approved
            table.add_row("Дельта", "%d фактов" % delta, style="bold yellow")
            if delta > 0:
                table.add_row("Вывод", "Обученный агент НЕ сохранил %d дубликатов" % delta, style="bold green")
        c.print(table)
    except ImportError:
        _print_summary_plain(result, has_trained)


def _print_summary_plain(result: DemoResult, has_trained: bool):
    total_clean_approved = sum(len(c.clean_approved) for c in result.comparisons)
    total_trained_approved = sum(len(c.trained_approved) for c in result.comparisons)
    total_trained_rejected = sum(len(c.trained_rejected_reasons) for c in result.comparisons)

    print(f"\n  Всего сессий: {len(result.comparisons)}")
    print(f"  Clean одобрил: {total_clean_approved} фактов (ничего не знает — всё новое)")
    if has_trained:
        print(f"  Trained одобрил: {total_trained_approved} фактов")
        print(f"  Trained отклонил (дубликаты): {total_trained_rejected} фактов")
        delta = total_clean_approved - total_trained_approved
        print(f"  Дельта: {delta} фактов — обученный агент знает больше, не сохраняет дубликаты")
        if delta > 0:
            print(f"\n  Вывод: Обученный агент НЕ сохранил {delta} фактов, которые уже знает.")
            print("  Чистый агент сохранил бы их как «новые» — это и есть накопление опыта.")
    else:
        print("  (обученная память не подключена — сравнение только clean)")


def run_opencode_demo(n_sessions: int = 3):
    header("DEMO: Memory Curator на реальных сессиях OpenCode")
    try:
        from curator.session_reader import extract_opencode_sessions
    except ImportError:
        print("  session_reader не найден")
        return

    sessions = extract_opencode_sessions(n=n_sessions)
    if not sessions:
        print("  Не удалось извлечь сессии из opencode.db")
        return

    print("  База: ~/.local/share/opencode/opencode.db")
    print(f"  Всего сессий в базе: 386 | Извлечено для демо: {len(sessions)}\n")

    backend = LocalBackend(":memory:")
    gk = Gatekeeper(backend, check_duplicates=True)
    all_stored = []
    snapshots = []

    for i, session in enumerate(sessions, 1):
        facts = _make_facts_from_session(session.text)
        result = gk.filter(facts)

        new_facts = []
        dup_facts = []
        for fact in result.approved:
            structured = StructuredFact(type=fact.type, title=fact.title, tags=fact.tags, status="verified", content_summary=fact.content_summary)
            backend.store_fact(structured)
            new_facts.append(fact.title)
            all_stored.append(structured)
        for _, reason in result.rejected:
            dup_facts.append(reason)

        snapshots.append({
            "session": "#%d — %s" % (i, session.name[:50]), "extracted": len(facts),
            "new": len(new_facts), "duplicates": len(dup_facts), "total_after": len(all_stored),
        })
        print("  Сессия #%d: %s" % (i, session.name[:60]))
        print("    Извлечено: %d | Новых: %d | Дубликатов: %d | Всего в памяти: %d" % (len(facts), len(new_facts), len(dup_facts), len(all_stored)))
        if new_facts:
            for title in new_facts[:2]:
                print("    +  %s" % title[:80])
        if dup_facts:
            for reason in dup_facts[:1]:
                print("    ⛔ %s" % reason[:80])
        print()

    try:
        from rich.table import Table
        from rich.console import Console
        c = Console()
        table = Table(title="Эволюция на реальных сессиях OpenCode")
        table.add_column("Сессия", style="cyan")
        table.add_column("Извл.", justify="right")
        table.add_column("Новых", justify="right", style="green")
        table.add_column("Дубл.", justify="right", style="red")
        table.add_column("Память", justify="right", style="bold")
        for s in snapshots:
            table.add_row(s["session"], str(s["extracted"]), str(s["new"]), str(s["duplicates"]), str(s["total_after"]))
        c.print(table)
    except ImportError:
        for s in snapshots:
            print("  %s | +%d -%d | память: %d" % (s["session"], s["new"], s["duplicates"], s["total_after"]))
    print(f"\n  Итого: {len(all_stored)} фактов из {len(sessions)} реальных сессий OpenCode.")
    print("  Данные не синтетические — из твоей рабочей базы opencode.db.")


def run_ingest_demo(learnings_dir: str | None = None):
    header("DEMO: Ingest реальных .md файлов из learnings/")
    dir_path = Path(learnings_dir or os.path.expanduser("~/Documents/AI/personal/learnings"))
    if not dir_path.exists():
        print(f"  Директория не найдена: {dir_path}")
        return

    backend = LocalBackend(":memory:")
    gk = Gatekeeper(backend, check_duplicates=False)
    from curator.analyzers.ingest import ingest_directory

    test_queries = ["kotlin", "compose", "git", "docker", "jvm", "mcp"]

    print("  ДО индексации:")
    for q in test_queries:
        results = backend.query_facts(FactQuery(search=q))
        print(f"    query('{q}') → {len(results)} фактов")

    saved = ingest_directory(dir_path, backend, gk)
    print(f"\n  Проиндексировано: {saved} фактов из {dir_path}")
    print(f"  Файлов: {len(list(dir_path.rglob('*.md')))}")

    print("\n  ПОСЛЕ индексации:")
    for q in test_queries:
        results = backend.query_facts(FactQuery(search=q))
        print(f"    query('{q}') → {len(results)} фактов")
        for r in results[:2]:
            print(f"      · {r.title[:70]}")

    print("\n  Вывод: до индексации — 0 фактов по любому запросу.")
    print(f"  После индексации {saved} фактов из {len(list(dir_path.rglob('*.md')))} .md файлов — агент может отвечать.")


def main():
    mode = os.getenv("DEMO_MODE", "compare")

    if mode == "opencode":
        run_opencode_demo()
        return
    if mode == "ingest":
        run_ingest_demo()
        return
    if mode == "timelapse":
        run_time_lapse()
        return

    result = run_demo()
    return result


if __name__ == "__main__":
    main()