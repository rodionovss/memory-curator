"""Proactive delivery: query → ranked context cards (ADR 002, issue #26).

Персональная база — сотни фактов, полный скан дёшев. Ranking
детерминированный: теги (0.4) + совпадение текста (0.4) + usage (0.2).
Ошибки — во входных данных вызывающего: функции не перехватывают
исключения, транспортный слой (issue #27) отвечает за «пусто вместо
падения».
"""

from __future__ import annotations

import math
import re
import time
from dataclasses import dataclass, field

from curator.models import StructuredFact

# ~4 символа на токен — консервативная оценка латиницы/кириллицы
_CHARS_PER_TOKEN = 4
# Накладные расходы на одну карточку в выдаче (рамка, метаданные, reason)
_CARD_OVERHEAD_TOKENS = 25
# Слова короче 3 символов — шум запроса (предлоги, союзы)
_MIN_TOKEN_LEN = 3
# Префикс-стемминг: обрезка слова для матча русских словоформ
# («хендлеры»/«хендлеров» → «хендле»). Лёгкая альтернатива full-stemmer.
_STEM_LEN = 5

# Минимальный шум запроса: слова-связки, которые не несут смысла темы,
# но занимают место в coverage. Полный NLP не нужен — персональная база.
_STOPWORDS = frozenset({
    "как", "что", "это", "this", "для", "или", "при", "чем", "там", "все",
    "the", "and", "for", "with", "how", "why", "when", "what",
})

_TOKEN_RE = re.compile(r"\w+", re.UNICODE)

_DEFAULTS = {
    "limit": 3,
    "token_budget": 500,
    "relevance_threshold": 0.4,
}

_W_TAGS = 0.4
_W_TEXT = 0.4
_W_USAGE = 0.2


@dataclass
class ContextQuery:
    """Запрос proactive delivery (ADR 002)."""

    trigger: str
    types: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    exclude_tags: list[str] = field(default_factory=list)
    include_hypothesis: bool = False
    limit: int = _DEFAULTS["limit"]
    token_budget: int = _DEFAULTS["token_budget"]
    relevance_threshold: float = _DEFAULTS["relevance_threshold"]


@dataclass
class ContextCard:
    """Карточка знания для контекста агента (ADR 002)."""

    title: str
    summary: str
    tags: list[str]
    type: str
    status: str
    source_file: str | None
    score: float
    reason: str


def _tokens(text: str) -> list[str]:
    return [
        t for t in _TOKEN_RE.findall(text.casefold())
        if len(t) >= _MIN_TOKEN_LEN and t not in _STOPWORDS
    ]


def _stem(token: str) -> str:
    return token[:_STEM_LEN] if len(token) > _STEM_LEN else token


def _usage_score(title: str, usage: dict[str, dict], now: float) -> float:
    entry = usage.get(title)
    if not entry:
        return 0.0
    count = entry.get("count", 0)
    if count <= 0:
        return 0.0
    saturation = count / (count + 5.0)
    last = entry.get("last_access", 0.0)
    days_since = max(0.0, (now - last) / 86400.0)
    recency = math.exp(-days_since / 30.0)
    return saturation * recency


def _text_score(query_tokens: list[str], fact: StructuredFact) -> tuple[float, bool]:
    """Доля запроса, покрытая текстом факта. Заголовок весит вдвое."""
    if not query_tokens:
        return 0.0, False
    title_l = fact.title.casefold()
    summary_l = fact.content_summary.casefold()

    total = 0.0
    title_hit = False
    for token in query_tokens:
        stem = _stem(token)
        if stem in title_l:
            total += 1.0
            title_hit = True
        elif stem in summary_l:
            total += 0.5
    return min(1.0, total / len(query_tokens)), title_hit


def _tag_score(query_tags: set[str], fact_tags: list[str]) -> tuple[float, list[str]]:
    if not fact_tags:
        return 0.0, []
    matched = [t for t in fact_tags if t.casefold() in query_tags]
    return len(matched) / len(fact_tags), matched


def _compose_reason(matched_tags: list[str], title_hit: bool, text_hit: bool, count: int) -> str:
    parts: list[str] = []
    if matched_tags:
        parts.append(f"теги: {', '.join(matched_tags)}")
    if title_hit:
        parts.append("совпадение в заголовке")
    elif text_hit:
        parts.append("совпадение в тексте")
    if count > 0:
        parts.append(f"использовался {count} раз")
    return "; ".join(parts)


def _card_tokens(card: ContextCard) -> int:
    return (len(card.title) + len(card.summary) + len(card.reason)) // _CHARS_PER_TOKEN + _CARD_OVERHEAD_TOKENS


def retrieve(
    query: ContextQuery,
    facts: list[StructuredFact],
    usage: dict[str, dict] | None = None,
    now: float | None = None,
) -> list[ContextCard]:
    """Ранжированные карточки verified-фактов под триггер запроса.

    Deterministic: одинаковый вход → одинаковый выход. Слабое совпадение
    (ниже relevance_threshold) не возвращается — silence вместо шума.
    """
    usage = usage or {}
    now = time.time() if now is None else now

    query_tokens = _tokens(query.trigger)
    query_tags = {t.casefold() for t in query.tags}
    exclude = {t.casefold() for t in query.exclude_tags}
    allowed_types = {t for t in query.types}

    candidates: list[ContextCard] = []
    for fact in facts:
        # deprecated не попадает в выдачу никогда; hypothesis — по явному
        # запросу клиента; всё остальное должно быть verified
        if fact.status == "deprecated":
            continue
        if fact.status == "hypothesis" and not query.include_hypothesis:
            continue
        if allowed_types and fact.type not in allowed_types:
            continue
        fact_tags_l = {t.casefold() for t in fact.tags}
        if exclude & fact_tags_l:
            continue

        tag_s, matched_tags = _tag_score(query_tags, fact.tags)
        text_s, title_hit = _text_score(query_tokens, fact)
        entry = usage.get(fact.title, {})
        count = entry.get("count", 0)
        usage_s = _usage_score(fact.title, usage, now)

        # Тег считается совпавшим, если он прозвучал в тексте триггера:
        # MCP-тоулу не передают структурированные теги триггера, зато сам
        # текст триггера почти всегда содержит названия областей как есть
        trigger_l = query.trigger.casefold()
        text_matched_tags = [t for t in fact.tags if _stem(t.casefold()) in trigger_l]
        if text_matched_tags:
            bonus = len(text_matched_tags) / len(fact.tags) if fact.tags else 0.0
            tag_s = max(tag_s, bonus)
            matched_tags = matched_tags or text_matched_tags

        score = _W_TAGS * tag_s + _W_TEXT * text_s + _W_USAGE * usage_s
        if score < query.relevance_threshold:
            continue

        candidates.append(ContextCard(
            title=fact.title,
            summary=fact.content_summary,
            tags=fact.tags,
            type=fact.type,
            status=fact.status,
            source_file=fact.source_file,
            score=round(score, 4),
            reason=_compose_reason(matched_tags, title_hit, text_s > 0, count),
        ))

    # Детерминированный порядок: score desc, затем title для стабильности
    candidates.sort(key=lambda c: (-c.score, c.title))

    selected: list[ContextCard] = []
    budget_left = query.token_budget
    for card in candidates:
        if len(selected) >= query.limit:
            break
        cost = _card_tokens(card)
        if cost > budget_left:
            continue
        selected.append(card)
        budget_left -= cost
    return selected
