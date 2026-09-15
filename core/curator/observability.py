"""Observability: JSONL лог всех improve-действий.

Каждая запись — одна строка JSON:
  {"ts": "2026-09-01T10:00:00", "action": "consolidate", "facts": ["A", "B"],
   "eval_before": 0.8, "eval_after": 0.9, "applied": true, "reason": ""}

Позволяет ответить на вопрос «какой урок к какому изменению привёл».
"""

import json
import os
import time
from pathlib import Path
from dataclasses import dataclass, field, asdict

from curator.state import env_path


@dataclass
class ObserveEvent:
    action: str
    applied: bool
    reason: str = ""
    facts: list[str] = field(default_factory=list)
    eval_before: float | None = None
    eval_after: float | None = None
    ts: str = ""

    def __post_init__(self):
        if not self.ts:
            self.ts = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())


class Observability:
    def __init__(self, path: str | None = None):
        # Тесты и демо изолируют лог через CURATOR_OBS_PATH — инвариант:
        # ничего, кроме прод-кода, не пишет в ~/.curator/ пользователя
        self.path = Path(path).expanduser() if path else env_path("CURATOR_OBS_PATH", "improve_events.jsonl")
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def log(self, event: ObserveEvent):
        d = asdict(event)
        d["ts"] = event.ts or time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")

    def _iter_events(self):
        """Все события лога; битые строки JSONL пропускаются — одна битая
        строка не должна валить improve-цикл после применения действий."""
        if not self.path.exists():
            return
        with open(self.path, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue

    def recent(self, n: int = 20) -> list[dict]:
        return list(self._iter_events())[-n:]

    def stats(self) -> dict:
        total = 0
        applied = 0
        skipped = 0
        by_action: dict[str, int] = {}
        for e in self._iter_events():
            total += 1
            if e.get("applied"):
                applied += 1
            else:
                skipped += 1
            action = e.get("action", "unknown")
            by_action[action] = by_action.get(action, 0) + 1
        return {"total_events": total, "applied": applied, "skipped": skipped, "by_action": by_action}
