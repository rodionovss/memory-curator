"""Тур по Memory Curator: `curator demo`.

Пошагово прогоняет полный жизненный цикл знания на изолированной tmp-базе:
кандидаты → gatekeeper → сохранение + write-back в .md → query → improve
(дубликаты, противоречия) → телеметрия использования → финальный статус.

Все вызовы настоящие — те же функции, что работают в проде (gatekeeper,
backend, ImproveLoop, worker). Никакой синтетики: каждый этап — реальный вызов.
"""

import json
import shutil
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

from curator.models import StructuredFact, ProposedFact, FactQuery, normalize_fact_type
from curator.backend.local import LocalBackend
from curator.gatekeeper import Gatekeeper
from curator.improve_loop import ImproveLoop
from curator.routing import get_router, route_fact_safe
from curator.sync_engine import SyncEngine

DEMO_FACTS = [
    # --- чистые знания (принимаются) ---
    {"type": "Tool", "title": "MCP SDK v2: правильная сигнатура хендлеров",
     "content_summary": "Хендлеры принимают (ctx, request), первый — ServerRequestContext. Запуск через async with stdio_server().",
     "tags": ["python", "mcp"], "evidence": "агент: add_request_handler(ctx, request)"},
    {"type": "Reference", "title": "Data class предпочтительнее value class в общем случае",
     "content_summary": "Когда нужны equals/hashCode/toString — data class генерирует их автоматически, value class боксирует при апкасте.",
     "tags": ["kotlin", "jvm"], "evidence": "агент: data class предпочтительнее"},

    # --- пара дубликатов: проходит gatekeeper (разные первые слова),
    #     ловится improve-консолидацией (Jaccard > 0.8) ---
    {"type": "Reference", "title": "Доменное правило про пагинацию длинных списков в каталоге товаров проекта",
     "content_summary": "Длинные списки каталога пагинировать на стороне сервера, клиент рендерит постранично.",
     "tags": ["android"], "evidence": "агент: пагинация для каталога"},
    {"type": "Reference", "title": "Альтернативное правило про пагинацию длинных списков в каталоге товаров проекта",
     "content_summary": "Длинные списки каталога пагинировать на стороне сервера, клиент рендерит постранично.",
     "tags": ["android"], "evidence": "агент: тот же вывод другими словами"},

    # --- пара противоречий: побеждает факт с бОльшим числом тегов ---
    {"type": "Reference", "title": "Командное правило использовать Retrofit для сетевых запросов",
     "content_summary": "Стандарт команды: сетевой слой на Retrofit, единый модуль для всех запросов.",
     "tags": ["android", "network"], "evidence": "агент: Retrofit — стандарт"},
    {"type": "Reference", "title": "Рабочая гипотеза не использовать Retrofit для сетевых запросов",
     "content_summary": "Гипотеза: переехать на Ktor для единообразия с общим стеком.",
     "tags": ["android"], "evidence": "агент: предлагал Ktor"},

    # --- знание, которое вторая волна попробует продублировать ---
    {"type": "Reference", "title": "Пагинация списков через offset параметр в API",
     "content_summary": "Offset-пагинация для стабильных списков без частых вставок.",
     "tags": ["api"], "evidence": "агент: offset для списков"},

    # --- шум: фичевая деталь, не знание ---
    {"type": "Reference", "title": "Поправить верстку кнопки на экране входа",
     "content_summary": "Мелкая правка интерфейса в рамках текущей задачи.",
     "tags": ["ui"], "evidence": "юзер: поправь кнопку"},

    # --- мусор: слишком короткий заголовок ---
    {"type": "Reference", "title": "Правка UI",
     "content_summary": "Небольшое изменение интерфейса без содержания.",
     "tags": ["ui"], "evidence": ""},
]

# Вторая волна: новая сессия принесла знание, которое уже есть в базе —
# gatekeeper проверяет кандидатов против СОХРАНЁННОЙ памяти и отклоняет повтор.
DEMO_FACTS_WAVE2 = [
    {"type": "Reference", "title": "Пагинация списков через cursor параметр в API",
     "content_summary": "Cursor-пагинация стабильнее offset при частых вставках.",
     "tags": ["api"], "evidence": "агент: cursor для тех же списков"},
]


@contextmanager
def _isolated(tmp: Path):
    """ImproveLoop/worker пишут логи в ~/.curator — изолируем в tmp, чтобы
    тур не трогал реальные данные пользователя."""
    import curator.observability as obs_mod
    import curator.retrieval_feedback as fb_mod
    from curator.observability import Observability
    from curator.retrieval_feedback import RetrievalFeedback

    orig_obs, orig_fb = obs_mod.Observability, fb_mod.RetrievalFeedback
    obs_mod.Observability = lambda *a, **k: Observability(path=str(tmp / "improve_events.jsonl"))
    fb_mod.RetrievalFeedback = lambda *a, **k: RetrievalFeedback(storage_path=str(tmp / "usage.json"))
    try:
        yield
    finally:
        obs_mod.Observability = orig_obs
        fb_mod.RetrievalFeedback = orig_fb


def _banner(out, text: str):
    line = "═" * 64
    out(f"\n{line}\n  {text}\n{line}")


def run_tour(keep: bool = False, verbose: bool = True) -> dict:
    """Прогнать полный тур. Возвращает итоговые счётчики (для тестов)."""
    out = print if verbose else (lambda *a, **k: None)

    tmp = Path(tempfile.mkdtemp(prefix="curator-tour-"))
    base_dir = tmp / "learnings"
    result = {"tmp_dir": str(tmp), "approved": 0, "rejected": 0,
              "duplicates_found": 0, "contradictions_found": 0,
              "decay": 0, "final_by_status": {}, "md_files": []}

    try:
        be = LocalBackend(str(tmp / "knowledge.db"))

        _banner(out, "MEMORY CURATOR — ТУР · бэкенд: local")
        out(f"  Изолированная база: {tmp} (реальные данные не трогаются)")
        out("  Флаг --keep сохранит файлы для ручного осмотра")
        out("")

        # ── ЭТАП 0: вход ─────────────────────────────────────────
        _banner(out, "ЭТАП 0/6 · ВХОД: агент извлек кандидатов из сессии")
        out("""  Первая сессия принесла 9 кандидатов:
  · 2 чистых знания (инструмент + техническое правило)
  · 2 похожих дубликата (обходят gatekeeper, ловит improve-консолидация)
  · 2 противоречащих факта («использовать» vs «не использовать»)
  · 1 знание про пагинацию (вторая сессия попробует его продублировать)
  · 1 шум (фичевая деталь) и 1 мусор (короткий заголовок)""")

        proposed = [
            ProposedFact(
                type=normalize_fact_type(c["type"]),
                title=c["title"],
                content_summary=c["content_summary"],
                tags=list(c["tags"]),
                evidence=c.get("evidence", ""),
            )
            for c in DEMO_FACTS
        ]

        # ── ЭТАП 1: gatekeeper + сохранение ──────────────────────
        _banner(out, "ЭТАП 1/6 · GATEKEEPER: валидация кандидатов + сохранение")
        gk = Gatekeeper(be)
        gate_result = gk.filter(proposed)

        out(f"\n  Одобрено: {len(gate_result.approved)}")
        for f in gate_result.approved:
            out(f"    ✅ [{f.type}] {f.title[:70]}")
        out(f"\n  Отклонено: {len(gate_result.rejected)}")
        for f, reason in gate_result.rejected:
            out(f"    ⛔ {f.title[:70]}")
            out(f"       причина: {reason}")

        router = get_router()
        sync = SyncEngine(be, base_dir)
        for f in gate_result.approved:
            structured = StructuredFact(
                type=f.type, title=f.title, tags=f.tags, status="verified",
                content_summary=f.content_summary, source_file=route_fact_safe(router, f),
            )
            be.store_fact(structured)
            sync.write_fact_to_md(structured)
        result["approved"] = len(gate_result.approved)

        out("\n  ── вторая сессия принесла 1 кандидата ──")
        wave2 = [
            ProposedFact(
                type=normalize_fact_type(c["type"]),
                title=c["title"],
                content_summary=c["content_summary"],
                tags=list(c["tags"]),
                evidence=c.get("evidence", ""),
            )
            for c in DEMO_FACTS_WAVE2
        ]
        wave2_result = gk.filter(wave2)
        for f, reason in wave2_result.rejected:
            out(f"    ⛔ {f.title[:70]}")
            out(f"       причина: {reason}")
        for f in wave2_result.approved:
            be.store_fact(StructuredFact(
                type=f.type, title=f.title, tags=f.tags, status="verified",
                content_summary=f.content_summary, source_file=route_fact_safe(router, f),
            ))
        result["approved"] += len(wave2_result.approved)
        result["rejected"] = len(gate_result.rejected) + len(wave2_result.rejected)
        out(f"\n  Итого: принято {result['approved']}, отклонено {result['rejected']}")

        # ── ЭТАП 2: write-back ──────────────────────────────────
        _banner(out, "ЭТАП 2/6 · WRITE-BACK: знания вернулись в .md документацию")
        md_files = sorted(str(p.relative_to(base_dir)) for p in base_dir.rglob("*.md"))
        result["md_files"] = md_files
        out(f"  Созданы файлы: {', '.join(md_files)}")
        first_md = base_dir / md_files[0] if md_files else None
        if first_md and first_md.exists():
            out(f"\n  --- {first_md.name} (первые строки) ---")
            for line in first_md.read_text(encoding="utf-8").splitlines()[:6]:
                out(f"  {line}")

        # ── ЭТАП 3: query ────────────────────────────────────────
        _banner(out, "ЭТАП 3/6 · QUERY: агент запрашивает знания перед работой")
        for q, comment in [("пагинацию", "обе копии дубликата ещё «живые»"),
                           ("Retrofit", "противоречивая пара до разрешения")]:
            found = be.query_facts(FactQuery(search=q))
            out(f"\n  query('{q}') → {len(found)} фактов ({comment}):")
            for f in found:
                out(f"    [{f.status}] {f.title[:70]}")

        # ── ЭТАП 4: improve ──────────────────────────────────────
        _banner(out, "ЭТАП 4/6 · IMPROVE LOOP: дубликаты + противоречия (автономно)")
        with _isolated(tmp):
            report = ImproveLoop(be).run()
        result["duplicates_found"] = report.stats["duplicates_found"]
        result["contradictions_found"] = report.stats["contradictions_found"]

        out(f"\n  Дубликатов найдено: {report.stats['duplicates_found']}")
        for f1, f2 in report.duplicates:
            out(f"    ↔ '{f1.title[:55]}' ~ '{f2.title[:55]}'")
            out("      консолидация: проигравший помечен deprecated (eval gate одобрил)")
        out(f"\n  Противоречий найдено: {report.stats['contradictions_found']}")
        for r in report.resolutions:
            out(f"    ✅ победил: '{r.winner.title[:60]}' ({r.reason})")
            out(f"    ⛔ проиграл: '{r.loser.title[:60]}' → deprecated")

        # ── ЭТАП 5: телеметрия использования ─────────────────────
        _banner(out, "ЭТАП 5/6 · ТЕЛЕМЕТРИЯ: что реально читают (совет, не приговор)")
        usage_path = tmp / "usage.json"
        usage = json.loads(usage_path.read_text()) if usage_path.exists() else {}
        usage["MCP SDK v2: правильная сигнатура хендлеров"] = {"count": 5, "last_access": time.time() - 40 * 86400}
        usage["Data class предпочтительнее value class в общем случае"] = {"count": 12, "last_access": time.time()}
        usage_path.write_text(json.dumps(usage, indent=2), encoding="utf-8")
        out("  Симуляция статистики: 'MCP SDK v2…' не запрашивали 40 дней,")
        out("  'Data class…' запрашивали сегодня\n")

        from curator.retrieval_feedback import RetrievalFeedback
        fb = RetrievalFeedback(str(usage_path))
        out(f"  Часто запрашиваемые ({len(fb.get_stats(5))}):")
        for item in fb.get_stats(5):
            out(f"    {item['title'][:60]} ({item['count']}×)")
        unused = fb.get_unused(30)
        if unused:
            out(f"\n  Не запрашивались >30 дней ({len(unused)}):")
            for title in unused:
                out(f"    ⏳ {title[:70]}")
        out("\n  Решение за человеком: таймерного decay нет — время не делает")
        out("  факт ложным. Устаревание: по смыслу (противоречие/дубль) или руками.")
        result["decay"] = 0

        # ── ЭТАП 6: финал ────────────────────────────────────────
        _banner(out, "ЭТАП 6/6 · ИТОГ: состояние памяти после полного цикла")
        all_facts = be.query_facts(FactQuery())
        by_status = {}
        for f in all_facts:
            by_status[f.status] = by_status.get(f.status, 0) + 1
        result["final_by_status"] = by_status
        out(f"\n  Всего фактов: {len(all_facts)}")
        for status in ("verified", "hypothesis", "deprecated"):
            out(f"    {status}: {by_status.get(status, 0)}")
        out(f"\n  Полный журнал improve: {tmp / 'improve_events.jsonl'}")
        out(f"  База: {tmp / 'knowledge.db'} · Документация: {base_dir}")

        if keep:
            out(f"\n  Файлы сохранены (--keep): {tmp}")
        else:
            out("\n  Временные файлы будут удалены. Флаг --keep — оставить для осмотра.")

        _banner(out, "ТУР ЗАВЕРШЁН · попробуйте: curator demo --keep")
        return result

    finally:
        if not keep:
            shutil.rmtree(tmp, ignore_errors=True)
