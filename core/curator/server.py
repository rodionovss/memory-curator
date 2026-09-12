"""MCP-сервер Memory Curator. Экспонирует тулзы для OpenCode и других MCP-клиентов.

Запуск: curator-mcp-server

Извлечение знаний делает сам агент (LLM) — opencode сейчас, любой MCP-клиент
(Claude Code) по тому же контракту. Скилл передаёт готовых кандидатов через
`candidates`. Python управляет gatekeeper и memory backend; отдельный
нейронный skill делает смысловой write-back в документацию проекта.

Конфигурация через переменные окружения:
    MEMORY_BACKEND: "xmemory" | "local" (default: "local")
    CURATOR_STATE_DIR: SQLite, outbox, логи и worker state (default: ~/.curator)
    CURATOR_BASE_DIR: директория с .md файлами
    CURATOR_MAP: путь к карте документации проекта
"""

import os
import json
import asyncio
import threading
import uuid
from collections import OrderedDict
from dataclasses import dataclass
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
        return LocalBackend()


_FACT_TYPES_DOC = "тип факта — известные типы с описаниями: см. curator_status; новый тип только после подтверждения человеком (new_type=true + type_description)"
_CAPTURE_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {"status": {"type": "string"}},
    "required": ["status"],
}


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


@dataclass(frozen=True)
class ReviewedCandidate:
    candidate_id: str
    type: str
    title: str
    content_summary: str
    tags: tuple[str, ...]
    evidence: str

    def as_dict(self) -> dict:
        return {
            "candidate_id": self.candidate_id,
            "type": self.type,
            "title": self.title,
            "content_summary": self.content_summary,
            "tags": list(self.tags),
            "evidence": self.evidence,
        }


@dataclass
class PendingCapture:
    candidates: tuple[ReviewedCandidate, ...]
    state: str = "reviewed"
    selected_candidate_ids: frozenset[str] = frozenset()


@dataclass(frozen=True)
class Placement:
    candidate_id: str
    topic: str
    target: str
    capture: str
    canonical_file: str
    changed_files: tuple[str, ...]


_captures_lock = threading.Lock()
_pending_captures: OrderedDict[str, PendingCapture] = OrderedDict()


def _json_response(**payload) -> str:
    return json.dumps(payload, ensure_ascii=False)


async def handle_list_tools(ctx, request):
    tools = [
        Tool(
            name="curator_session_capture",
            description="Проверить кандидаты знаний и вернуть preview для подтверждения человеком",
            inputSchema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "candidates": {
                        "type": "array",
                        "minItems": 1,
                        "description": ("Кандидаты: [{type, title, content_summary, tags: [], evidence, "
                                         "new_type (опционально: true если пользователь подтвердил новый тип), "
                                         "type_description (описание нового типа, обязательно при new_type)}]"),
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "type": {"type": "string", "description": _FACT_TYPES_DOC},
                                "title": {"type": "string"},
                                "content_summary": {"type": "string"},
                                "tags": {"type": "array", "items": {"type": "string"}},
                                "evidence": {"type": "string"},
                                "new_type": {"type": "boolean", "description": "пользователь подтвердил заведение нового типа"},
                                "type_description": {"type": "string", "description": "что значит новый тип — контракт для агента"},
                            },
                            "required": ["type", "title", "content_summary", "tags"],
                        },
                    },
                },
                "required": ["candidates"],
            },
            outputSchema=_CAPTURE_OUTPUT_SCHEMA,
        ),
        Tool(
            name="curator_capture_approve",
            description="Зафиксировать выбранное человеком подмножество проверенных кандидатов",
            inputSchema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "capture_id": {"type": "string"},
                    "selected_candidate_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": ["capture_id", "selected_candidate_ids"],
            },
            outputSchema=_CAPTURE_OUTPUT_SCHEMA,
        ),
        Tool(
            name="curator_capture_complete",
            description="Проверить размещение в документации и сохранить поисковую копию фактов",
            inputSchema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "capture_id": {"type": "string"},
                    "placements": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "candidate_id": {"type": "string"},
                                "topic": {"type": "string"},
                                "target": {"type": "string"},
                                "capture": {"type": "string"},
                                "canonical_file": {"type": "string"},
                                "changed_files": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                            },
                            "required": [
                                "candidate_id", "topic", "target", "capture",
                                "canonical_file", "changed_files",
                            ],
                        },
                    },
                },
                "required": ["capture_id", "placements"],
            },
            outputSchema=_CAPTURE_OUTPUT_SCHEMA,
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
    elif name == "curator_capture_approve":
        text = await asyncio.to_thread(_capture_approve, arguments)
    elif name == "curator_capture_complete":
        text = await asyncio.to_thread(_capture_complete, arguments)
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

    structured = json.loads(text) if name in {
        "curator_session_capture", "curator_capture_approve", "curator_capture_complete",
    } else None
    return CallToolResult(
        content=[TextContent(type="text", text=text)],
        structuredContent=structured,
    )


class _AnyParams(BaseModel):
    model_config = ConfigDict(extra="allow")


app.add_request_handler("tools/call", _AnyParams, handle_call_tool)


def _session_capture(args: dict) -> str:
    """Проверить кандидатов и создать process-local capture без сохранения."""
    raw = args.get("candidates", [])
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as e:
            return _json_response(status="error", error=f"candidates не является валидным JSON ({e})")
    if not isinstance(raw, list) or not raw:
        return _json_response(status="error", error="candidates должен быть непустым массивом фактов")

    proposed: list[tuple[str, ProposedFact]] = []
    rejected: list[dict] = []
    seen_titles: set[str] = set()
    for i, c in enumerate(raw, 1):
        candidate_id = f"fact_{i}"
        if not isinstance(c, dict):
            rejected.append({"candidate_id": candidate_id, "reason": "кандидат должен быть объектом"})
            continue
        if not isinstance(c.get("type"), str) or not c["type"].strip():
            rejected.append({"candidate_id": candidate_id, "reason": "нет type"})
            continue
        if not isinstance(c.get("title"), str):
            rejected.append({"candidate_id": candidate_id, "reason": "title должен быть строкой"})
            continue
        if not isinstance(c.get("content_summary"), str):
            rejected.append({"candidate_id": candidate_id, "reason": "content_summary должен быть строкой"})
            continue
        tags = c.get("tags")
        if not isinstance(tags, list) or any(not isinstance(tag, str) for tag in tags):
            rejected.append({"candidate_id": candidate_id, "reason": "tags должен быть массивом строк"})
            continue
        title = c["title"].strip()
        summary = c["content_summary"].strip()
        if not title:
            rejected.append({"candidate_id": candidate_id, "reason": "нет title"})
            continue
        if not summary:
            rejected.append({"candidate_id": candidate_id, "title": title,
                             "reason": "нет content_summary"})
            continue
        fact_type, type_error = resolve_fact_type(
            c["type"].strip(),
            new_type=_as_bool(c.get("new_type", False)),
            type_description=str(c.get("type_description", "") or ""),
        )
        if fact_type is None:
            rejected.append({"candidate_id": candidate_id, "title": title, "reason": type_error})
            continue
        if title in seen_titles:
            rejected.append({"candidate_id": candidate_id, "title": title,
                             "reason": "кандидат дублирует title в этом capture"})
            continue
        seen_titles.add(title)
        proposed.append((candidate_id, ProposedFact(
            type=fact_type,
            title=title,
            content_summary=summary,
            tags=parse_tags(tags),
            evidence=str(c.get("evidence", "") or ""),
        )))

    from curator import server_log
    server_log.log("session_capture", stage="intake", received=len(raw), parsed=len(proposed))
    result = gatekeeper.filter([fact for _, fact in proposed])
    server_log.log("session_capture", stage="gatekeeper",
                    proposed=len(proposed), approved=len(result.approved),
                    rejected=len(result.rejected))

    ids_by_identity = {id(fact): candidate_id for candidate_id, fact in proposed}
    eligible = tuple(
        ReviewedCandidate(
            candidate_id=ids_by_identity[id(fact)],
            type=fact.type,
            title=fact.title,
            content_summary=fact.content_summary,
            tags=tuple(fact.tags),
            evidence=fact.evidence,
        )
        for fact in result.approved
    )
    rejected.extend({
        **ReviewedCandidate(
            candidate_id=ids_by_identity[id(fact)],
            type=fact.type,
            title=fact.title,
            content_summary=fact.content_summary,
            tags=tuple(fact.tags),
            evidence=fact.evidence,
        ).as_dict(),
        "reason": reason,
    } for fact, reason in result.rejected)

    capture_id = f"cap_{uuid.uuid4().hex}"
    with _captures_lock:
        _pending_captures[capture_id] = PendingCapture(eligible)
        while len(_pending_captures) > 100:
            _pending_captures.popitem(last=False)

    # Телеметрия кандидатов: одна запись на вызов (preview без сохранения
    # тоже запись — saved=0), не роняет capture
    _log_mcp_candidates(result, saved=0, declined_by_human=False)
    return _json_response(
        status="needs_human_approval",
        capture_id=capture_id,
        eligible=[candidate.as_dict() for candidate in eligible],
        rejected=rejected,
    )


def _project_paths() -> tuple[Path, Path] | tuple[None, str]:
    from curator.routing.map_router import find_map_path
    root = Path(os.getenv("CURATOR_BASE_DIR", str(base_dir))).expanduser().resolve()
    # 1. Явный CURATOR_MAP всегда главный («установил, задал и всё»)
    configured_map = os.getenv("CURATOR_MAP", "").strip()
    if configured_map:
        map_path = Path(configured_map).expanduser().resolve()
        if not map_path.is_file():
            return None, f"CURATOR_MAP не существует: {map_path}"
        return root, map_path
    # 2. Конвенция: DOCUMENTATION-MAP.md в корне базы — работает без env
    found = find_map_path()
    if found is not None:
        return root, found.expanduser().resolve()
    # 3. Карты нет вообще — ведём человека к настройке, а не сухой ошибкой
    return None, (
        "карта документации не настроена: создай DOCUMENTATION-MAP.md в корне базы "
        "(CURATOR_BASE_DIR) или задай CURATOR_MAP, затем вызови /curator-setup — "
        "шаги настройки в docs/getting-started.md"
    )


def _approval_manifest(capture_id: str, capture: PendingCapture, root: Path,
                       map_path: Path) -> str:
    return _json_response(
        status="update_project_docs",
        next_action="curator-update-docs",
        capture_id=capture_id,
        base_dir=str(root),
        map_path=str(map_path),
        facts=[candidate.as_dict() for candidate in capture.candidates
               if candidate.candidate_id in capture.selected_candidate_ids],
    )


def _capture_approve(args: dict) -> str:
    capture_id = str(args.get("capture_id", "")).strip()
    selected = args.get("selected_candidate_ids")
    if not capture_id or not isinstance(selected, list) or any(not isinstance(x, str) for x in selected):
        return _json_response(status="error", error="capture_id и selected_candidate_ids обязательны")
    selected_ids = frozenset(selected)
    if len(selected_ids) != len(selected):
        return _json_response(status="error", error="selected_candidate_ids не должен содержать дубликаты")

    with _captures_lock:
        capture = _pending_captures.get(capture_id)
        if capture is None:
            return _json_response(status="error", error="capture_id не найден")
        if capture.state == "approved":
            if capture.selected_candidate_ids != selected_ids:
                return _json_response(status="error", error="выбранный набор уже зафиксирован")
            paths = _project_paths()
            if paths[0] is None:
                return _json_response(status="error", error=paths[1])
            return _approval_manifest(capture_id, capture, paths[0], paths[1])
        if capture.state != "reviewed":
            return _json_response(status="error", error=f"capture имеет состояние {capture.state}")
        if not selected_ids:
            del _pending_captures[capture_id]
            return _json_response(status="cancelled", capture_id=capture_id)
        eligible_ids = {candidate.candidate_id for candidate in capture.candidates}
        unknown = selected_ids - eligible_ids
        if unknown:
            return _json_response(status="error", error=f"неизвестные candidate_id: {sorted(unknown)}")
        paths = _project_paths()
        if paths[0] is None:
            return _json_response(status="error", error=paths[1])
        root, map_path = paths
        capture.state = "approved"
        capture.selected_candidate_ids = selected_ids
        return _approval_manifest(capture_id, capture, root, map_path)


def _relative_existing_file(root: Path, raw_path, target: str) -> tuple[str | None, str | None]:
    from curator.routing.map_router import MapRouter

    if not isinstance(raw_path, str) or not raw_path.strip() or not MapRouter._safe_source(raw_path):
        return None, f"путь '{raw_path}' должен быть безопасным root-relative путём"
    relative = raw_path.replace("\\", "/")
    resolved = (root / relative).resolve()
    try:
        resolved_relative = resolved.relative_to(root).as_posix()
    except ValueError:
        return None, f"путь '{raw_path}' находится вне CURATOR_BASE_DIR"
    if not resolved.is_file():
        return None, f"файл '{relative}' должен существовать"
    if not MapRouter.matches_target(resolved_relative, target):
        return None, f"файл '{relative}' не совпадает с target '{target}'"
    return resolved_relative, None


def _capture_complete(args: dict) -> str:
    from curator.routing.map_router import MapRouter

    capture_id = str(args.get("capture_id", "")).strip()
    placements = args.get("placements")
    if not capture_id or not isinstance(placements, list):
        return _json_response(status="error", error="capture_id и placements обязательны")
    paths = _project_paths()
    if paths[0] is None:
        return _json_response(status="error", error=paths[1])
    root, map_path = paths
    map_router = MapRouter(map_path)

    with _captures_lock:
        capture = _pending_captures.get(capture_id)
        if capture is None or capture.state != "approved":
            return _json_response(status="error", error="capture_id не найден или не approved")

        selected_ids = capture.selected_candidate_ids
        valid_placements = all(
            isinstance(placement, dict) and isinstance(placement.get("candidate_id"), str)
            for placement in placements
        )
        placement_ids = [placement["candidate_id"] for placement in placements] if valid_placements else []
        if (not valid_placements or len(placement_ids) != len(selected_ids)
                or set(placement_ids) != selected_ids or len(set(placement_ids)) != len(placement_ids)):
            return _json_response(status="error", error="для каждого выбранного факта нужен ровно один placement")

        canonical_by_id = {}
        documents = []
        for raw_placement in placements:
            placement = Placement(
                candidate_id=raw_placement["candidate_id"],
                topic=str(raw_placement.get("topic", "")),
                target=str(raw_placement.get("target", "")),
                capture=str(raw_placement.get("capture", "")),
                canonical_file=raw_placement.get("canonical_file"),
                changed_files=tuple(raw_placement.get("changed_files"))
                if isinstance(raw_placement.get("changed_files"), list) else (),
            )
            candidate_id = placement.candidate_id
            config = map_router.target_config(placement.topic, placement.target)
            if config is None:
                return _json_response(status="error", error=f"неизвестная точная пара topic/target для {candidate_id}")
            if placement.capture not in config["captures"]:
                return _json_response(status="error", error=f"capture '{placement.capture}' не разрешён target для {candidate_id}")
            if config["mode"] not in ("update", "append"):
                return _json_response(status="error", error=f"target для {candidate_id} имеет readonly mode")

            if not placement.changed_files:
                return _json_response(status="error", error=f"changed_files для {candidate_id} должен быть непустым")
            if not isinstance(placement.canonical_file, str) or placement.canonical_file.replace("\\", "/") not in {
                    str(path).replace("\\", "/") for path in placement.changed_files}:
                return _json_response(status="error", error=f"changed_files должен содержать canonical_file для {candidate_id}")

            normalized_changed = []
            for changed_file in placement.changed_files:
                normalized, error = _relative_existing_file(root, changed_file, placement.target)
                if error:
                    return _json_response(status="error", error=error)
                normalized_changed.append(normalized)
            canonical, error = _relative_existing_file(root, placement.canonical_file, placement.target)
            if error:
                return _json_response(status="error", error=error)
            canonical_by_id[candidate_id] = canonical
            for changed_file in normalized_changed:
                if changed_file not in documents:
                    documents.append(changed_file)

        candidates = {candidate.candidate_id: candidate for candidate in capture.candidates}
        capture.state = "completing"

    saved = 0
    try:
        for candidate_id in placement_ids:
            candidate = candidates[candidate_id]
            backend.store_fact(StructuredFact(
                type=candidate.type,
                title=candidate.title,
                tags=list(candidate.tags),
                status="verified",
                content_summary=candidate.content_summary,
                source_file=canonical_by_id[candidate_id],
            ))
            feedback.record_save(candidate.title)
            saved += 1
    except Exception as e:
        with _captures_lock:
            if _pending_captures.get(capture_id) is capture:
                capture.state = "approved"
        return _json_response(status="error", error=f"backend store failed: {e}", saved=saved)

    with _captures_lock:
        if _pending_captures.get(capture_id) is capture:
            del _pending_captures[capture_id]
    # Телеметрия: complete-вызов закрывает цикл записи (saved=N, verified)
    from curator import candidates_log
    candidates_log.log_capture(
        "mcp",
        [(candidate, "approved", "") for candidate in capture.candidates
         if candidate.candidate_id in selected_ids],
        saved=saved,
        final_status="verified" if saved else "preview",
        session_id=None,
        declined_by_human=False,
    )
    return _json_response(
        status="completed",
        capture_id=capture_id,
        saved=saved,
        documents=documents,
    )


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
    from curator.state import state_dir

    all_facts = backend.query_facts(FactQuery())
    by_type = {}
    by_status = {}

    for f in all_facts:
        by_type[f.type] = by_type.get(f.type, 0) + 1
        by_status[f.status] = by_status.get(f.status, 0) + 1

    lines = [
        f"Всего фактов: {len(all_facts)}",
        f"База знаний: {base_dir}",
        f"Состояние: {state_dir()}",
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

    # Semantic project docs меняет нейронный write-back. Без project map
    # сохраняем legacy lifecycle-синхронизацию Curator-секций.
    from curator.routing.map_router import find_map_path
    if find_map_path() is None:
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
