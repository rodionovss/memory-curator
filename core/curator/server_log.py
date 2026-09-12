"""Лог сервера: JSONL в $CURATOR_STATE_DIR/server.log.

Каждая строка — один вызов/этап:
  {"ts": "2026-08-25T10:00:00", "event": "session_capture", "stage": "analyze",
   "model": "...", "duration_ms": 1234, "num_facts": 3, "error": ""}

Зачем: диагностика таймаутов и ошибок MCP-сервера без правки вслепую.
"""

import json
import os
import time
from pathlib import Path

from curator.state import env_path


def _path() -> Path:
    return env_path("CURATOR_LOG_PATH", "server.log")


def log(event: str, **fields):
    try:
        p = _path()
        p.parent.mkdir(parents=True, exist_ok=True)
        rec = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
            "event": event,
        }
        rec.update(fields)
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass
