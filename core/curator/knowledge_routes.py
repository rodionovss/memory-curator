"""Детерминированная генерация Knowledge Routes — метаданные уровня файла.

Контракт: design/knowledge-route-format.md. Один route entry = один
source_file; каталог содержит только метаданные для маршрутизации,
никогда — содержимое фактов (content_summary, тела).
"""

from dataclasses import dataclass
from pathlib import Path

from curator.models import StructuredFact


@dataclass(frozen=True)
class KnowledgeRoute:
    """Route entry каталога: указатель на один source_file."""

    name: str
    source_file: str
    description: str
    when_to_use: tuple[str, ...]
    contains: tuple[str, ...]


@dataclass(frozen=True)
class RouteBuildResult:
    """Результат сборки каталога: маршруты + видимые ошибки валидации."""

    routes: tuple[KnowledgeRoute, ...]
    validation_errors: tuple[str, ...]


def _ci_key(value: str) -> tuple[str, str]:
    """Ключ сортировки без учёта регистра; оригинал стабилизирует равные casefold."""
    return (value.casefold(), value)


def _normalize_source(source: str, base_dir: Path) -> tuple[str, str]:
    """Source_file → root-relative POSIX-путь. Возвращает (путь, "") или ("", ошибка).

    Абсолютные пути вне base_dir и `..`-обход после нормализации отклоняются —
    маршрут не может указывать за пределы базы.
    """
    if "\n" in source or "\r" in source:
        return "", f"source_file содержит перевод строки: {source!r}"
    root = base_dir.resolve()
    candidate = source.replace("\\", "/")
    path = Path(candidate)
    resolved = path.resolve() if path.is_absolute() else (root / candidate).resolve()
    if not resolved.is_relative_to(root):
        return "", f"source_file вне base_dir: {source}"
    relative = resolved.relative_to(root).as_posix()
    if not relative:
        return "", f"source_file некорректен: {source}"
    return relative, ""


def _build_route(source_file: str, group: list[StructuredFact]) -> KnowledgeRoute:
    """Route entry из группы фактов одного файла. Только метаданные, без содержимого."""
    name = Path(source_file).stem
    type_label = "/".join(sorted({f.type for f in group}))
    tags = sorted({t for f in group for t in f.tags if t.strip()}, key=_ci_key)
    description = (
        f"{type_label} knowledge from {name}: {', '.join(tags)}"
        if tags
        else f"{type_label} knowledge from {name}"
    )
    when_to_use = tuple(
        sorted(
            {t for f in group for t in f.tags if t.strip()} | {f.title for f in group},
            key=_ci_key,
        )
    )
    contains = tuple(sorted({f.title for f in group}, key=_ci_key))
    return KnowledgeRoute(
        name=name,
        source_file=source_file,
        description=description,
        when_to_use=when_to_use,
        contains=contains,
    )


def build_routes(facts: list[StructuredFact], base_dir: Path) -> RouteBuildResult:
    """Собрать маршруты из фактов: группировка по source_file, deprecated excluded.

    Факты без source_file и с небезопасными путями не пропускаются молча —
    попадают в validation_errors и видны человеку.
    """
    groups: dict[str, list[StructuredFact]] = {}
    errors: list[str] = []
    for fact in facts:
        if fact.status == "deprecated":
            continue
        source = (fact.source_file or "").strip()
        if not source:
            errors.append(f"Факт '{fact.title}': отсутствует source_file")
            continue
        relative, error = _normalize_source(source, base_dir)
        if error:
            errors.append(f"Факт '{fact.title}': {error}")
            continue
        groups.setdefault(relative, []).append(fact)

    routes = tuple(
        _build_route(source_file, group) for source_file, group in sorted(groups.items())
    )
    return RouteBuildResult(routes=routes, validation_errors=tuple(errors))


def build_routes_from_map(topics: list[dict], facts: list[StructuredFact],
                          base_dir: Path) -> RouteBuildResult:
    """Проекция карты тем (источник истины) + заголовки фактов DB.

    topics: [{"name": str, "tokens": set[str], "targets": [str]}] — таргеты
    темы карты; glob-таргеты в маршруты не попадают (нет конкретного файла).
    contains каждого маршрута — заголовки фактов с этим source_file.
    Факты вне таргетов карты попадают в validation_errors (кроме session/ —
    дефолт-приёмник становится маршрутом «на разбор»).
    """
    groups: dict[str, list[StructuredFact]] = {}
    for fact in facts:
        if fact.status == "deprecated":
            continue
        source = (fact.source_file or "").strip()
        if source:
            groups.setdefault(source.replace("\\", "/"), []).append(fact)

    routes: list[KnowledgeRoute] = []
    errors: list[str] = []
    seen_targets: set[str] = set()
    for topic in topics:
        tokens = sorted(t for t in topic.get("tokens", ()) if t.strip())
        for target in topic.get("targets", ()):
            if any(ch in target for ch in "*?[{"):
                continue
            if target in seen_targets:
                continue  # две темы в один файл — маршрут уже есть
            seen_targets.add(target)
            group = groups.pop(target, [])
            name = Path(target).stem
            description = (
                f"тема '{topic['name']}'"
                + (f": {', '.join(tokens)}" if tokens else "")
            )
            when_to_use = tuple(tokens) or (topic["name"],)
            contains = tuple(sorted({f.title for f in group}, key=_ci_key))
            routes.append(KnowledgeRoute(
                name=name, source_file=target, description=description,
                when_to_use=when_to_use, contains=contains,
            ))

    # Остаток: факты вне карты. session/ — легитимный дефолт-приёмник,
    # становится маршрутом «на разбор»; всё прочее — видимая рассинхронизация.
    session_facts: list[StructuredFact] = []
    for source in sorted(groups):
        if source.startswith("session/"):
            session_facts.extend(groups[source])
        else:
            errors.append(
                f"Факты вне таргетов карты ({source}): "
                f"{', '.join(f.title[:40] for f in groups[source][:3])}"
            )
    if session_facts:
        routes.append(KnowledgeRoute(
            name="session",
            source_file="session/",
            description="Неразобранное: факты без темы в карте — кандидаты на маршрутизацию",
            when_to_use=("неразобранное", "без темы"),
            contains=tuple(sorted({f.title for f in session_facts}, key=_ci_key)),
        ))

    routes.sort(key=lambda r: _ci_key(r.name))
    return RouteBuildResult(routes=tuple(routes), validation_errors=tuple(errors))


def build_catalog(backend, base_dir: Path) -> RouteBuildResult:
    """Сборка каталога: карта есть → проекция карты, нет → из фактов.

    Единая точка для CLI (`curator knowledge-routes`) и авто-регенерации
    после `curator save` — пути не расходятся.
    """
    from curator.models import FactQuery
    from curator.routing.map_router import MapRouter, find_map_path

    facts = backend.query_facts(FactQuery())
    map_path = find_map_path()
    if map_path is not None and map_path.exists():
        router = MapRouter(map_path)
        topics = [
            {"name": t.name, "tokens": t.tokens,
             "targets": [tg.path for tg in t.targets]}
            for t in router._topics
        ]
        return build_routes_from_map(topics, facts, base_dir)
    return build_routes(facts, base_dir)


def render_catalog(backend, base_dir: Path) -> str:
    """Полный Markdown-каталог маршрутов (общая сборка для save и CLI).

    Детерминированный рендер уровня файла; только метаданные, без
    содержимого фактов (контракт design/knowledge-route-format.md).
    """
    return render_routes_markdown(list(build_catalog(backend, base_dir).routes))


def _bullets(items: tuple[str, ...]) -> list[str]:
    """Список по схеме контракта: `- item;`, последний пункт заканчивается точкой."""
    if not items:
        return []
    return [f"- {item};" for item in items[:-1]] + [f"- {items[-1]}."]


def render_routes_markdown(routes: list[KnowledgeRoute]) -> str:
    """Стабильный Markdown-каталог маршрутов; пустой список → пустая строка."""
    blocks: list[str] = []
    for route in routes:
        lines = [
            f"## {route.name}",
            "",
            f"**Description:** {route.description}",
            "",
            "**When to use:**",
            *_bullets(route.when_to_use),
            "",
            "**Contains:**",
            *_bullets(route.contains),
            "",
            f"**Source:** `{route.source_file}`",
        ]
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) + "\n" if blocks else ""


def render_routes_json(routes: list[KnowledgeRoute]) -> list[dict]:
    """Каталог маршрутов в виде JSON-структуры для программной доставки."""
    return [
        {
            "name": route.name,
            "source_file": route.source_file,
            "description": route.description,
            "when_to_use": list(route.when_to_use),
            "contains": list(route.contains),
        }
        for route in routes
    ]
