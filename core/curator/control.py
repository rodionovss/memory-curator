"""curator CLI — универсальный интерфейс к Memory Curator.

Использование:
    curator save               — сохранить кандидатов знаний (JSON из stdin, извлекает агент)
    curator get "kotlin"       — поиск фактов
    curator start              — запустить worker daemon в фоне
    curator stop               — остановить worker
    curator status              — worker жив? последний improve? фактов в базе?
    curator report             — сводка: сегодня / 3 дня / неделя
    curator improve            — ручной запуск improve цикла
    curator routes             — текущие правила маршрутизации
    curator knowledge-routes   — каталог маршрутов базы (Markdown/JSON/write/check)

Конфигурация:
    CURATOR_STATE_DIR: SQLite, логи и worker state (default: ~/.curator)
    IMPROVE_INTERVAL_MINUTES: интервал daemon (default: 1440 = сутки)
    CURATOR_DELIVERY_MODE: режим `curator context` — off (default) | shadow | inject
    CURATOR_SESSION_ID: id сессии OpenCode в shadow/inject событиях (форвардит плагин)
    CURATOR_SHADOW_LOG_PATH: лог событий доставки (default: <state>/delivery-shadow.jsonl)
"""

import os
import sys
import json
import time
from pathlib import Path
from datetime import datetime, timedelta

from curator.fs import atomic_write_text

def _report_dir() -> Path:
    from curator.state import env_path
    return env_path("IMPROVE_REPORT_DIR", "reports")


def _improve_log() -> Path:
    from curator.state import env_path
    return env_path("CURATOR_OBS_PATH", "improve_events.jsonl")


def _usage_json() -> Path:
    from curator.state import env_path
    return env_path("CURATOR_USAGE_PATH", "usage.json")


def _project_root() -> Path:
    current = Path.cwd().resolve()
    return next((path for path in (current, *current.parents) if (path / ".git").exists()), current)


def _project_mcp_env() -> dict:
    root = _project_root()
    candidates = [
        (root / ".opencode" / "opencode.json", "mcp"),
        (root / "opencode.json", "mcp"),
        (root / ".mcp.json", "mcpServers"),
    ]
    for path, section in candidates:
        try:
            config = json.loads(path.read_text(encoding="utf-8"))
            entry = config.get(section, {}).get("memory-curator", {})
            environment = entry.get("environment") or entry.get("env") or {}
            if environment:
                return environment
        except (OSError, json.JSONDecodeError, AttributeError):
            continue
    return {}


def _apply_project_mcp_env() -> None:
    for name, value in _project_mcp_env().items():
        os.environ.setdefault(str(name), str(value))


def _header(title: str):
    try:
        from rich.console import Console
        from rich.panel import Panel
        Console().print(Panel(title, style="bold cyan", expand=False))
    except ImportError:
        print(f"\n{'='*60}")
        print(f"  {title}")
        print(f"{'='*60}")


def _table(headers: list[str], rows: list[list], title: str = ""):
    try:
        from rich.table import Table
        from rich.console import Console
        c = Console()
        t = Table(title=title)
        for h in headers:
            t.add_column(h)
        for row in rows:
            t.add_row(*[str(c) for c in row])
        c.print(t)
    except ImportError:
        if title:
            print(f"\n  {title}")
        for row in rows:
            print(f"  {' | '.join(str(c) for c in row)}")


def _configured_base_dir() -> str | None:
    """База из установленного конфига (opencode.json / .mcp.json), env или None."""
    import json
    home = Path(os.environ.get("HOME") or Path.home())
    configured = os.getenv("CURATOR_BASE_DIR")
    if configured:
        return configured
    candidates = [
        (home / ".config" / "opencode" / "opencode.json", ("mcp", "memory-curator")),
        (Path.cwd() / ".mcp.json", ("mcpServers", "memory-curator")),
    ]
    for path, (section, key) in candidates:
        try:
            cfg = json.loads(path.read_text(encoding="utf-8"))
            entry = cfg.get(section, {}).get(key, {})
            env = entry.get("environment") or entry.get("env") or {}
            base = env.get("CURATOR_BASE_DIR")
            if base:
                return base
        except (OSError, json.JSONDecodeError, AttributeError):
            continue
    return None


def cmd_status():
    _header("Curator Status")

    from curator.daemon import read_pid, is_running, pid_is_curator_worker
    pid = read_pid()
    if pid and is_running(pid) and pid_is_curator_worker(pid):
        print(f"  Worker: ✅ запущен (pid {pid})")
    else:
        print("  Worker: ⛔ остановлен")

    base = _configured_base_dir()
    if base:
        print(f"  База знаний: {base}")
    from curator.state import state_dir
    print(f"  Состояние: {state_dir()}")

    backend = _make_backend()
    try:
        from curator.models import FactQuery
        facts = backend.query_facts(FactQuery())
        by_type = {}
        by_status = {}
        for f in facts:
            by_type[f.type] = by_type.get(f.type, 0) + 1
            by_status[f.status] = by_status.get(f.status, 0) + 1
        print(f"\n  Фактов: {len(facts)}")
        print(f"  По типам: {json.dumps(by_type, ensure_ascii=False)}")
        print(f"  По статусам: {json.dumps(by_status, ensure_ascii=False)}")
    except Exception as e:
        print(f"  Ошибка чтения фактов: {e}")

    last_report = _last_report_summary()
    if last_report:
        print(f"\n  Последний improve: {last_report}")

    if _improve_log().exists():
        events = _read_events()
        today = [e for e in events if _is_today(e.get("ts", ""))]
        applied = sum(1 for e in today if e.get("applied"))
        skipped = sum(1 for e in today if not e.get("applied"))
        print(f"  Событий сегодня: {len(today)} (применено: {applied}, отклонено: {skipped})")

    interval = os.getenv("IMPROVE_INTERVAL_MINUTES", "1440")
    print(f"\n  Интервал improve: {interval} мин ({_human_interval(int(interval))})")

    from curator.harness import integration_status
    print("\n  Интеграция OpenCode:")
    for ok, message in integration_status():
        print(f"    {'✅' if ok else '⛔'} {message}")


def cmd_report(days: int = 0):
    period = "за всё время" if days == 0 else f"за {days} дн."
    _header(f"Curator Report — {period}")

    cutoff = None
    if days > 0:
        cutoff = datetime.now() - timedelta(days=days)

    _section_usage(cutoff)
    _section_improve_log(cutoff)


def _section_usage(cutoff):
    usage_json = _usage_json()
    if not usage_json.exists():
        print("  Нет данных об использовании.")
        return

    try:
        data = json.loads(usage_json.read_text())
    except Exception:
        return

    sorted_items = sorted(data.items(), key=lambda x: x[1].get("count", 0), reverse=True)
    active = [(t, d["count"], d.get("last_access", 0)) for t, d in sorted_items[:10] if d.get("count", 0) > 0]
    if active:
        rows = []
        for i, (title, count, last) in enumerate(active[:10], 1):
            last_str = datetime.fromtimestamp(last).strftime("%d.%m %H:%M") if last else "—"
            rows.append([str(i), title[:60], str(count), last_str])
        _table(["#", "Факт", "Запросов", "Последний доступ"], rows, "Топ запросов")

    now = time.time()
    unused_30 = [t for t, d in sorted_items if d.get("last_access", 0) < now - 30 * 86400]
    unused_90 = [t for t, d in sorted_items if d.get("last_access", 0) < now - 90 * 86400]
    if unused_30 or unused_90:
        print(f"\n  Забытые: >30д: {len(unused_30)}, >90д: {len(unused_90)}")


def _section_improve_log(cutoff):
    events = _read_events()
    if not events:
        print("  Нет данных improve-лога.")
        return

    if cutoff:
        events = [e for e in events if e.get("ts", "") >= cutoff.isoformat()[:10]]

    applied = sum(1 for e in events if e.get("applied"))
    skipped = sum(1 for e in events if not e.get("applied"))
    by_action = {}
    for e in events:
        a = e.get("action", "unknown")
        by_action[a] = by_action.get(a, 0) + 1

    print(f"\n  Всего событий: {len(events)} (✅ {applied}, ⛔ {skipped})")
    for action, count in sorted(by_action.items()):
        print(f"    {action}: {count}")

    recent = events[-5:]
    if recent:
        rows = []
        for e in recent:
            ts = e.get("ts", "")[:16].replace("T", " ")
            applied_str = "✅" if e.get("applied") else "⛔"
            before = e.get("eval_before")
            after = e.get("eval_after")
            eval_str = f"{before:.0%}→{after:.0%}" if isinstance(before, (int, float)) and isinstance(after, (int, float)) else "—"
            facts = e.get("facts", [])
            detail = facts[0][:60] if facts else "—"
            rows.append([ts, e.get("action", "?"), applied_str, eval_str, detail])
        _table(["Время", "Действие", "", "Eval", "Детали"], rows, "Последние события")


def cmd_save(auto_yes: bool = False, hypothesis: bool = False,
             session_id: str | None = None, raw: str | None = None):
    if raw is None:
        raw = sys.stdin.read() if not sys.stdin.isatty() else ""
    if not raw.strip():
        print("Ошибка: нет данных. Используйте: curator save < candidates.json")
        print('  Формат: [{"type": "Reference", "title": "...", "content_summary": "...", "tags": ["..."], "evidence": "..."}]')
        return

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"Ошибка: stdin не является валидным JSON ({e})")
        return

    if isinstance(data, dict):
        data = data.get("candidates") or data.get("facts") or []
    if not isinstance(data, list) or not data:
        print('Ошибка: ожидается непустой массив кандидатов (или {"candidates": [...]})')
        return

    status = "hypothesis" if hypothesis else "verified"
    _header("Curator Save — кандидаты от агента" +
            (f" (майнинг сессии, статус: {status})" if session_id else ""))

    from curator.models import ProposedFact, StructuredFact, parse_tags, resolve_fact_type
    proposed = []
    for i, c in enumerate(data, 1):
        title = str(c.get("title", "")).strip() if isinstance(c, dict) else ""
        summary = str(c.get("content_summary", "")).strip() if isinstance(c, dict) else ""
        if not title or not summary:
            print(f"  ⚠ Кандидат #{i} некорректен (нет title/content_summary) — пропущен")
            continue
        fact_type, type_error = resolve_fact_type(
            str(c.get("type", "Reference")).strip(),
            new_type=str(c.get("new_type", "")).lower() in ("true", "1", "yes"),
            type_description=str(c.get("type_description", "") or ""),
        )
        if fact_type is None:
            print(f"  ⚠ Кандидат #{i}: {type_error}")
            continue
        proposed.append(ProposedFact(
            type=fact_type,
            title=title,
            content_summary=summary,
            tags=parse_tags(c.get("tags")),
            evidence=str(c.get("evidence", "") or ""),
            source_file=str(c.get("source_file", "") or "").strip() or None,
        ))

    if not proposed:
        print("  Валидных кандидатов нет.")
        return

    backend = _make_backend()
    from curator.gatekeeper import Gatekeeper
    gk = Gatekeeper(backend)
    result = gk.filter(proposed)

    print(f"\n  Получено: {len(proposed)}")
    print(f"  Одобрено: {len(result.approved)}")
    print(f"  Отклонено: {len(result.rejected)}")

    if result.rejected:
        print("\n  Отклонённые:")
        for fact, reason in result.rejected:
            print(f"    ⛔ {fact.title[:70]} — {reason}")

    if result.approved:
        print("\n  Одобренные:")
        for fact in result.approved:
            print(f"    ✅ {fact.title[:70]}")
            print(f"       {fact.type} | {', '.join(fact.tags[:5])}")

        if auto_yes:
            answer = "y"
        else:
            print(f"\n  Сохранить {len(result.approved)} фактов (статус: {status})? [y/N]: ", end="")
            answer = input().strip().lower()
        if answer == "y":
            from curator.routing import get_router, route_fact_safe
            from curator.sync_engine import SyncEngine
            from curator.retrieval_feedback import RetrievalFeedback
            router = get_router()
            base_dir = Path(os.getenv("CURATOR_BASE_DIR", os.path.expanduser("~/Documents/AI/personal/learnings")))
            sync = SyncEngine(backend, base_dir)
            fb = RetrievalFeedback()
            saved = 0
            for fact in result.approved:
                structured = StructuredFact(
                    type=fact.type, title=fact.title, tags=fact.tags,
                    status=status,
                    content_summary=fact.content_summary,
                    source_file=route_fact_safe(router, fact),
                )
                backend.store_fact(structured)
                try:
                    sync.write_fact_to_md(structured)
                except Exception as e:
                    # Факт в DB, но в .md его нет — молчать нельзя
                    print(f"    ⚠ write-back в .md не удался для '{fact.title[:50]}': {e}")
                fb.record_save(fact.title)
                saved += 1
            print(f"  ✅ Сохранено: {saved} фактов (статус: {status})")
            _log_candidates("mining" if session_id else "cli", result, saved, status,
                            session_id, declined_by_human=False)
        else:
            print("  Сохранение отменено.")
            _log_candidates("mining" if session_id else "cli", result, 0, status,
                            session_id, declined_by_human=True)
    else:
        # Все кандидаты отклонены gatekeeper'ом — это тоже данные precision
        _log_candidates("mining" if session_id else "cli", result, 0, status,
                        session_id, declined_by_human=False)


def _log_candidates(source: str, result, saved: int, status: str,
                    session_id: str | None, declined_by_human: bool):
    """Телеметрия: предложил/сохранил/отказал + причина. Не роняет save."""
    from curator import candidates_log
    candidates = [(f, "approved", "") for f in result.approved]
    candidates += [(f, "rejected", reason) for f, reason in result.rejected]
    candidates_log.log_capture(source, candidates, saved=saved, final_status=status,
                               session_id=session_id, declined_by_human=declined_by_human)


def cmd_get(query: str = ""):
    if not query:
        print("Использование: curator get 'kotlin'")
        return

    _header(f"Curator Get — поиск: '{query}'")
    backend = _make_backend()
    from curator.models import FactQuery
    facts = backend.query_facts(FactQuery(search=query))
    if not facts:
        print("  Ничего не найдено.")
        return

    print(f"  Найдено: {len(facts)}")
    rows = []
    for f in facts:
        rows.append([f.title[:60], f.type, f.status, ", ".join(f.tags[:4])])
    _table(["Факт", "Тип", "Статус", "Теги"], rows)


def _delivery_mode() -> str:
    """CURATOR_DELIVERY_MODE: off | shadow | inject. Опечатка → off (fail-safe)."""
    mode = (os.getenv("CURATOR_DELIVERY_MODE") or "").strip().lower()
    return mode if mode in ("off", "shadow", "inject") else "off"


def cmd_context(args: list[str] | None = None):
    """curator context '<текст задачи>' — ranked context cards (стабильный JSON).

    Транспорт плагина OpenCode (ADR 002). Режим CURATOR_DELIVERY_MODE:
    off (default) — пустой контракт без retrieval; shadow — retrieval и
    локальное shadow-событие, карточки не возвращаются; inject — событие
    и возврат карточек. Retrieval всегда с feedback=None: proactive
    доставка не считается ручным доступом пользователя.
    """
    import json as json_mod

    args = list(args if args is not None else sys.argv[2:] if len(sys.argv) > 2 else [])
    flags = ("-j", "--json")
    pretty = any(a in ("-t", "--text") for a in args)
    rest = [a for a in args if a not in flags + ("-t", "--text")]

    options = {"limit": 3, "token_budget": 500, "relevance_threshold": 0.4}
    for i, a in enumerate(rest):
        if a in ("--limit", "--budget", "--threshold") and i + 1 < len(rest):
            options[{"--limit": "limit", "--budget": "token_budget", "--threshold": "relevance_threshold"}[a]] = (
                int(rest[i + 1]) if a != "--threshold" else float(rest[i + 1])
            )
        elif a == "--types" and i + 1 < len(rest):
            options["types"] = [t.strip() for t in rest[i + 1].split(",") if t.strip()]

    trigger = " ".join(a for a in rest if not a.startswith("--"))
    mode = _delivery_mode()
    result = {"cards": [], "count": 0}
    if trigger and mode != "off":
        from curator import shadow_log
        from curator.delivery import fetch_context

        session_id = os.getenv("CURATOR_SESSION_ID") or None
        started = time.perf_counter()
        near_misses: list[tuple[str, float]] = []
        try:
            cards = fetch_context(trigger, _make_backend(), None, near_misses=near_misses, **options)
        except Exception as e:
            # Сбой retrieval — не наблюдение: событие не пишется, CLI жив
            print(f"curator: context delivery недоступен: {e}", file=sys.stderr, flush=True)
            cards = None
        if cards is not None:
            latency_ms = int((time.perf_counter() - started) * 1000)
            shadow_log.log_event(
                trigger, cards, mode=mode, session_id=session_id,
                delivered=(mode == "inject" and bool(cards)),
                latency_ms=latency_ms,
                near_miss_titles=[t for t, _ in near_misses],
                near_miss_scores=[s for _, s in near_misses],
            )
            if mode == "inject":
                result = {"cards": [card.__dict__ for card in cards], "count": len(cards)}

    if pretty:
        if result["cards"]:
            for c in result["cards"]:
                print(f"{c['score']:.2f} {c['title']} ({c['type']}, {', '.join(c['tags'])})")
                print(f"  {c['summary'][:300]}")
                print(f"  → {c['source_file'] or '(нет файла)'} | {c['reason']}\n")
        else:
            print("  Релевантных фактов нет (silent).")
    else:
        print(json_mod.dumps(result, ensure_ascii=False, indent=2))


def cmd_start():
    from curator.daemon import ensure_worker
    print(ensure_worker())


def cmd_stop():
    from curator.daemon import stop_worker
    print(stop_worker())


def cmd_demo():
    args = sys.argv[2:]
    keep = "--keep" in args
    from curator.tour import run_tour
    run_tour(keep=keep)


def cmd_install():
    """Установить Memory Curator без вопросов: автодетект opencode/Claude Code."""
    _header("Curator Install")
    from curator import installer

    args = sys.argv[2:]
    target = None
    if "--opencode" in args:
        target = "opencode"
    elif "--claude" in args:
        target = "claude"

    base_dir = None
    if "--base-dir" in args:
        idx = args.index("--base-dir")
        if idx + 1 < len(args):
            base_dir = args[idx + 1]

    skills_mode = None
    if "--skills-link" in args:
        skills_mode = "link"
    elif "--skills-copy" in args:
        skills_mode = "copy"

    steps = installer.install_all(target=target, base_dir=base_dir, skills_mode=skills_mode)
    print()
    for step in steps:
        print(f"  {step}")


def cmd_improve():
    _header("Curator Improve")
    backend = _make_backend()
    from curator.improve_loop import ImproveLoop
    loop = ImproveLoop(backend)
    report = loop.run()

    # Semantic project docs меняет нейронный write-back. Без project map
    # сохраняем legacy lifecycle-синхронизацию Curator-секций.
    from curator.routing.map_router import find_map_path
    if find_map_path() is None:
        base_dir = Path(os.getenv("CURATOR_BASE_DIR", os.path.expanduser("~/Documents/AI/personal/learnings")))
        from curator.sync_engine import SyncEngine
        sync = SyncEngine(backend, base_dir)
        for f in report.deprecated:
            try:
                sync.rewrite_status(f)
            except Exception as e:
                print(f"  ⚠ write-back в .md не удался для '{f.title[:50]}': {e}")

    print(f"  Фактов: {report.stats['total_facts']}")
    print(f"  Дубликатов: {report.stats['duplicates_found']}")
    print(f"  Устаревших: {report.stats['stale_found']}")
    print(f"  Противоречий: {report.stats['contradictions_found']}")
    if report.metrics_before and report.metrics_after:
        b, a = report.metrics_before, report.metrics_after
        print(f"\n  Метрики (до → после): coverage {b.query_coverage:.0%} → {a.query_coverage:.0%}, "
              f"факты {b.total_facts} → {a.total_facts}")
    if report.duplicates:
        print(f"\n  Дубликаты ({len(report.duplicates)}):")
        for f1, f2 in report.duplicates[:5]:
            print(f"    '{f1.title[:50]}' ↔ '{f2.title[:50]}'")
    if report.contradictions:
        print(f"\n  Противоречия ({len(report.contradictions)}):")
        for f1, f2 in report.contradictions[:5]:
            print(f"    ⚡ '{f1.title[:50]}' ↔ '{f2.title[:50]}'")
    if getattr(report, "resolutions", None):
        print(f"\n  Разрешено ({len(report.resolutions)}):")
        for r in report.resolutions[:5]:
            print(f"    ✅ {r.winner.title[:50]} ← {r.loser.title[:50]}")
            print(f"       {r.reason}")
    if report.events:
        print("\n  Eval-решения:")
        for e in report.events[-5:]:
            status = "✅" if e.get("applied") else "⛔"
            print(f"    {e['action']}: {status}")


def cmd_routes():
    _header("Curator Routes")
    from curator.routing import get_router
    router = get_router()
    routes = router.list_routes()
    rows = []
    for r in routes:
        path = r.get("path", "?")
        desc = r.get("description", "")
        rules = r.get("rules", "")
        if isinstance(rules, list):
            rules = ", ".join(str(rule) for rule in rules)
        rows.append([path, desc, str(rules)[:60]])
    _table(["Путь", "Описание", "Правила"], rows)


KNOWLEDGE_ROUTES_CATALOG_NAME = "knowledge-routes.md"


def _print_route_validation_errors(errors) -> None:
    """Все ошибки валидации маршрутов — человеку, в stderr (stdout машинных режимов чист)."""
    print("  Ошибки валидации (факты без source_file или с небезопасными путями):",
          file=sys.stderr)
    for error in errors:
        print(f"    ⛔ {error}", file=sys.stderr)


def _resolve_knowledge_routes_base_dir(base_dir: Path | None) -> Path | None:
    """Base dir для каталога маршрутов: --base-dir > CURATOR_BASE_DIR/конфиг.

    Без явного пути и конфига возвращает None — фолбэк на домашнюю базу
    не делаем: нельзя молча писать не туда, куда просил человек.
    """
    if base_dir is not None:
        return base_dir
    configured = _configured_base_dir()
    return Path(configured).expanduser() if configured else None


def cmd_knowledge_routes(args: list[str] | None = None) -> int:
    """curator knowledge-routes — каталог маршрутов базы знаний (уровень файла).

    Режимы (взаимоисключающие): default — Markdown в stdout; --json —
    машинные записи; --write — атомарная запись <base_dir>/knowledge-routes.md;
    --check — сверка файла с текущими фактами.

    Возвращает exit code: 0 — успех; 1 — устаревший каталог, ошибки валидации
    или неудачная запись; 2 — неверные аргументы или недоступный base dir.
    """
    args = list(args if args is not None else sys.argv[2:])
    mode_flags = ("--json", "--write", "--check")
    chosen = [a for a in args if a in mode_flags]
    if len(chosen) > 1:
        print("Ошибка: флаги --json/--write/--check взаимоисключающие", file=sys.stderr)
        return 2

    base_dir: Path | None = None
    known = set(mode_flags) | {"--base-dir"}
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--base-dir":
            if i + 1 >= len(args) or args[i + 1].startswith("-"):
                print("Ошибка: --base-dir требует путь", file=sys.stderr)
                return 2
            base_dir = Path(args[i + 1]).expanduser()
            i += 2
            continue
        if arg.startswith("-"):
            if arg not in known:
                print(f"Ошибка: неизвестный флаг: {arg}", file=sys.stderr)
                return 2
        else:
            print(f"Ошибка: неожидаемый аргумент: {arg}", file=sys.stderr)
            return 2
        i += 1

    base_dir = _resolve_knowledge_routes_base_dir(base_dir)
    if base_dir is None:
        print("Ошибка: base dir не задан (--base-dir, CURATOR_BASE_DIR или конфиг opencode/.mcp)",
              file=sys.stderr)
        return 2
    if not base_dir.exists():
        print(f"Ошибка: base dir не существует: {base_dir}", file=sys.stderr)
        return 2

    from curator.knowledge_routes import (
        build_routes,
        render_routes_json,
        render_routes_markdown,
    )
    from curator.models import FactQuery

    facts = _make_backend().query_facts(FactQuery())
    result = build_routes(facts, base_dir)
    routes = list(result.routes)

    exit_code = 0
    if not chosen:
        print(render_routes_markdown(routes), end="")
    elif chosen == ["--json"]:
        print(json.dumps(render_routes_json(routes), ensure_ascii=False, indent=2))
    elif chosen == ["--write"]:
        target = base_dir / KNOWLEDGE_ROUTES_CATALOG_NAME
        try:
            atomic_write_text(target, render_routes_markdown(routes))
        except OSError as e:
            print(f"Ошибка записи {target}: {e}", file=sys.stderr)
            return 1
        print(f"  ✅ Каталог маршрутов записан: {target}")
        # Placement M2: указатель на каталог — в rules-файлы найденных
        # харнесов (install-механизм, без дублирования логики)
        from curator import installer
        for step in installer.publish_routes_pointers(str(base_dir)):
            print(f"  {step}")
    elif chosen == ["--check"]:
        target = base_dir / KNOWLEDGE_ROUTES_CATALOG_NAME
        if not target.exists():
            print(f"Ошибка: каталог маршрутов не найден: {target} — сначала "
                  "curator knowledge-routes --write", file=sys.stderr)
            return 1
        if target.read_text(encoding="utf-8") != render_routes_markdown(routes):
            print(f"  ⛔ Каталог маршрутов устарел: {target} не совпадает с текущими фактами",
                  file=sys.stderr)
            exit_code = 1
        elif not result.validation_errors:
            # ✅ только при полностью чистом прогоне: ошибки валидации
            # говорят сами за себя (stderr + exit 1) — без конкурирующего «актуален»
            print(f"  ✅ Каталог маршрутов актуален: {target}")

    if result.validation_errors:
        _print_route_validation_errors(result.validation_errors)
        exit_code = 1
    return exit_code


def cmd_sessions():
    """Реестр и транскрипты сессий OpenCode — источник для майнинга знаний."""
    args = sys.argv[2:] if len(sys.argv) > 2 else []
    sub = args[0] if args else "list"

    from curator.session_reader import list_opencode_sessions, read_opencode_session

    if sub == "list":
        since = None
        limit = 100
        if "--since" in args:
            idx = args.index("--since")
            if idx + 1 < len(args):
                since = args[idx + 1]
        if "--limit" in args:
            idx = args.index("--limit")
            if idx + 1 < len(args):
                limit = int(args[idx + 1])
        sessions = list_opencode_sessions(since=since, limit=limit)
        if not sessions:
            print("  Сессий не найдено (opencode.db пуст или нет по пути по умолчанию).")
            return
        _header(f"Curator Sessions — {len(sessions)} сессий (свежие сверху)")
        rows = []
        for s in sessions:
            title = (s.title or s.id)[:60]
            rows.append([s.created or "—", str(s.messages), f"{s.tokens // 1000}k", title])
        _table(["Дата", "Сообщ.", "Токены", "Заголовок"], rows)
        print("\n  Полный транскрипт: curator sessions show <id> [--out файл]")
        print("  id — полный идентификатор сессии из opencode.db")

    elif sub == "show":
        if len(args) < 2:
            print("Использование: curator sessions show <session_id> [--out файл]")
            return
        session_id = args[1]
        out_file = None
        if "--out" in args:
            idx = args.index("--out")
            if idx + 1 < len(args):
                out_file = args[idx + 1]
        session = read_opencode_session(session_id)
        if session is None:
            print(f"  Сессия не найдена или пуста: {session_id}")
            return
        header = (f"# Сессия: {session.name}\n"
                  f"# Сообщений (parts): {session.messages}, токенов: {session.tokens}\n\n")
        if out_file:
            Path(out_file).write_text(header + session.text, encoding="utf-8")
            print(f"  ✅ Транскрипт записан: {out_file} ({len(session.text)} символов)")
        else:
            print(header + session.text)
    else:
        print(f"Неизвестная подкоманда sessions: {sub} (доступны list, show)")


def cmd_candidates():
    """Precision-отчёт: что предлагал агент, что сохранилось, почему отказано."""
    _header("Curator Candidates — точность извлечения")
    from curator import candidates_log
    stats = candidates_log.precision_stats()
    if not stats["calls"]:
        print("  Нет данных: лог кандидатов пуст (~/.curator/candidates.jsonl).")
        print("  Заполняется при каждом curator save / curator_session_capture.")
        return

    print(f"  Вызовов capture: {stats['calls']} "
          f"(источники: {json.dumps(stats['by_source'], ensure_ascii=False)})")
    print(f"  Предложено кандидатов: {stats['proposed']}")
    print(f"  Сохранено: {stats['saved']} (precision {stats['precision_pct']}%)")
    print(f"  Отклонено gatekeeper: {stats['rejected_by_gatekeeper']}")
    print(f"  Отказов человека (весь batch): {stats['declined_by_human']}")

    if stats["by_reason"]:
        print("\n  Отказы по причинам:")
        for reason, count in sorted(stats["by_reason"].items(), key=lambda x: -x[1]):
            print(f"    {reason}: {count}")

    if stats["by_type_approved"]:
        print("\n  Одобренные по типам:")
        for ftype, count in sorted(stats["by_type_approved"].items(), key=lambda x: -x[1]):
            print(f"    {ftype}: {count}")

    if stats["top_rejected"]:
        print("\n  Чаще всего отклоняют:")
        for title, count in stats["top_rejected"][:5]:
            print(f"    {count}x {title[:70]}")


def _make_backend():
    from curator.backend.local import LocalBackend
    return LocalBackend()


def _read_events():
    improve_log = _improve_log()
    if not improve_log.exists():
        return []
    events = []
    with open(improve_log) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return events


def _is_today(ts: str) -> bool:
    return ts[:10] == datetime.now().isoformat()[:10]


def _last_report_summary():
    """Последний improve-отчёт: время + суть (что нашёл worker), не только дата."""
    report_dir = _report_dir()
    if not report_dir.exists():
        return None
    reports = sorted(report_dir.glob("improve_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not reports:
        return None
    when = datetime.fromtimestamp(reports[0].stat().st_mtime).strftime("%d.%m.%Y %H:%M")
    try:
        stats = json.loads(reports[0].read_text(encoding="utf-8")).get("stats", {})
    except (OSError, json.JSONDecodeError):
        stats = {}
    parts = []
    for key, label in (("duplicates_found", "дубликатов"), ("stale_found", "устаревших"), ("contradictions_found", "противоречий")):
        if key in stats:
            parts.append(f"{label}: {stats[key]}")
    if not parts:
        return when
    summary = f"{when} — " + ", ".join(parts)
    if all(stats.get(k, 1) == 0 for k in ("duplicates_found", "stale_found", "contradictions_found")):
        summary += " (база чистая)"
    return summary


def _human_interval(minutes: int) -> str:
    if minutes < 60:
        return f"{minutes} мин"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} ч"
    days = hours // 24
    return f"{days} д"


def main():
    _apply_project_mcp_env()
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")

    if len(sys.argv) < 2:
        print("curator — Memory Curator CLI")
        print("Использование:")
        print("  curator save              — сохранить кандидатов (JSON из stdin, извлекает агент)")
        print("  curator get <query>       — поиск фактов")
        print("  curator context '<задача>' — ranked context cards (JSON, ADR 002)")
        print("  curator start             — запустить worker daemon")
        print("  curator stop              — остановить worker")
        print("  curator status            — worker + факты + последний improve")
        print("  curator report [-d N]    — сводка (за N дней или всё время)")
        print("  curator improve           — ручной improve цикл")
        print("  curator routes            — правила маршрутизации")
        print("  curator knowledge-routes [--json|--write|--check] [--base-dir ПУТЬ] — каталог маршрутов базы")
        print("  curator sessions [list|show] — реестр/транскрипты сессий OpenCode (майнинг)")
        print("  curator candidates        — precision-отчёт: предложено/сохранено/отказано")
        print("  curator install [--opencode|--claude] [--base-dir ПУТЬ] [--skills-link|--skills-copy] — установка без вопросов")
        print("  curator demo [--keep] — тур: полный цикл жизни знания")
        print()
        print("Конфигурация: IMPROVE_INTERVAL_MINUTES")
        return

    cmd = sys.argv[1].lower()
    if cmd == "status":
        cmd_status()
    elif cmd == "report":
        days = 0
        if len(sys.argv) >= 4 and sys.argv[2] == "-d":
            days = int(sys.argv[3])
        cmd_report(days=days)
    elif cmd == "save":
        auto_yes = any(a in ("-y", "--yes") for a in sys.argv[2:])
        hypothesis = "--hypothesis" in sys.argv[2:]
        session_id = None
        if "--session" in sys.argv[2:]:
            idx = sys.argv[2:].index("--session")
            if idx + 2 < len(sys.argv):
                session_id = sys.argv[2:][idx + 2]
        cmd_save(auto_yes=auto_yes, hypothesis=hypothesis, session_id=session_id)
    elif cmd == "get":
        query = " ".join(sys.argv[2:]) if len(sys.argv) > 2 else ""
        cmd_get(query)
    elif cmd == "context":
        cmd_context()
    elif cmd == "start":
        cmd_start()
    elif cmd == "stop":
        cmd_stop()
    elif cmd == "improve":
        cmd_improve()
    elif cmd == "routes":
        cmd_routes()
    elif cmd == "knowledge-routes":
        sys.exit(cmd_knowledge_routes(sys.argv[2:]))
    elif cmd == "install":
        cmd_install()
    elif cmd == "demo":
        cmd_demo()
    elif cmd == "sessions":
        cmd_sessions()
    elif cmd == "candidates":
        cmd_candidates()
    else:
        print(f"Неизвестная команда: {cmd}")
        print("Доступные: save, get, start, stop, status, report, improve, routes, knowledge-routes, sync, demo, sessions, candidates")


if __name__ == "__main__":
    main()
