"""Offline outbox: отложенные записи для xmemory.

Когда xmemory недоступна (сеть/VPN/5xx), факты пишутся в локальную БД
и ставятся в очередь сюда. При восстановлении `curator sync` пушит
их в xmemory. Идемпотентно по title (UPSERT), попытки считаются.
"""

import json
import os
import sqlite3
import threading
from pathlib import Path

from curator.models import StructuredFact
from curator.state import state_path


class Outbox:
    def __init__(self, path: str | os.PathLike | None = None):
        self._path = state_path("outbox.db") if path is None else Path(path).expanduser()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        # Сериализация доступа к одному соединению: reachable из to_thread
        # (xmemory-fallback при конкурентных MCP-вызовах)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self._path, check_same_thread=False)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS outbox (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL UNIQUE,
                fact_json TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now')),
                synced_at TEXT
            )
        """)
        self._conn.commit()

    def enqueue(self, fact: StructuredFact) -> None:
        payload = {
            "type": fact.type, "title": fact.title, "tags": fact.tags,
            "status": fact.status, "content_summary": fact.content_summary,
            "source_file": fact.source_file, "source_session": fact.source_session,
        }
        with self._lock:
            self._conn.execute(
                "INSERT INTO outbox (title, fact_json) VALUES (?, ?) "
                "ON CONFLICT(title) DO UPDATE SET fact_json=excluded.fact_json, synced_at=NULL",
                (fact.title, json.dumps(payload, ensure_ascii=False)),
            )
            self._conn.commit()

    def pending(self) -> list[tuple[int, StructuredFact]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, fact_json FROM outbox WHERE synced_at IS NULL ORDER BY id"
            ).fetchall()
        result = []
        for row_id, raw in rows:
            d = json.loads(raw)
            result.append((row_id, StructuredFact(
                type=d.get("type", "Reference"), title=d["title"],
                tags=d.get("tags", []), status=d.get("status", "verified"),
                content_summary=d.get("content_summary", ""),
                source_file=d.get("source_file"), source_session=d.get("source_session"),
            )))
        return result

    def mark_synced(self, row_id: int) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE outbox SET synced_at = datetime('now') WHERE id = ?", (row_id,)
            )
            self._conn.commit()

    def fail(self, row_id: int) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE outbox SET attempts = attempts + 1 WHERE id = ?", (row_id,)
            )
            self._conn.commit()

    def count(self) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM outbox WHERE synced_at IS NULL"
            ).fetchone()
        return int(row[0])
