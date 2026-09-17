"""Детерминированное расширение запроса алиасами — retrieval v2, задача 8.

Словарь `query_aliases.json` (не LLM): ключ — слово/фраза пользователя,
значение — канонические термины базы. Расширение участвует только в
генерации кандидатов и скоринге; исходный триггер не меняется, текст
выдачи не содержит расширенных терминов.

Правила контракта:

- детерминированность и case-insensitive сопоставление;
- multi-word алиасы матчатся longest-first (поглощение диапазона), затем
  одиночные токены — одиночный ключ не срабатывает внутри уже
  сматченной фразы;
- дубликаты расширенных терминов убираются с сохранением первого-seen
  порядка (глобально, между ключами тоже);
- общие слова (screen/feature/code) не расширяются никогда — алиасы
  только на узкие технические термины;
- `expand_query(text, aliases) -> list[str]` — плоский список терминов;
  `expand_query_detailed` — атрибуция «какой ключ какие термины дал»
  для debug-reasons доставки.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

# Общие слова не расширяются: алиас на «экран»/«фичу»/«код» тащит шум
# в любой запрос. Словарь — только узкие технические термины.
_GENERIC_KEYS = frozenset({"screen", "feature", "code"})

_ALIASES_PATH = Path(__file__).parent / "query_aliases.json"


def load_aliases(path: Path | None = None) -> dict[str, list[str]]:
    """Загрузить словарь алиасов. Битый/отсутствующий файл → пустой словарь.

    Доставка деградирует до fact-only совпадений, но не падает.
    """
    source = path or _ALIASES_PATH
    try:
        raw = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return {
        str(key): [str(term) for term in terms]
        for key, terms in raw.items()
        if isinstance(terms, list)
    }


def _iter_keys(aliases: dict[str, list[str]]) -> list[str]:
    """Ключи в порядке матчинга: multi-word первыми, длинные первее коротких."""
    keys = [k for k in aliases if k.strip()]
    return sorted(
        keys,
        key=lambda k: (-len(k.split()), -len(k.casefold()), k.casefold()),
    )


def _matches(haystack: str, key: str, consumed: list[tuple[int, int]]) -> bool:
    """Есть ли непоглощённое word-boundary-совпадение ключа в тексте.

    Совпавшие диапазоны добавляются в consumed: более короткие ключи
    (longest-first) не срабатывают внутри уже сматченной фразы.
    """
    pattern = re.compile(r"(?<!\w)" + re.escape(key) + r"(?!\w)")
    found = False
    for m in pattern.finditer(haystack):
        s, e = m.span()
        if any(s < ce and e > cs for cs, ce in consumed):
            continue
        consumed.append((s, e))
        found = True
    return found


def expand_query_detailed(
    text: str, aliases: dict[str, list[str]]
) -> list[tuple[str, list[str]]]:
    """Атрибуция расширения: [(ключ, [новые термины]), ...] в порядке матчинга.

    Ключ, все термины которого уже выданы раньше, пропускается —
    дубликаты убираются с сохранением первого-seen порядка.
    """
    if not text or not aliases:
        return []
    haystack = text.casefold()
    consumed: list[tuple[int, int]] = []
    result: list[tuple[str, list[str]]] = []
    seen_terms: set[str] = set()
    for key in _iter_keys(aliases):
        if key.casefold().strip() in _GENERIC_KEYS:
            continue
        if not _matches(haystack, key.casefold().strip(), consumed):
            continue
        fresh = []
        for term in aliases[key]:
            if term.casefold() not in seen_terms:
                seen_terms.add(term.casefold())
                fresh.append(term)
        if fresh:
            result.append((key, fresh))
    return result


def expand_query(text: str, aliases: dict[str, list[str]]) -> list[str]:
    """Расширенные термины запроса: плоско, без дубликатов, first-seen порядок."""
    return [term for _, terms in expand_query_detailed(text, aliases) for term in terms]
