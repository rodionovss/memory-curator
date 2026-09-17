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
