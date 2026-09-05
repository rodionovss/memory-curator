"""MCP-сервер Memory Curator. Экспонирует тулзы для OpenCode и других MCP-клиентов.

Запуск: curator-mcp-server

Извлечение знаний делает сам агент (LLM) — opencode сейчас, любой MCP-клиент
(Claude Code) по тому же контракту. Скилл передаёт готовых кандидатов через
`candidates`. Бэкенд управляет данными: валидация (gatekeeper),
хранение, write-back в .md, improve loop.

Конфигурация через переменные окружения:
    MEMORY_BACKEND: "xmemory" | "local" (default: "local")
    CURATOR_BASE_DIR: директория с .md файлами
    AUTO_MODE: "true" | "false" (default: "false")
"""

import os
import json
import asyncio
from pathlib import Path

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    Tool, TextContent,
    ListToolsRequest, CallToolResult,
)

from curator.models import (
    StructuredFact, ProposedFact, FactQuery, parse_tags,
    get_fact_types, resolve_fact_type,
)
from curator.backend.interface import MemoryBackend
from curator.backend.local import LocalBackend
from pydantic import BaseModel, ConfigDict
from curator.gatekeeper import Gatekeeper
from curator.improve_loop import ImproveLoop
from curator.retrieval_feedback import RetrievalFeedback


def _get_backend() -> MemoryBackend:
    backend_type = os.getenv("MEMORY_BACKEND", "local")
    if backend_type == "xmemory":
        from curator.backend.xmemory import XMemoryBackend
        return XMemoryBackend(
            api_key=os.getenv("XMEMORY_API_KEY", ""),
            instance_id=os.getenv("XMEMORY_INSTANCE_ID", ""),
        )
    else:
        db_path = os.path.expanduser("~/.curator/knowledge.db")
        return LocalBackend(db_path)


_FACT_TYPES_DOC = "тип факта — известные типы с описаниями: см. curator_status; новый тип только после подтверждения человеком (new_type=true + type_description)"


def _as_bool(value) -> bool:
    """LLM-клиенты присылают bool строкой: 'false' обязана быть ложной."""
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("true", "1", "yes")


from curator.routing import get_router

app = Server("memory-curator")
backend = _get_backend()
gatekeeper = Gatekeeper(backend)
router = get_router()
base_dir = Path(os.getenv("CURATOR_BASE_DIR", os.path.expanduser("~/Documents/AI/personal/learnings")))
improve = ImproveLoop(backend)
feedback = RetrievalFeedback()


async def handle_list_tools(ctx, request):
    tools = [
        Tool(
            name="curator_session_capture",
            description="Сохранить готовые кандидаты знаний (извлекает сам агент): валидация gatekeeper → preview → сохранение",
            inputSchema={
                "type": "object",
                "properties": {
                    "candidates": {
                        "type": "array",
                        "description": ("Кандидаты: [{type, title, content_summary, tags: [], evidence, "
                                         "source_file (опционально: путь .md внутри базы, предложенный агентом/скиллом), "
                                         "new_type (опционально: true если пользователь подтвердил новый тип), "
                                         "type_description (описание нового типа, обязательно при new_type)}]"),
                        "items": {
                            "type": "object",
                            "properties": {
                                "type": {"type": "string", "description": _FACT_TYPES_DOC},
                                "title": {"type": "string"},
                                "content_summary": {"type": "string"},
                                "tags": {"type": "array", "items": {"type": "string"}},
                                "evidence": {"type": "string"},
                                "source_file": {"type": "string", "description": "path внутри CURATOR_BASE_DIR (не absolute, без ..)"},
                                "new_type": {"type": "boolean", "description": "пользователь подтвердил заведение нового типа"},
                                "type_description": {"type": "string", "description": "что значит новый тип — контракт для агента"},
                            },
                            "required": ["type", "title", "content_summary", "tags"],
                        },
                    },
                    "auto_approve": {
                        "type": "boolean",
                        "description": "Автоматически сохранять одобренных кандидатов без подтверждения (агент вызывает после показа preview)",
                        "default": False,
                    },
                },
                "required": ["candidates"],
            },
        ),
        Tool(
            name="curator_query",
            description="Запросить факты из базы знаний",
            inputSchema={
                "type": "object",
                "properties": {
                    "type": {"type": "string", "description": "Тип факта: Reference, Style, Tool, Spec"},
                    "tags": {"type": "string", "description": "Теги через запятую"},
                    "status": {"type": "string", "description": "Статус: verified, hypothesis, deprecated"},
                    "search": {"type": "string", "description": "Текстовый поиск"},
                },
            },
        ),
        Tool(
            name="curator_status",
            description="Статистика базы знаний: количество фактов по типам и статусам",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="curator_improve",
            description="Запустить цикл улучшения: поиск дубликатов и устаревших знаний",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="curator_feedback",
            description="Статистика использования: какие факты чаще запрашиваются, какие забыты",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="curator_routes",
            description="Показать текущие правила маршрутизации фактов по папкам",
            inputSchema={"type": "object", "properties": {}},
        ),
    ]
    from mcp.types import ListToolsResult
    return ListToolsResult(tools=tools)


app.add_request_handler("tools/list", ListToolsRequest, handle_list_tools)


async def handle_call_tool(ctx, request):
    if isinstance(request, dict):
        params = request.get("params", {})
        name = params.get("name", "") if isinstance(params, dict) else getattr(params, "name", "")
        arguments = params.get("arguments", {}) if isinstance(params, dict) else getattr(params, "arguments", {}) or {}
    else:
        name = getattr(request, "name", "")
        arguments = getattr(request, "arguments", {}) or {}

    if name == "curator_session_capture":
        text = await asyncio.to_thread(_session_capture, arguments)
    elif name == "curator_routes":
        text = await asyncio.to_thread(_routes)
    elif name == "curator_query":
        text = await asyncio.to_thread(_query, arguments)
    elif name == "curator_status":
        text = await asyncio.to_thread(_status)
    elif name == "curator_improve":
        text = await asyncio.to_thread(_improve)
    elif name == "curator_feedback":
        text = await asyncio.to_thread(_feedback)
    else:
        text = f"Unknown tool: {name}"

    return CallToolResult(content=[TextContent(type="text", text=text)])


class _AnyParams(BaseModel):
    model_config = ConfigDict(extra="allow")


app.add_request_handler("tools/call", _AnyParams, handle_call_tool)


def _session_capture(args: dict) -> str:
    """Принять готовых кандидатов (извлёк агент), провалидировать, показать preview, сохранить."""
    auto_approve = _as_bool(args.get("auto_approve", False)) or os.getenv("AUTO_MODE", "false").lower() == "true"

    raw = args.get("candidates", [])
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as e:
            return f"Ошибка: candidates не является валидным JSON ({e})"
    if not isinstance(raw, list) or not raw:
        return "Ошибка: candidates — непустой массив фактов."

    proposed = []
    errors = []
    for i, c in enumerate(raw, 1):
        if not isinstance(c, dict):
            errors.append(f"{i}: кандидат должен быть объектом")
            continue
        title = str(c.get("title", "")).strip()
        summary = str(c.get("content_summary", "")).strip()
        if not title:
            errors.append(f"{i}: нет title")
            continue
        if not summary:
            errors.append(f"{i}: нет content_summary")
            continue
        # Тип: известный / новый с подтверждением человека / отказ со словарём.
        # Молчаливый фолбэк на Reference — ложь о сохранённом, запрещён.
        fact_type, type_error = resolve_fact_type(
            str(c.get("type", "Reference")).strip(),
            new_type=_as_bool(c.get("new_type", False)),
            type_description=str(c.get("type_description", "") or ""),
        )
        if fact_type is None:
            errors.append(f"{i}: {type_error}")
            continue
        source_file = str(c.get("source_file", "") or "").strip() or None
        proposed.append(ProposedFact(
            type=fact_type,
            title=title,
            content_summary=summary,
            tags=parse_tags(c.get("tags")),
            evidence=str(c.get("evidence", "") or ""),
            source_file=source_file,
        ))

    from curator import server_log
    server_log.log("session_capture", stage="intake", received=len(raw), parsed=len(proposed))

    error_lines = []
    if errors:
        error_lines.append("Кандидаты с ошибками (не сохранены):")
        error_lines.extend(f"  {e}" for e in errors)

    if not proposed:
        return "\n".join(["Кандидаты пусты."] + error_lines)

    result = gatekeeper.filter(proposed)
    server_log.log("session_capture", stage="gatekeeper",
                   proposed=len(proposed), approved=len(result.approved),
                   rejected=len(result.rejected))
    saved_count = 0

    lines = [f"Получено кандидатов: {len(proposed)}"]
    if errors:
        lines.extend(error_lines)
    lines.append(f"Отклонено: {len(result.rejected)}")

    if result.rejected:
        lines.append("\nОтклонённые:")
        for fact, reason in result.rejected:
            lines.append(f"  ❌ {fact.title} — {reason}")

    if result.approved:
        lines.append(f"\nОдобрено: {len(result.approved)}")
        for i, fact in enumerate(result.approved, 1):
            lines.append(f"\n{i}. [{fact.type}] {fact.title}")
            lines.append(f"   {fact.content_summary}")
            if fact.tags:
                lines.append(f"   Теги: {', '.join(fact.tags)}")
            if fact.evidence:
                lines.append(f"   Источник: {fact.evidence[:200]}")

    if auto_approve and result.approved:
        from curator.sync_engine import SyncEngine
        from curator.routing import route_fact_safe
        sync = SyncEngine(backend, base_dir)
        saved = []
        for fact in result.approved:
            structured = StructuredFact(
                type=fact.type,
                title=fact.title,
                tags=fact.tags,
                status="verified",
                content_summary=fact.content_summary,
                source_file=route_fact_safe(router, fact),
            )
            try:
                backend.store_fact(structured)
            except Exception as e:
                server_log.log("session_capture", stage="store_error",
                               fact=fact.title, error=str(e)[:200])
                lines.append(f"\n  ⚠ не сохранён '{fact.title[:50]}': {str(e)[:100]}")
                continue
            try:
                sync.write_fact_to_md(structured)
            except Exception as e:
                server_log.log("session_capture", stage="writeback_error",
                               fact=fact.title, error=str(e)[:200])
            feedback.record_save(fact.title)
            saved.append(fact.title)
        server_log.log("session_capture", stage="autosave", saved=len(saved))
        saved_count = len(saved)
        lines.append(f"\nАвто-сохранено: {len(saved)} фактов")

    # Телеметрия кандидатов: одна запись на вызов (preview без сохранения
    # тоже запись — saved=0), не роняет capture
    _log_mcp_candidates(result, saved=saved_count, declined_by_human=False)
    return "\n".join(lines)


def _log_mcp_candidates(result, saved: int, declined_by_human: bool):
    """Телеметрия кандидатов для MCP-пути. Не роняет capture."""
    from curator import candidates_log
    candidates = [(f, "approved", "") for f in result.approved]
    candidates += [(f, "rejected", reason) for f, reason in result.rejected]
    candidates_log.log_capture("mcp", candidates, saved=saved,
                               final_status="verified" if saved else "preview",
                               session_id=None,
                               declined_by_human=declined_by_human)


def _routes() -> str:
    routes = router.list_routes()
    lines = [f"Маршрутов: {len(routes)}"]
    for r in routes:
        lines.append(f"  · {r.get('path', '?')} — {r.get('description', '')}")
    return "\n".join(lines)


def _query(args: dict) -> str:
    tags_list = None
    if args.get("tags"):
        tags_list = [t.strip() for t in args["tags"].split(",") if t.strip()]

    query = FactQuery(
        type=args.get("type"),
        tags=tags_list,
        status=args.get("status"),
        search=args.get("search"),
    )

    facts = backend.query_facts(query)

    if facts:
        feedback.record_query(len(facts), [f.title for f in facts])

    if not facts:
        return "Ничего не найдено."

    lines = [f"Найдено: {len(facts)}\n"]
    for f in facts:
        tags = ", ".join(f.tags)
        lines.append(f"### {f.title}")
        lines.append(f"{f.content_summary}")
        lines.append(f"*{f.type} | {f.status} | {tags}*\n")

    return "\n".join(lines)


def _status() -> str:
    all_facts = backend.query_facts(FactQuery())
    by_type = {}
    by_status = {}

    for f in all_facts:
        by_type[f.type] = by_type.get(f.type, 0) + 1
        by_status[f.status] = by_status.get(f.status, 0) + 1

    lines = [
        f"Всего фактов: {len(all_facts)}",
        f"База знаний: {base_dir}",
        f"По типам: {json.dumps(by_type, ensure_ascii=False)}",
        f"По статусам: {json.dumps(by_status, ensure_ascii=False)}",
        "",
        "Типы (словарь для агента):",
    ]
    for name, description in get_fact_types().items():
        lines.append(f"  {name} — {description}")
    return "\n".join(lines)


def _improve() -> str:
    report = improve.run()

    # Жизненный цикл обязан отражаться в .md: задеприкейтнутые факты
    # получают маркер [УСТАРЕЛО], иначе человеко-читаемый слой врёт
    # и rebuild из .md воскрешает устаревшее
    from curator import server_log
    from curator.sync_engine import SyncEngine
    sync = SyncEngine(backend, base_dir)
    for f in report.deprecated:
        try:
            sync.rewrite_status(f)
        except Exception as e:
            server_log.log("improve", stage="writeback_error",
                            fact=f.title, error=str(e)[:200])

    lines = [
        "=== Отчёт цикла улучшения ===",
        f"Всего фактов: {report.stats['total_facts']}",
        f"Найдено дубликатов: {report.stats['duplicates_found']}",
        f"Устаревших: {report.stats['stale_found']}",
        f"Противоречий: {report.stats['contradictions_found']}",
    ]

    if report.metrics_before and report.metrics_after:
        b, a = report.metrics_before, report.metrics_after
        lines.append(
            f"\nМетрики (до → после): coverage {b.query_coverage:.0%} → {a.query_coverage:.0%}, "
            f"факты {b.total_facts} → {a.total_facts}, "
            f"verified {b.verified_percent:.0%} → {a.verified_percent:.0%}"
        )

    if report.duplicates:
        lines.append("\nДубликаты:")
        for f1, f2 in report.duplicates[:10]:
            lines.append(f"  '{f1.title}' ↔ '{f2.title}'")

    if report.stale:
        lines.append("\nУстаревшие:")
        for f in report.stale[:10]:
            lines.append(f"  {f.title} [{f.status}]")

    if report.contradictions:
        lines.append("\nПротиворечия найдены:")
        for f1, f2 in report.contradictions[:10]:
            lines.append(f"  ⚡ '{f1.title}' ↔ '{f2.title}'")
        if report.resolutions:
            lines.append("\nРазрешение противоречий:")
            for r in report.resolutions[:10]:
                lines.append(f"  ✅ '{r.winner.title}' (победил: {r.reason})")
                lines.append(f"     ⛔ '{r.loser.title}' (отклонён)")

    if report.events:
        lines.append("\nEval-решения:")
        for e in report.events:
            status = "✅ применено" if e["applied"] else "⛔ отклонено"
            before = e.get("eval_before", None)
            after = e.get("eval_after", None)
            before_str = f"{before:.0%}" if isinstance(before, (int, float)) else "—"
            after_str = f"{after:.0%}" if isinstance(after, (int, float)) else "—"
            lines.append(f"  {e['action']}: {status} (coverage {before_str} → {after_str})")

    top = feedback.get_stats(5)
    if top:
        lines.append("\nЧасто запрашиваемые:")
        for item in top:
            lines.append(f"  {item['title']} ({item['count']}×)")

    return "\n".join(lines)


def _feedback() -> str:
    top = feedback.get_stats(10)
    unused = feedback.get_unused(30)

    lines = ["=== Статистика использования ==="]

    if top:
        lines.append(f"\nТоп-{len(top)} по запросам:")
        for i, item in enumerate(top, 1):
            lines.append(f"  {i}. {item['title']} ({item['count']} запросов)")

    if unused:
        lines.append(f"\nНе использовались >30 дней ({len(unused)}):")
        for title in unused[:10]:
            lines.append(f"  {title}")

    if not top and not unused:
        lines.append("Нет данных об использовании.")

    return "\n".join(lines)


def main():
    """Entry point для MCP-сервера."""
    import asyncio
    import sys
    print(f"[curator] MCP server starting: BACKEND={os.getenv('MEMORY_BACKEND', 'local')}", file=sys.stderr)

    # Инвариант: worker жив, пока жив MCP-сервер. opencode стартует сервер —
    # ensure поднимает мёртвый демон и чистит протухший pid. Выключатель для
    # окружений, где фоновый процесс нежелателен: CURATOR_AUTO_WORKER=false.
    if os.getenv("CURATOR_AUTO_WORKER", "true").lower() != "false":
        try:
            from curator.daemon import ensure_worker
            print(f"[curator] worker: {ensure_worker()}", file=sys.stderr)
        except Exception as e:
            print(f"[curator] worker ensure не удался: {e}", file=sys.stderr)

    async def _run():
        async with stdio_server() as (read_stream, write_stream):
            await app.run(read_stream, write_stream, app.create_initialization_options())

    asyncio.run(_run())


if __name__ == "__main__":
    main()