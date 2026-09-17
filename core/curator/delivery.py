"""Proactive delivery: query → ranked context cards (ADR 002, issue #26).

Персональная база — сотни фактов, полный скан дёшев. Ranking
детерминированный: теги (0.4) + совпадение текста (0.4) + usage (0.2).
Ошибки — во входных данных вызывающего: функции не перехватывают
исключения, транспортный слой (issue #27) отвечает за «пусто вместо
падения».

Retrieval v2: перед переранжированием добавлен маршрутный уровень
(knowledge routes, задачи #7): метаданные файлов (description/
when_to_use/contains) дают дополнительные кандидаты — факты из
сматченных source_file. Маршрут поднимает кандидатуру (буст ≤ 0.5 от
покрытия метаданных), но порог переранжирования не обходится: слабый
факт остаётся тишиной.

Расширение запроса алиасами (задача 8): детерминированный словарь
`query_aliases.json` даёт канонические термины базы для слов
пользователя («dao» → repository/suspend/room). Расширенные термины
участвуют только в генерации кандидатов (бонус к text score ≤ 0.5 от
покрытия, матч тегов) — исходный триггер не меняется, совпадения
помечаются фрагментом reason «alias:<ключ>→<термины>». Общие слова
(screen/feature/code) не расширяются.
"""

from __future__ import annotations

import math
import os
import posixpath
import re
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from curator.knowledge_routes import KnowledgeRoute, build_routes
from curator.models import FactQuery, StructuredFact
from curator.query_expansion import expand_query_detailed, load_aliases

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

# Порог переранжирования валидирован пороговым sweep-ом (Task 8):
# benchmark/experiments/results/04-storage/threshold-sweep.json —
# 0.4 наивысший порог из прошедших все гейты (precision 1.0, recall
# 0.375 > baseline 0.312, leak 0.0, FP 0.0) на замороженных запросах.
_DEFAULTS = {
    "limit": 3,
    "token_budget": 500,
    "relevance_threshold": 0.4,
}

_W_TAGS = 0.4
_W_TEXT = 0.4
_W_USAGE = 0.2

# Маршрутный буст — доля от покрытия метаданных маршрута. Меньше 1.0:
# маршрут не может заменить собственное совпадение факта с запросом,
# только поднять кандидата из сматченного файла до переранжирования.
_ROUTE_TEXT_DISCOUNT = 0.5

# Бонус алиасного расширения — та же доля, что у маршрутов: совпадение
# расширенного термина подтверждает тему, но не заменяет прямое
# совпадение факта с запросом. Порог переранжирования не обходится.
_ALIAS_TEXT_DISCOUNT = 0.5

# Словарь алиасов — part of пакета; битый/отсутствующий файл деградирует
# до fact-only совпадений без падения доставки.
_QUERY_ALIASES = load_aliases()


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


def _fact_source_key(source: str | None) -> str:
    """Канонический ключ source_file для матча факт↔маршрут."""
    if not source:
        return ""
    return posixpath.normpath(source.replace("\\", "/"))


def _route_coverage(query_tokens: list[str], route: KnowledgeRoute) -> float:
    """Доля запроса, покрытая метаданными маршрута (без содержимого фактов)."""
    if not query_tokens:
        return 0.0
    blob = " ".join(
        (route.description, *route.when_to_use, *route.contains)
    ).casefold()
    total = sum(1.0 for token in query_tokens if _stem(token) in blob)
    return total / len(query_tokens)


def _route_boosts(
    query_tokens: list[str], routes: Sequence[KnowledgeRoute]
) -> dict[str, tuple[float, str]]:
    """source_file → (буст кандидатуры, source_file маршрута).

    Файл без совпадений метаданных не входит. Несколько маршрутов на один
    файл (нештатный случай) — берётся максимальный буст.
    """
    boosts: dict[str, tuple[float, str]] = {}
    for route in routes:
        if not route.source_file:
            continue
        coverage = _route_coverage(query_tokens, route)
        if coverage <= 0.0:
            continue
        boost = coverage * _ROUTE_TEXT_DISCOUNT
        key = _fact_source_key(route.source_file)
        current = boosts.get(key)
        if current is None or boost > current[0]:
            boosts[key] = (boost, route.source_file)
    return boosts


def _expanded_text_score(
    expanded_tokens: list[str], fact: StructuredFact
) -> tuple[float, list[str]]:
    """Покрытие расширенных терминов фактом + сами совпавшие термины.

    Веса те же, что у прямого совпадения: заголовок 1.0, текст 0.5.
    """
    if not expanded_tokens:
        return 0.0, []
    title_l = fact.title.casefold()
    summary_l = fact.content_summary.casefold()
    total = 0.0
    hit_terms: list[str] = []
    for token in expanded_tokens:
        stem = _stem(token)
        if stem in title_l:
            total += 1.0
            hit_terms.append(token)
        elif stem in summary_l:
            total += 0.5
            hit_terms.append(token)
    return total / len(expanded_tokens), hit_terms


def _alias_reason(
    alias_matches: list[tuple[str, list[str]]], hit_tokens: set[str]
) -> str | None:
    """Стабильный фрагмент reason: alias:<ключ>→<совпавшие термины>.

    Несколько ключей разделяются «; ». Ключ без единого совпавшего
    термина в reason не попадает.
    """
    parts: list[str] = []
    for key, terms in alias_matches:
        key_tokens = list(dict.fromkeys(_tokens(" ".join(terms))))
        hit = [t for t in key_tokens if t in hit_tokens]
        if hit:
            parts.append(f"{key}→{', '.join(hit)}")
    return "alias:" + "; ".join(parts) if parts else None


def _compose_reason(
    matched_tags: list[str],
    title_hit: bool,
    text_hit: bool,
    count: int,
    route_source: str | None = None,
    alias_fragment: str | None = None,
) -> str:
    parts: list[str] = []
    if matched_tags:
        parts.append(f"теги: {', '.join(matched_tags)}")
    if title_hit:
        parts.append("совпадение в заголовке")
    elif text_hit:
        parts.append("совпадение в тексте")
    if route_source:
        parts.append(f"route:{route_source}")
    if alias_fragment:
        parts.append(alias_fragment)
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
    routes: Sequence[KnowledgeRoute] = (),
) -> list[ContextCard]:
    """Ранжированные карточки verified-фактов под триггер запроса.

    Deterministic: одинаковый вход → одинаковый выход. Слабое совпадение
    (ниже relevance_threshold) не возвращается — silence вместо шума.

    Retrieval v2: маршруты (routes) дают file-level кандидаты — метаданные
    маршрута матчатся текстом запроса, факты из сматченных файлов получают
    буст кандидатуры. Буст не минует порог: каждый факт переранжируется
    индивидуально, как и без маршрутов. Алиасы расширяют генерацию
    кандидатов теми же правилами: ограниченный бонус, порог не обходится.
    """
    usage = usage or {}
    now = time.time() if now is None else now

    query_tokens = _tokens(query.trigger)
    query_tags = {t.casefold() for t in query.tags}
    exclude = {t.casefold() for t in query.exclude_tags}
    allowed_types = {t for t in query.types}
    route_boosts = _route_boosts(query_tokens, routes)

    # Расширение алиасами (задача 8): детерминированный словарь даёт
    # канонические термины для слов пользователя. Токены, уже звучащие
    # в триггере напрямую, не дублируются.
    alias_matches = expand_query_detailed(query.trigger, _QUERY_ALIASES)
    alias_terms = [t for _, terms in alias_matches for t in terms]
    direct_tokens = set(query_tokens)
    expanded_tokens = list(dict.fromkeys(
        t for t in _tokens(" ".join(alias_terms)) if t not in direct_tokens
    ))

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
        direct_text_s, title_hit = _text_score(query_tokens, fact)
        entry = usage.get(fact.title, {})
        count = entry.get("count", 0)
        usage_s = _usage_score(fact.title, usage, now)

        # Тег считается совпавшим, если он прозвучал в тексте триггера
        # или среди расширенных алиасами терминов: MCP-тоулу не передают
        # структурированные теги триггера, зато сам текст триггера почти
        # всегда содержит названия областей как есть
        trigger_l = query.trigger.casefold()
        if alias_terms:
            trigger_l += " " + " ".join(alias_terms).casefold()
        text_matched_tags = [t for t in fact.tags if _stem(t.casefold()) in trigger_l]
        if text_matched_tags:
            bonus = len(text_matched_tags) / len(fact.tags) if fact.tags else 0.0
            tag_s = max(tag_s, bonus)
            matched_tags = matched_tags or text_matched_tags

        # Алиасное расширение (retrieval v2, задача 8): совпавшие
        # расширенные термины добавляют ограниченный бонус к text score,
        # не заменяя прямое совпадение и не обходя порог.
        alias_s, alias_hit_terms = _expanded_text_score(expanded_tokens, fact)
        alias_fragment = _alias_reason(alias_matches, set(alias_hit_terms)) \
            if alias_hit_terms else None

        # Маршрутный уровень (retrieval v2): файл сматчен метаданными →
        # факты файла поднимаются в кандидаты. Буст ограничен и не
        # подменяет собственное совпадение факта, если оно сильнее.
        text_s = min(1.0, direct_text_s + alias_s * _ALIAS_TEXT_DISCOUNT)
        route_source: str | None = None
        boost_entry = route_boosts.get(_fact_source_key(fact.source_file))
        if boost_entry is not None and boost_entry[0] > text_s:
            text_s = boost_entry[0]
            route_source = boost_entry[1]

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
            reason=_compose_reason(
                matched_tags, title_hit, direct_text_s > 0, count,
                route_source, alias_fragment,
            ),
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


class ContextBackend(Protocol):
    def query_facts(self, query: FactQuery) -> list[StructuredFact]: ...


class ContextFeedback(Protocol):
    def usage_map(self) -> dict[str, dict]: ...
    def record_query(self, query_result_count: int, accessed_titles: list[str]): ...


def _delivery_base_dir(base_dir: Path | None) -> Path:
    """База знаний для нормализации source_file: аргумент → env → дефолт.

    Совпадает с разрешением server.py (CURATOR_BASE_DIR). Для сборки
    маршрутов путь только нормализует source_file — файлы не читаются.
    """
    if base_dir is not None:
        return Path(base_dir)
    return Path(os.getenv(
        "CURATOR_BASE_DIR",
        os.path.expanduser("~/Documents/AI/personal/learnings"),
    ))


def _build_delivery_routes(
    facts: list[StructuredFact], base_dir: Path | None
) -> tuple[KnowledgeRoute, ...]:
    """Маршруты для retrieval с отказоустойчивостью RouteBuildResult.

    Ошибки валидации видны человеку (stderr), но не ломают delivery:
    есть маршруты — используем частичные; нет — fact-only fallback.
    Пустой результат без ошибок — валидное состояние, не шумит.
    """
    try:
        result = build_routes(facts, _delivery_base_dir(base_dir))
    except Exception as e:
        print(f"curator: сборка knowledge routes не удалась: {e}",
              file=sys.stderr, flush=True)
        return ()
    for error in result.validation_errors:
        print(f"curator: knowledge routes: {error}", file=sys.stderr, flush=True)
    return result.routes


def fetch_context(
    trigger: str,
    backend: ContextBackend,
    feedback: ContextFeedback | None = None,
    *,
    types: list[str] | None = None,
    tags: list[str] | None = None,
    exclude_tags: list[str] | None = None,
    include_hypothesis: bool = False,
    limit: int = _DEFAULTS["limit"],
    token_budget: int = _DEFAULTS["token_budget"],
    relevance_threshold: float = _DEFAULTS["relevance_threshold"],
    now: float | None = None,
    base_dir: Path | None = None,
) -> list[ContextCard]:
    """Proactive delivery: текст задачи → ranked context cards (ADR 002).

    Доставленные карточки записываются в usage-телеметрию (вход ранжирования
    и сигнал качества для Epic #18). Только verified; deprecated исключён.

    Retrieval v2: маршруты собираются из тех же фактов (build_routes) и
    дают file-level кандидатов до переранжирования. Сбой сборки маршрутов
    не ломает доставку — fact-only fallback.
    """
    facts = backend.query_facts(FactQuery())
    usage = feedback.usage_map() if feedback else {}
    routes = _build_delivery_routes(facts, base_dir)
    cards = retrieve(
        ContextQuery(
            trigger=trigger,
            types=types or [],
            tags=tags or [],
            exclude_tags=exclude_tags or [],
            include_hypothesis=include_hypothesis,
            limit=limit,
            token_budget=token_budget,
            relevance_threshold=relevance_threshold,
        ),
        facts,
        usage=usage,
        now=now,
        routes=routes,
    )
    if cards and feedback is not None:
        feedback.record_query(len(cards), [c.title for c in cards])
    return cards


def fetch_context_safe(
    trigger: str,
    backend: ContextBackend,
    feedback: ContextFeedback | None = None,
    **options,
) -> list[ContextCard]:
    """Безопасная обёртка: ошибка retrieval → пустой список, не исключение.

    Инвариант proactive delivery: сбой базы не ломает сессию агента
    (ADR 002, п. «Отказ безопасности»).
    """
    try:
        return fetch_context(trigger, backend, feedback, **options)
    except Exception as e:
        print(f"curator: context delivery недоступен: {e}", file=sys.stderr, flush=True)
        return []
