import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal

from curator.state import state_path

FactType = Literal["Reference", "Style", "Tool", "Spec"]
FactStatus = Literal["verified", "hypothesis", "deprecated"]

# Базовый словарь типов: name → что значит. Описание — контракт для агента:
# он не гадает «что такое Tool», а читает заявленную автором семантику.
BASE_FACT_TYPES: dict[str, str] = {
    "Reference": "Справочное знание: проверенные факты, паттерны, принципы",
    "Style": "Правила работы агента: стиль, процесс, ограничения поведения",
    "Tool": "Заметки об инструментах: статус, наблюдения после проб",
    "Spec": "Спецификации и договорённости: контракты, требования",
}

_TYPE_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,29}$")


def _registry_path() -> Path:
    return state_path("fact_types.json")


def _read_registry() -> dict:
    path = _registry_path()
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return {
        name: entry.get("description", "")
        for name, entry in raw.items()
        if isinstance(name, str) and isinstance(entry, dict)
    }


def get_fact_types() -> dict[str, str]:
    """Словарь типов: name → description.

    Три источника: база в коде + env CURATOR_FACT_TYPES (имена через запятую,
    для деплоев) + персистентный реестр ~/.curator/fact_types.json (типы,
    заведённые через подтверждение человека в capture).
    """
    types = dict(BASE_FACT_TYPES)
    for name in os.getenv("CURATOR_FACT_TYPES", "").split(","):
        name = name.strip()
        if name:
            types[name] = types.get(name, "Добавлено через CURATOR_FACT_TYPES")
    types.update(_read_registry())
    return types


def is_valid_type_name(name: str) -> bool:
    """Имя типа обязано быть безопасным для имени файла (session/{type}.md),
    regex ingest и мета-строки .md."""
    return bool(_TYPE_NAME_RE.match(name))


def register_fact_type(name: str, description: str) -> tuple[bool, str]:
    """Зарегистрировать новый тип (человек подтвердил в capture).

    Требование осмысленности: тип без описания — угадайка для агента,
    словарь не должен засоряться типами «на всякий случай».
    """
    if not is_valid_type_name(name):
        return False, (f"Имя типа '{name}' некорректно: латиница/цифры/-/_ , "
                       f"начинается с буквы, до 30 знаков")
    if len(description.strip()) < 10:
        return False, "Новый тип требует описание (минимум 10 знаков) — это контракт для агента"
    types = get_fact_types()
    if name in types:
        return False, f"Тип '{name}' уже есть"
    path = _registry_path()
    try:
        raw: dict = {}
        if path.exists():
            raw = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raw = {}
        raw[name] = {"description": description.strip(), "added_at": datetime.now().isoformat()}
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as e:
        return False, f"Реестр типов недоступен: {e}"
    return True, ""


def resolve_fact_type(raw: str, new_type: bool = False, type_description: str = "") -> tuple[str | None, str | None]:
    """Решить судьбу типа кандидата: (тип, None) или (None, причина_отказа).

    Известный тип → пропустить. Неизвестный: с new_type (человек подтвердил)
    и описанием → зарегистрировать; иначе — отказ со словарём известных:
    агент видит семантику и либо соотносит, либо идёт к человеку.
    Молчаливый фолбэк на Reference запрещён — это ложь о сохранённом.
    """
    types = get_fact_types()
    if raw in types:
        return raw, None
    if new_type:
        ok, error = register_fact_type(raw, type_description)
        if ok:
            return raw, None
        return None, f"{raw}: {error}"
    dictionary = "; ".join(f"{name} — {desc}" for name, desc in types.items())
    return None, f"неизвестный тип '{raw}'. Известные: {dictionary}. " \
                 f"Если это новый тип — подтвердите у пользователя и передайте new_type=true с type_description"


def normalize_fact_type(raw: str) -> FactType:
    """Легаси для кодовых/демо данных (tour и пр.): неизвестное → Reference.

    Для входа от агента (LLM) запрещено — молчаливый фолбэк это ложь
    о сохранённом; агентский путь идёт через resolve_fact_type.
    """
    return raw if raw in get_fact_types() else "Reference"


def parse_tags(raw) -> list[str]:
    """Теги кандидата от агента: массив или строка через запятую — один
    канонический парсер для MCP-сервера и CLI."""
    if raw is None:
        return []
    if isinstance(raw, str):
        raw = raw.split(",")
    return [str(t).strip() for t in raw if str(t).strip()]


# Служебные префиксы строк рендера факта (SyncEngine._render_fact) и парсера
# (analyzers/ingest). Инъекция их в content_summary подменяет метаданные
# факта при реингесте — gatekeeper такие строки отклоняет.
META_TYPE_PREFIX = "*Тип:"
META_TAGS_PREFIX = "*Теги:"
META_LINE_PREFIXES = (META_TYPE_PREFIX, META_TAGS_PREFIX, "*Статус:", "*Файл:")


@dataclass
class StructuredFact:
    """Валидированный факт, готовый к сохранению в память."""

    type: FactType
    title: str
    tags: list[str]
    status: FactStatus
    content_summary: str
    source_file: str | None = None
    source_session: str | None = None


@dataclass
class ProposedFact:
    """Факт до валидации — пришёл из сессии или .md парсинга."""

    type: FactType
    title: str
    content_summary: str
    tags: list[str] = field(default_factory=list)
    evidence: str = ""
    # Путь .md внутри базы, предложенный агентом/скиллом (например, скилл
    # mapping-documentation разрулил glob-таргет карты). Ядро валидирует
    # его против маршрутов, а не доверяет слепо.
    source_file: str | None = None


@dataclass
class FactRef:
    """Ссылка на сохранённый факт."""

    id: str
    title: str


@dataclass
class FactQuery:
    """Параметры поиска фактов."""

    type: FactType | None = None
    tags: list[str] | None = None
    status: FactStatus | None = None
    search: str | None = None


@dataclass
class Relation:
    """Связь между двумя фактами."""

    source_id: str
    target_id: str
    kind: Literal["related_to", "contradicts"]


@dataclass
class GraphData:
    """Граф знаний: узлы и рёбра."""

    nodes: list[StructuredFact]
    edges: list[Relation]
