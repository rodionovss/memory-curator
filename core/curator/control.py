"""curator CLI — универсальный интерфейс к Memory Curator.

Использование:
    curator save               — сохранить кандидатов знаний (JSON из stdin, извлекает агент)
    curator get "kotlin"       — поиск фактов
    curator status             — база, факты, capture-сводка
    curator install            — установка в opencode / Claude Code
    curator knowledge-routes   — каталог маршрутов базы (Markdown/JSON/write/check)

Конфигурация:
    CURATOR_STATE_DIR: SQLite, логи и state (default: ~/.curator)

"""

import os
import sys
import json
from pathlib import Path
from datetime import datetime

from curator.fs import atomic_write_text

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
    """База из env или state-конфига (~/.curator/config.json), иначе None.

    MCP-секции больше не источник истины (решение 2026-10-03):
    env CURATOR_BASE_DIR > state-конфиг, записанный `curator install`.
    """
    configured = os.getenv("CURATOR_BASE_DIR")
    if configured:
        return configured
    from curator.state import configured_base
    return configured_base()


def _resolve_base_dir() -> Path:
    """База для write-путей (save / save --doc): полная цепочка.

    env CURATOR_BASE_DIR > state-конфиг > нейтральный дефолт. Единая
    точка: смена цепочки меняется здесь, а не в каждом вызове.
    """
    from curator.state import default_base_dir
    return Path(_configured_base_dir() or default_base_dir())


def cmd_status():
    _header("Curator Status")

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

    try:
        from curator import candidates_log
        stats = candidates_log.precision_stats()
        if stats["calls"]:
            print(f"\n  Capture за всё время: {stats['calls']} вызовов, "
                  f"{stats['proposed']} предложено / {stats['saved']} сохранено / "
                  f"{stats['rejected_by_gatekeeper']} отклонено gatekeeper")
    except Exception:
        pass

    from curator.harness import integration_status
    print("\n  Интеграция OpenCode:")
    for ok, message in integration_status():
        print(f"    {'✅' if ok else '⛔'} {message}")


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
        from curator.routing import get_router, route_fact_safe
        router = get_router()
        # Маршрут резолвим до показа: «что» и «куда» в одном preview
        routes = {id(f): route_fact_safe(router, f) for f in result.approved}
        print("\n  Одобренные:")
        for fact in result.approved:
            print(f"    ✅ {fact.title[:70]}")
            line = f"       {fact.type} | {', '.join(fact.tags[:5])}"
            if routes[id(fact)]:
                line += f" | → {routes[id(fact)]}"
            print(line)

        if auto_yes:
            answer = "y"
        else:
            print(f"\n  Сохранить {len(result.approved)} фактов (статус: {status})? [y/N]: ", end="")
            answer = input().strip().lower()
        if answer == "y":
            from curator.sync_engine import SyncEngine
            base_dir = _resolve_base_dir()
            sync = SyncEngine(backend, base_dir)
            saved = 0
            for fact in result.approved:
                structured = StructuredFact(
                    type=fact.type, title=fact.title, tags=fact.tags,
                    status=status,
                    content_summary=fact.content_summary,
                    source_file=routes[id(fact)],
                )
                backend.store_fact(structured)
                try:
                    sync.write_fact_to_md(structured)
                except Exception as e:
                    # Факт в DB, но в .md его нет — молчать нельзя
                    print(f"    ⚠ write-back в .md не удался для '{fact.title[:50]}': {e}")
                saved += 1
            print(f"  ✅ Сохранено: {saved} фактов (статус: {status})")
            # Петля чтения не протухает: каталог регенерируется тем же
            # ходом, что и факты (детерминированный рендер). Сбой каталога
            # не валит save — факты важнее, предупреждение видно.
            try:
                from curator.knowledge_routes import render_catalog
                catalog_path = base_dir / "knowledge-routes.md"
                atomic_write_text(catalog_path, render_catalog(backend, base_dir))
                print(f"  ✅ Каталог маршрутов обновлён: {catalog_path}")
            except Exception as e:
                print(f"    ⚠ каталог маршрутов не перегенерирован: {e}")
            if saved:
                first_title = result.approved[0].title
                if saved == 1:
                    message = f"curator: {first_title}"
                else:
                    message = f"curator: {saved} фактов ({first_title[:50]})"
                outcome = _git_commit(base_dir, message)
                if outcome == "committed":
                    print(f"  git: локальный коммит — {message}")
                elif outcome == "failed":
                    print("  ⚠ git-коммит не прошёл (git недоступен или identity не настроен)"
                          " — данные сохранены, история базы не ведётся")
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


def _ensure_git_repo(base_dir: Path) -> bool:
    import subprocess
    try:
        probe = subprocess.run(
            ["git", "-C", str(base_dir), "rev-parse", "--git-common-dir"],
            capture_output=True, text=True, timeout=15,
        )
        if probe.returncode == 0:
            return True
        init = subprocess.run(
            ["git", "-C", str(base_dir), "init", "--quiet"],
            capture_output=True, text=True, timeout=15,
        )
        return init.returncode == 0
    except Exception:
        return False


def _git_commit(base_dir: Path, message: str) -> str:
    import subprocess
    try:
        if not _ensure_git_repo(base_dir):
            return "failed"
        status = subprocess.run(
            ["git", "-C", str(base_dir), "status", "--porcelain"],
            capture_output=True, text=True, timeout=15,
        )
        if status.returncode != 0:
            return "failed"
        if not status.stdout.strip():
            return "noop"
        subprocess.run(
            ["git", "-C", str(base_dir), "add", "-A", "."],
            capture_output=True, text=True, timeout=15,
        )
        commit = subprocess.run(
            ["git", "-C", str(base_dir), "commit", "-m", message, "--no-verify"],
            capture_output=True, text=True, timeout=30,
        )
        return "committed" if commit.returncode == 0 else "failed"
    except Exception:
        return "failed"


def cmd_save_doc(path: str):
    """Зафиксировать файл-знание: проверка полки по карте + git-коммит + аналитика.

    Контент пишет модель (файл уже существует на диске) — куратор здесь
    библиотекарь: сверяет путь с картой тем, коммитит и протоколирует событие.
    В SQLite ничего не пишется: файл-знание сам себе единица.
    """
    _header("Curator Save — фиксация документа")
    base_dir = _resolve_base_dir()

    raw = Path(path).expanduser()
    resolved = raw.resolve() if raw.is_absolute() else (base_dir / raw).resolve()
    root = base_dir.resolve()
    if not resolved.is_relative_to(root):
        print(f"  ⛔ Путь вне базы ({base_dir}) — фиксация отменена")
        _log_doc(path, saved=0, reason="путь вне базы")
        return
    if not resolved.is_file():
        print(f"  ⛔ Файл не найден: {path}")
        print("     Сначала запиши/дополни файл, потом вызывай curator save --doc <path>")
        _log_doc(path, saved=0, reason="файл не найден")
        return
    relative = resolved.relative_to(root).as_posix()

    from curator.routing.map_router import MapRouter, find_map_path
    map_path = find_map_path()
    known = relative.startswith("session/")  # дефолт-приёмник валиден всегда
    if not known and map_path is not None and map_path.exists():
        router = MapRouter(map_path)
        if any(MapRouter.matches_target(relative, t.path) for t in router._all_targets):
            known = True
    if not known:
        print(f"  ⛔ Путь '{relative}' не совпадает ни с одним таргетом карты.")
        if map_path is not None and map_path.exists():
            concrete = sorted({t.path for t in MapRouter(map_path)._all_targets if not t.is_glob})
            for c in concrete[:8]:
                print(f"     - {c}")
            if len(concrete) > 8:
                print(f"     ... и ещё {len(concrete) - 8}")
        print("     Новая тема? Сначала добавь её в knowledge-map.md (тема + таргет).")
        _log_doc(relative, saved=0, reason="путь вне карты")
        return

    outcome = _git_commit(base_dir, f"curator: doc {relative}")
    if outcome == "committed":
        print(f"  ✅ Документ зафиксирован: {relative}")
        print(f"  git: локальный коммит — curator: doc {relative}")
    elif outcome == "noop":
        print(f"  ✅ Документ зафиксирован: {relative} (изменений в git нет)")
    else:
        print(f"  ✅ Документ зафиксирован: {relative}")
        print("  ⚠ git-коммит не прошёл (git недоступен или identity не настроен)"
              " — история базы не ведётся")
    _log_doc(relative, saved=1, reason="")


def _log_doc(path: str, saved: int, reason: str):
    """Событие save --doc в журнале аналитики. Не роняет фиксацию."""
    from types import SimpleNamespace
    from curator import candidates_log
    doc = SimpleNamespace(title=path, type="Doc")
    candidates_log.log_capture(
        "doc", [(doc, "approved" if saved else "rejected", reason)],
        saved=saved, final_status="verified",
    )


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
        else:
            print("Ошибка: --base-dir требует путь", file=sys.stderr)
            return

    skills_mode = None
    if "--skills-link" in args:
        skills_mode = "link"
    elif "--skills-copy" in args:
        skills_mode = "copy"

    try:
        steps = installer.install_all(
            target=target, base_dir=base_dir, skills_mode=skills_mode)
    except installer.RepoAssetsMissingError as e:
        print(f"\n⛔ {e}", file=sys.stderr)
        sys.exit(1)
    print()
    for step in steps:
        print(f"  {step}")


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
        print("Ошибка: base dir не задан (--base-dir, env CURATOR_BASE_DIR или ~/.curator/config.json)",
              file=sys.stderr)
        return 2
    if not base_dir.exists():
        print(f"Ошибка: base dir не существует: {base_dir}", file=sys.stderr)
        return 2

    from curator.knowledge_routes import (
        build_catalog,
        render_routes_json,
        render_routes_markdown,
    )

    # Карта тем — источник истины: есть карта → каталог её проекция
    # (маршруты из таргетов карты, contains — заголовки фактов DB).
    # Нет карты — каталог из самих фактов. Общая сборка с save-путём.
    # Битая карта — ошибка, не молчаливая деградация (см. build_catalog).
    try:
        result = build_catalog(_make_backend(), base_dir)
    except ValueError as e:
        print(f"Ошибка: {e} — почини карту или удали, каталог не перезаписан",
              file=sys.stderr)
        return 2
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
        for step in installer.publish_rules_sections(str(base_dir)):
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


def _make_backend():
    from curator.backend.local import LocalBackend
    return LocalBackend()


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")

    if len(sys.argv) < 2:
        print("curator — Memory Curator CLI")
        print("Использование:")
        print("  curator save              — сохранить кандидатов (JSON из stdin, извлекает агент)")
        print("  curator status            — база + факты + capture-сводка")
        print("  curator install           — установка в opencode / Claude Code")
        print("  curator get '<запрос>'    — поиск фактов по ключевым словам")
        print()
        print("Служебные: knowledge-routes (каталог маршрутов базы)")
        return

    cmd = sys.argv[1].lower()
    if cmd == "status":
        cmd_status()
    elif cmd == "install":
        cmd_install()
    elif cmd == "get":
        cmd_get(" ".join(sys.argv[2:]) if len(sys.argv) > 2 else "")
    elif cmd == "save":
        args = sys.argv[2:]
        if "--doc" in args:
            idx = args.index("--doc")
            if idx + 1 >= len(args) or args[idx + 1].startswith("-"):
                print("Использование: curator save --doc <путь до файла в базе>")
                return
            cmd_save_doc(args[idx + 1])
            return
        auto_yes = any(a in ("-y", "--yes", "--auto-yes") for a in args)
        hypothesis = "--hypothesis" in args
        session_id = None
        if "--session" in args:
            idx = args.index("--session")
            if idx + 1 < len(args):
                session_id = args[idx + 1]
        cmd_save(auto_yes=auto_yes, hypothesis=hypothesis, session_id=session_id)
    elif cmd == "knowledge-routes":
        sys.exit(cmd_knowledge_routes(sys.argv[2:]))
    else:
        print(f"Неизвестная команда: {cmd}")
        print("Доступные: save, status, get, install (+ служебная knowledge-routes)")


if __name__ == "__main__":
    main()
