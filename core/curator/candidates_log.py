"""Телеметрия кандидатов знаний: что предложил агент, что сохранилось и почему отказано.

Каждый вызов capture (CLI save / MCP curator_session_capture) пишет одну строку JSONL:
  {"ts": "2026-09-05T10:00:00", "source": "mining", "session": "ses_abc",
   "proposed": 5, "saved": 3, "declined_by_human": false, "final_status": "hypothesis",
   "candidates": [{"title": "...", "type": "Reference", "decision": "rejected",
                   "reason": "Дубликат: ..."}]}

Отвечает на два вопроса:
  1. Точность извлечения: сколько из предложенного выжило и по каким причинам нет —
     карта «что докрутить в extraction».
  2. Прямая рука для эксперимента: доля отказов gatekeeper до/после обучения базы.
"""

import json
import os
import time
from pathlib import Path


def _path() -> Path:
    # Инвариант: тесты изолируют лог через CURATOR_CANDIDATES_PATH,
    # прод пишет в ~/.curator/ пользователя
    base = os.getenv("CURATOR_CANDIDATES_PATH", "~/.curator/candidates.jsonl")
    return Path(base).expanduser()


def log_capture(source: str, candidates, saved: int, final_status: str,
                session_id: str | None = None, declined_by_human: bool = False):
    """Записать один вызов capture.

    candidates — список (ProposedFact, decision, reason): decision "approved" | "rejected".
    Телеметрия не должна ронять capture — любая ошибка глушится.
    """
    try:
        entries = []
        for fact, decision, reason in candidates:
            entries.append({
                "title": fact.title,
                "type": fact.type,
                "decision": decision,
                "reason": reason or "",
            })
        rec = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
            "source": source,
            "session": session_id,
            "proposed": len(entries),
            "saved": saved,
            "declined_by_human": declined_by_human,
            "final_status": final_status,
            "candidates": entries,
        }
        p = _path()
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


def read_entries() -> list[dict]:
    """Все записи лога; битые строки JSONL пропускаются."""
    p = _path()
    if not p.exists():
        return []
    entries = []
    with open(p) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return entries


def precision_stats() -> dict:
    """Агрегация: предложено / сохранено / отказано, по причинам и источникам."""
    entries = read_entries()
    proposed = 0
    saved = 0
    rejected_by_gatekeeper = 0
    declined_by_human = 0
    by_reason: dict[str, int] = {}
    by_source: dict[str, int] = {}
    by_type: dict[str, int] = {}
    top_rejected: list[tuple[str, int]] = []
    rejected_titles: dict[str, int] = {}

    for e in entries:
        src = e.get("source", "unknown")
        by_source[src] = by_source.get(src, 0) + 1
        proposed += e.get("proposed", 0)
        saved += e.get("saved", 0)
        if e.get("declined_by_human"):
            declined_by_human += 1
        for c in e.get("candidates", []):
            if c.get("decision") == "rejected":
                rejected_by_gatekeeper += 1
                reason = c.get("reason", "без причины")
                # Причину gatekeeper вида "Дубликат: уже есть 'X'" агрегируем по классу
                key = reason.split(":")[0].strip() if reason else "без причины"
                by_reason[key] = by_reason.get(key, 0) + 1
                title = c.get("title", "?")
                rejected_titles[title] = rejected_titles.get(title, 0) + 1
            else:
                ftype = c.get("type", "unknown")
                by_type[ftype] = by_type.get(ftype, 0) + 1

    top_rejected = sorted(rejected_titles.items(), key=lambda x: x[1], reverse=True)[:10]
    precision = (saved / proposed * 100) if proposed else 0.0
    return {
        "calls": len(entries),
        "proposed": proposed,
        "saved": saved,
        "rejected_by_gatekeeper": rejected_by_gatekeeper,
        "declined_by_human": declined_by_human,
        "precision_pct": round(precision, 1),
        "by_reason": by_reason,
        "by_source": by_source,
        "by_type_approved": by_type,
        "top_rejected": top_rejected,
    }
