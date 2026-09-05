"""Читатель реальных сессий OpenCode из opencode.db.

Извлекает диалоги для демо на реальных данных: 386 сессий, 16K сообщений.
Использование:
    from curator.session_reader import extract_opencode_sessions
    sessions = extract_opencode_sessions(n=5)  # → list[DemoSession]

Майнинг-профиль (полный текст, без обрезки демо-профиля):
    from curator.session_reader import list_opencode_sessions, read_opencode_session
    sessions = list_opencode_sessions(limit=100)      # метаданные для отбора
    full = read_opencode_session(session_id)           # полный транскрипт
"""

import sqlite3
import json
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass


@dataclass
class OpenCodeSession:
    name: str
    text: str
    messages: int
    tokens: int


@dataclass
class SessionMeta:
    """Метаданные сессии для отбора под майнинг (без транскрипта)."""
    id: str
    title: str
    directory: str
    created: str
    messages: int
    tokens: int


def extract_opencode_sessions(
    db_path: str = "~/.local/share/opencode/opencode.db",
    n: int = 5,
) -> list[OpenCodeSession]:
    db = Path(db_path).expanduser()
    if not db.exists():
        return []

    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row

    # Берём N самых насыщенных неархивированных сессий
    rows = conn.execute("""
        SELECT s.id, s.slug, s.title, COUNT(m.id) as msg_count,
               s.tokens_input, s.tokens_output
        FROM session s
        JOIN message m ON m.session_id = s.id
        WHERE s.time_archived IS NULL
        GROUP BY s.id
        HAVING msg_count >= 5
        ORDER BY msg_count DESC
        LIMIT ?
    """, [n]).fetchall()

    sessions = []
    for row in rows:
        messages = conn.execute("""
            SELECT m.id, m.data, p.data as part_data
            FROM message m
            JOIN part p ON p.message_id = m.id
            WHERE m.session_id = ?
            ORDER BY m.time_created, p.time_created
            LIMIT 100
        """, [row["id"]]).fetchall()

        lines = []
        for msg in messages:
            try:
                pdata = json.loads(msg["part_data"])
                if pdata.get("type") == "text" and pdata.get("text"):
                    role = _extract_role(msg)
                    text = pdata["text"].strip()
                    if text and len(text) > 10:
                        prefix = "пользователь:" if role == "user" else "агент:"
                        lines.append(f"{prefix} {text[:300]}")
            except (json.JSONDecodeError, KeyError):
                continue

        if len(lines) >= 5:
            sessions.append(OpenCodeSession(
                name=row["title"] or row["slug"],
                text="\n".join(lines[:30]),
                messages=row["msg_count"],
                tokens=(row["tokens_input"] or 0) + (row["tokens_output"] or 0),
            ))

    conn.close()
    return sessions


def _extract_role(msg) -> str:
    try:
        data = json.loads(msg["data"])
        role = data.get("role", "")
        if role:
            return role
    except (json.JSONDecodeError, KeyError):
        pass
    try:
        pdata = json.loads(msg["part_data"])
        role = pdata.get("role", "")
        if role:
            return role
    except (json.JSONDecodeError, KeyError):
        pass
    return "agent"


DEFAULT_DB = "~/.local/share/opencode/opencode.db"


def _ts_to_date(ts) -> str:
    """time_created → ISO-дата. opencode.db хранит миллисекунды (JS-стиль) —
    секунды и миллисекунды нормализуются единообразно."""
    if not ts:
        return ""
    if ts > 1e12:  # мс
        ts = ts / 1000
    return datetime.fromtimestamp(ts).isoformat()[:10]


def list_opencode_sessions(
    db_path: str = DEFAULT_DB,
    since: str | None = None,
    limit: int = 100,
    min_messages: int = 5,
    include_archived: bool = False,
) -> list[SessionMeta]:
    """Сессии с метаданными, свежие сверху — реестр для отбора под майнинг.

    since — ISO-дата («2026-06-01»): сессии, созданные не раньше неё.
    """
    db = Path(db_path).expanduser()
    if not db.exists():
        return []

    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row

    where = [] if include_archived else ["s.time_archived IS NULL"]
    where_sql = " AND ".join(where) if where else "1=1"

    rows = conn.execute(f"""
        SELECT s.id, s.title, s.directory, s.time_created,
               COUNT(m.id) as msg_count,
               s.tokens_input, s.tokens_output
        FROM session s
        JOIN message m ON m.session_id = s.id
        WHERE {where_sql}
        GROUP BY s.id
        HAVING msg_count >= ?
        ORDER BY s.time_created DESC
        LIMIT ?
    """, [min_messages, limit]).fetchall()

    sessions = []
    for row in rows:
        created = _ts_to_date(row["time_created"])
        if since and created < since:
            continue
        sessions.append(SessionMeta(
            id=row["id"],
            title=row["title"] or "",
            directory=row["directory"] or "",
            created=created,
            messages=row["msg_count"],
            tokens=(row["tokens_input"] or 0) + (row["tokens_output"] or 0),
        ))
    conn.close()
    return sessions


def read_opencode_session(
    session_id: str,
    db_path: str = DEFAULT_DB,
    max_messages: int = 400,
    max_chars_per_message: int = 4000,
) -> OpenCodeSession | None:
    """Полный транскрипт одной сессии — майнинг-профиль.

    Отличия от демо-профиля (extract_opencode_sessions): без обрезки до 300
    символов и 30 строк — текст-parts целиком (до max_chars_per_message),
    все сообщения (до max_messages). Транскрипт идёт на извлечение знаний
    агентом, обрезка там теряет факты.
    """
    db = Path(db_path).expanduser()
    if not db.exists():
        return None

    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row

    row = conn.execute(
        "SELECT id, title, tokens_input, tokens_output FROM session WHERE id = ?",
        [session_id],
    ).fetchone()
    if row is None:
        conn.close()
        return None

    messages = conn.execute("""
        SELECT m.id, m.data, p.data as part_data
        FROM message m
        JOIN part p ON p.message_id = m.id
        WHERE m.session_id = ?
        ORDER BY m.time_created, p.time_created
        LIMIT ?
    """, [session_id, max_messages]).fetchall()

    lines = []
    for msg in messages:
        try:
            pdata = json.loads(msg["part_data"])
            if pdata.get("type") == "text" and pdata.get("text"):
                role = _extract_role(msg)
                text = pdata["text"].strip()
                if text and len(text) > 10:
                    prefix = "пользователь:" if role == "user" else "агент:"
                    lines.append(f"{prefix} {text[:max_chars_per_message]}")
        except (json.JSONDecodeError, KeyError):
            continue

    conn.close()
    if not lines:
        return None
    return OpenCodeSession(
        name=row["title"] or session_id,
        text="\n\n".join(lines),
        messages=len(messages),
        tokens=(row["tokens_input"] or 0) + (row["tokens_output"] or 0),
    )