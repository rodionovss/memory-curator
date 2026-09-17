"""Парсер транскрипта прогона из opencode.db изолированного home.

Схема та же, что читает curator.session_reader: session/message/part.
Извлекаем:
- tool calls (toolName + args) → события file read внутри kb/;
- tokens_input/tokens_output сессии.
"""

import json
import sqlite3
from pathlib import Path


def _extract_args(part_data: dict) -> dict:
    """args из обеих схем part: старой (toolInvocation) и новой (tool/state)."""
    inv = part_data.get("toolInvocation") or {}
    args = inv.get("args")
    if isinstance(args, dict):
        return args
    state = part_data.get("state") or {}
    inputs = state.get("input")
    return inputs if isinstance(inputs, dict) else {}


def parse_session_db(db_path: Path) -> dict:
    """Вернуть {session_id, tokens_input, tokens_output, tool_calls, texts}.

    Берёт последнюю (time_created max) сессию в базе изолированного home.
    """
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        session = conn.execute(
            "SELECT id, tokens_input, tokens_output FROM session "
            "ORDER BY time_created DESC LIMIT 1"
        ).fetchone()
        if session is None:
            return {"session_id": None, "tokens_input": 0, "tokens_output": 0,
                    "tool_calls": [], "texts": []}

        parts = conn.execute(
            "SELECT p.data FROM part p JOIN message m ON p.message_id = m.id "
            "WHERE m.session_id = ? ORDER BY p.time_created",
            [session["id"]],
        ).fetchall()

        tool_calls = []
        texts = []
        for row in parts:
            try:
                data = json.loads(row["data"])
            except (json.JSONDecodeError, TypeError):
                continue
            ptype = data.get("type")
            if ptype == "text" and data.get("text"):
                texts.append(data["text"])
            elif ptype == "tool-invocation":
                inv = data.get("toolInvocation") or {}
                if inv.get("state") == "result":
                    continue
                tool_calls.append({
                    "tool": inv.get("toolName", "?"),
                    "args": _extract_args(data),
                })
            elif ptype == "tool":
                tool_calls.append({
                    "tool": data.get("tool", "?"),
                    "args": _extract_args(data),
                })

        return {
            "session_id": session["id"],
            "tokens_input": session["tokens_input"] or 0,
            "tokens_output": session["tokens_output"] or 0,
            "tool_calls": tool_calls,
            "texts": texts,
        }
    finally:
        conn.close()


def kb_events(transcript: dict, ws: Path) -> list[dict]:
    """События навигации по базе знаний из tool calls.

    Считаем навигацией read/glob/grep, чей target указывает внутрь kb/.
    Чтения fixture-файлов — обычная работа, не память.
    """
    ws_prefix = str(ws) + "/"
    events = []
    for call in transcript["tool_calls"]:
        tool = call["tool"]
        args = call["args"]
        if tool == "read":
            target = args.get("filePath") or args.get("path") or ""
        elif tool in ("glob", "grep"):
            target = args.get("path") or ""
        else:
            continue
        abs_target = str(Path(target).expanduser())
        if not abs_target.startswith(ws_prefix):
            continue
        rel = abs_target[len(ws_prefix):]
        if rel.startswith("kb/"):
            events.append({
                "event": "index_read" if rel == "kb/index.md" else "source_file_read",
                "source": "file_read",
                "fact_id": _fact_id_of(rel),
                "path": rel,
            })
    return events


def _fact_id_of(rel_path: str) -> str | None:
    name = Path(rel_path).name
    if "-" in name:
        return name.split("-", 1)[0]
    return None
