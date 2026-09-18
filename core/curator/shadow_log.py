"""Телеметрия proactive delivery: локальный JSONL-лог shadow/inject событий.

Shadow-режим (ADR 002, Task 10): retrieval наблюдается на реальных
сессиях без доставки карточек — данные для решения о live A/B.
Приватность: сырой промпт не персистится никогда, только SHA-256 хэш;
лог локальный, в shared repository не попадает.

Событие (контракт Task 10):
  {"session_id": "...", "trigger_hash": "...", "mode": "shadow",
   "candidate_titles": ["..."], "scores": [0.8], "delivered": false,
   "silent": false, "latency_ms": 12, "source_files": ["session/tool.md"]}

Кандидаты идентифицируются по title (natural key) — row id из SQLite
в события не попадают. Запись под advisory flock; ротация 10 MB
(активный файл переименовывается с суффиксом-таймстампом).
"""

import hashlib
import json
import os
import sys
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from curator.delivery import ContextCard
from curator.state import env_path

if os.name != "nt":
    import fcntl

SHADOW_LOG_NAME = "delivery-shadow.jsonl"
# Ротация: тысячи событий между ротациями, активный файл остаётся greppable
ROTATE_BYTES = 10 * 1024 * 1024


def shadow_log_path() -> Path:
    """Путь лога: CURATOR_SHADOW_LOG_PATH или <state dir>/delivery-shadow.jsonl."""
    return env_path("CURATOR_SHADOW_LOG_PATH", SHADOW_LOG_NAME)


def trigger_hash(trigger: str) -> str:
    """SHA-256 сырого триггера: промпт не персистится, хэш — для дедупликации."""
    return hashlib.sha256(trigger.encode("utf-8")).hexdigest()


def _source_files(cards: Sequence[ContextCard]) -> list[str]:
    """Уникальные source_file кандидатов в порядке ранжирования (без None)."""
    seen: set[str] = set()
    files: list[str] = []
    for card in cards:
        if card.source_file and card.source_file not in seen:
            seen.add(card.source_file)
            files.append(card.source_file)
    return files


def build_event(
    trigger: str,
    cards: Sequence[ContextCard],
    *,
    mode: str,
    session_id: str | None,
    delivered: bool,
    latency_ms: int,
) -> dict:
    """Событие доставки по контракту Task 10 (natural key — title, без row id)."""
    return {
        "session_id": session_id,
        "trigger_hash": trigger_hash(trigger),
        "mode": mode,
        "candidate_titles": [c.title for c in cards],
        "scores": [c.score for c in cards],
        "delivered": delivered,
        "silent": not cards,
        "latency_ms": latency_ms,
        "source_files": _source_files(cards),
    }


def _rotated_path(log: Path) -> Path:
    """Имя ротации: <stem>.<таймстамп><suffix>; коллизия в одну секунду — счётчик."""
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    rotated = log.with_name(f"{log.stem}.{stamp}{log.suffix}")
    n = 1
    while rotated.exists():
        rotated = log.with_name(f"{log.stem}.{stamp}-{n}{log.suffix}")
        n += 1
    return rotated


def append_event(event: dict, *, path: Path | None = None, max_bytes: int | None = None) -> Path:
    """Одна строка JSONL под локом; ротация при размере >= max_bytes.

    Возвращает активный путь лога. OSError не глушится — высокоуровневый
    log_event решает, как реагировать. На Windows flock нет — append
    без лока (лучше усилие, чем молчаливый отказ).
    """
    log = Path(path) if path is not None else shadow_log_path()
    limit = ROTATE_BYTES if max_bytes is None else max_bytes
    log.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(event, ensure_ascii=False) + "\n"

    if os.name == "nt":
        with open(log, "a", encoding="utf-8") as f:
            f.write(line)
        return log

    lock_path = log.with_name(log.name + ".lock")
    with open(lock_path, "a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            if log.exists() and log.stat().st_size >= limit:
                os.replace(log, _rotated_path(log))
            with open(log, "a", encoding="utf-8") as f:
                f.write(line)
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
    return log


def log_event(
    trigger: str,
    cards: Sequence[ContextCard],
    *,
    mode: str,
    session_id: str | None,
    delivered: bool,
    latency_ms: int,
) -> None:
    """Записать событие доставки. Телеметрия не роняет вызвавший CLI."""
    try:
        append_event(build_event(
            trigger, cards, mode=mode, session_id=session_id,
            delivered=delivered, latency_ms=latency_ms,
        ))
    except Exception as e:
        print(f"curator: shadow-лог доставки недоступен: {e}",
              file=sys.stderr, flush=True)
