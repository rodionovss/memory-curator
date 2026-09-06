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

Конфигурация:
    MEMORY_BACKEND: "local" | "xmemory"
    CURATOR_STATE_DIR: SQLite, outbox, логи и worker state (default: ~/.curator)
    IMPROVE_INTERVAL_MINUTES: интервал daemon (default: 1440 = сутки)
    XMEMORY_API_KEY / XMEMORY_INSTANCE_ID
"""

import os
import sys
import json
import time
from pathlib import Path
from datetime import datetime, timedelta

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


def cmd_save(auto_yes: bool = False):
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

    _header("Curator Save — кандидаты от агента")

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
            print(f"\n  Сохранить {len(result.approved)} фактов? [y/N]: ", end="")
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
                    status="verified", content_summary=fact.content_summary,
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
            print(f"  ✅ Сохранено: {saved} фактов")
        else:
            print("  Сохранение отменено.")


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


def cmd_start():
    from curator.daemon import ensure_worker
    print(ensure_worker())


def cmd_stop():
    from curator.daemon import stop_worker
    print(stop_worker())


def cmd_demo():
    args = sys.argv[2:]
    keep = "--keep" in args
    backend = "local"
    if "--backend" in args:
        idx = args.index("--backend")
        if idx + 1 < len(args):
            backend = args[idx + 1]
    from curator.tour import run_tour
    run_tour(backend=backend, keep=keep)


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

    steps = installer.install_all(target=target, base_dir=base_dir)
    print()
    for step in steps:
        print(f"  {step}")


def cmd_sync():
    _header("Curator Sync — пуш outbox в xmemory")

    key = os.getenv("XMEMORY_API_KEY", "")
    inst = os.getenv("XMEMORY_INSTANCE_ID", "")
    if not key or not inst:
        print("  ⚠ Нет XMEMORY_API_KEY / XMEMORY_INSTANCE_ID — синк невозможен.")
        return

    from curator.outbox import Outbox
    from curator.backend.xmemory import XMemoryBackend
    ob = Outbox()
    pending = ob.pending()
    if not pending:
        print("  Outbox пуст — нечего синхронизировать.")
        return

    print(f"  В очереди: {len(pending)} фактов")
    xmem = XMemoryBackend(api_key=key, instance_id=inst)
    pushed = 0
    failed = 0
    for row_id, fact in pending:
        try:
            xmem.push_direct(fact)
            ob.mark_synced(row_id)
            pushed += 1
        except Exception as e:
            ob.fail(row_id)
            failed += 1
            print(f"    ⛔ {fact.title[:60]} — {str(e)[:80]}")
    print(f"  ✅ Отправлено: {pushed}, ⛔ Не удалось: {failed}")


def cmd_improve():
    _header("Curator Improve")
    backend = _make_backend()
    from curator.improve_loop import ImproveLoop
    loop = ImproveLoop(backend)
    report = loop.run()

    # Semantic project docs меняет нейронный write-back. Без project map
    # сохраняем legacy lifecycle-синхронизацию Curator-секций.
    if not os.getenv("CURATOR_MAP", "").strip():
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


def _make_backend():
    backend_type = os.getenv("MEMORY_BACKEND", "local")
    if backend_type == "xmemory":
        from curator.backend.xmemory import XMemoryBackend
        return XMemoryBackend(
            api_key=os.getenv("XMEMORY_API_KEY", ""),
            instance_id=os.getenv("XMEMORY_INSTANCE_ID", ""),
        )
    else:
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
        print("  curator start             — запустить worker daemon")
        print("  curator stop              — остановить worker")
        print("  curator status            — worker + факты + последний improve")
        print("  curator report [-d N]    — сводка (за N дней или всё время)")
        print("  curator improve           — ручной improve цикл")
        print("  curator routes            — правила маршрутизации")
        print("  curator sync              — пуш offline-outbox в xmemory")
        print("  curator install [--opencode|--claude] [--base-dir ПУТЬ] — установка без вопросов (автодетект; флаги — для скриптов)")
        print("  curator demo [--keep] [--backend xmemory] — тур: полный цикл жизни знания")
        print()
        print("Конфигурация: MEMORY_BACKEND, IMPROVE_INTERVAL_MINUTES, XMEMORY_API_KEY")
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
        cmd_save(auto_yes=auto_yes)
    elif cmd == "get":
        query = " ".join(sys.argv[2:]) if len(sys.argv) > 2 else ""
        cmd_get(query)
    elif cmd == "start":
        cmd_start()
    elif cmd == "stop":
        cmd_stop()
    elif cmd == "improve":
        cmd_improve()
    elif cmd == "routes":
        cmd_routes()
    elif cmd == "sync":
        cmd_sync()
    elif cmd == "install":
        cmd_install()
    elif cmd == "demo":
        cmd_demo()
    else:
        print(f"Неизвестная команда: {cmd}")
        print("Доступные: save, get, start, stop, status, report, improve, routes, sync, demo")


if __name__ == "__main__":
    main()
