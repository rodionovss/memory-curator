"""Тесты майнинг-профиля session_reader: list_opencode_sessions / read_opencode_session.

Фикстурная база повторяет схему opencode.db (session/message/part) — без чтения
реального архива пользователя.
"""

import json
import sqlite3
import time

import pytest

from curator.session_reader import list_opencode_sessions, read_opencode_session


def _make_db(tmp_path):
    db = tmp_path / "opencode.db"
    conn = sqlite3.connect(str(db))
    conn.executescript("""
        CREATE TABLE session (
            id text PRIMARY KEY, project_id text NOT NULL, parent_id text,
            slug text NOT NULL, directory text NOT NULL, title text NOT NULL,
            version text NOT NULL, share_url text, summary_additions integer,
            summary_deletions integer, summary_files integer, summary_diffs text,
            revert text, permission text, time_created integer NOT NULL,
            time_updated integer NOT NULL, time_compacting integer, time_archived integer,
            workspace_id text, path text, agent text, model text, cost real DEFAULT 0 NOT NULL,
            tokens_input integer DEFAULT 0 NOT NULL, tokens_output integer DEFAULT 0 NOT NULL,
            tokens_reasoning integer DEFAULT 0 NOT NULL, tokens_cache_read integer DEFAULT 0 NOT NULL,
            tokens_cache_write integer DEFAULT 0 NOT NULL, metadata text
        );
        CREATE TABLE message (
            id text PRIMARY KEY, session_id text NOT NULL,
            time_created integer NOT NULL, time_updated integer NOT NULL,
            data text NOT NULL
        );
        CREATE TABLE part (
            id text PRIMARY KEY, message_id text NOT NULL, session_id text NOT NULL,
            time_created integer NOT NULL, time_updated integer NOT NULL,
            data text NOT NULL
        );
    """)
    return conn


def _insert_session(conn, sid, title, directory, created_ts, messages,
                    archived=None, tokens=(100, 200)):
    """messages — list[(role, text, part_type)] — part_type != 'text' фильтруется."""
    conn.execute(
        "INSERT INTO session (id, project_id, slug, directory, title, version,"
        " time_created, time_updated, time_archived, tokens_input, tokens_output)"
        " VALUES (?, 'p', ?, ?, ?, 'v', ?, ?, ?, ?, ?)",
        (sid, sid, directory, title, created_ts, created_ts, archived,
         tokens[0], tokens[1]),
    )
    for i, (role, text, part_type) in enumerate(messages):
        mid = f"{sid}-m{i}"
        conn.execute(
            "INSERT INTO message (id, session_id, time_created, time_updated, data)"
            " VALUES (?, ?, ?, ?, ?)",
            (mid, sid, created_ts + i, created_ts + i,
             json.dumps({"role": role})),
        )
        conn.execute(
            "INSERT INTO part (id, message_id, session_id, time_created, time_updated, data)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (f"{mid}-p", mid, sid, created_ts + i, created_ts + i,
             json.dumps({"type": part_type, "text": text})),
        )


NOW = int(time.time())
DAY = 86400


@pytest.fixture
def db(tmp_path):
    conn = _make_db(tmp_path)
    # Две нормальные сессии (ses_a проходит дефолтный min_messages=5),
    # одна архивная, одна мелкая
    _insert_session(conn, "ses_a", "Compose миграция", "/proj/goldapple", NOW - DAY, [
        ("user", "сделай экран корзины на Compose", "text"),
        ("agent", "ок, делаю через MVI паттерн проекта", "text"),
        ("user", "не забудь StateFlow", "text"),
        ("agent", "готово, использовал StateFlow", "text"),
        ("user", "теперь добави обработку ошибок", "text"),
        ("agent", "сделал через Loading/Error/Content", "text"),
    ])
    _insert_session(conn, "ses_b", "Старая сессия про пагинацию", "/proj/other", NOW - 90 * DAY, [
        ("user", "какую пагинацию выбрать", "text"),
        ("agent", "cursor-based для стримов, offset для стабильных списков", "text"),
        ("user", "tool output", "tool"),
    ], tokens=(50, 60))
    _insert_session(conn, "ses_arch", "Архив", "/proj/x", NOW - DAY, [
        ("user", "запись 1", "text"),
        ("user", "запись 2", "text"),
    ], archived=NOW)
    _insert_session(conn, "ses_small", "Мелкая", "/proj/x", NOW - DAY, [
        ("user", "всего одно сообщение", "text"),
    ])
    conn.commit()
    conn.close()
    return tmp_path / "opencode.db"


class TestListSessions:
    def test_lists_active_sessions_newest_first(self, db):
        sessions = list_opencode_sessions(db_path=str(db))
        ids = [s.id for s in sessions]
        assert ids == ["ses_a"]  # свежая неархивная с 6 сообщениями
        # ses_arch скрыта (архив), ses_small скрыта (1 сообщение < min_messages=5),
        # ses_b скрыта (3 сообщения < min_messages=5)

    def test_min_messages_threshold(self, db):
        # С порогом 1 видны обе неархивные содержательные сессии
        ids = [s.id for s in list_opencode_sessions(db_path=str(db), min_messages=1)]
        assert "ses_b" in ids
        assert "ses_arch" not in ids

    def test_since_filters_old_sessions(self, db):
        sessions = list_opencode_sessions(
            db_path=str(db), since=time.strftime("%Y-%m-%d", time.localtime(NOW - 30 * DAY)),
            min_messages=1, include_archived=True)
        ids = [s.id for s in sessions]
        assert "ses_a" in ids
        assert "ses_b" not in ids  # 90 дней назад — за пределами since

    def test_metadata_fields(self, db):
        sessions = list_opencode_sessions(db_path=str(db), min_messages=1)
        s = next(x for x in sessions if x.id == "ses_a")
        assert s.title == "Compose миграция"
        assert s.directory == "/proj/goldapple"
        assert s.messages == 6
        assert s.tokens == 300

    def test_missing_db_returns_empty(self, tmp_path):
        assert list_opencode_sessions(db_path=str(tmp_path / "none.db")) == []

    def test_millisecond_timestamps_handled(self, db):
        # opencode.db хранит time_created в миллисекундах (JS-стиль)
        conn = sqlite3.connect(str(db))
        conn.execute(
            "INSERT INTO session (id, project_id, slug, directory, title, version,"
            " time_created, time_updated)"
            " VALUES ('ses_ms', 'p', 'ses_ms', '/proj', 'Мс-сессия', 'v', ?, ?)",
            (NOW * 1000, NOW * 1000))
        for i in range(3):
            conn.execute(
                "INSERT INTO message (id, session_id, time_created, time_updated, data)"
                " VALUES ('ses_ms-m%d', 'ses_ms', ?, ?, ?)" % i,
                (NOW * 1000 + i, NOW * 1000 + i, json.dumps({"role": "user"})))
            conn.execute(
                "INSERT INTO part (id, message_id, session_id, time_created, time_updated, data)"
                " VALUES ('ses_ms-m%d-p', 'ses_ms-m%d', 'ses_ms', ?, ?, ?)" % (i, i),
                (NOW * 1000 + i, NOW * 1000 + i,
                 json.dumps({"type": "text", "text": f"мс сообщение {i}"})))
        conn.commit()
        conn.close()

        sessions = list_opencode_sessions(db_path=str(db), min_messages=1)
        s = next(x for x in sessions if x.id == "ses_ms")
        assert s.created  # не упало и не «год 58645»
        assert len(s.created) == 10


class TestReadSession:
    def test_full_text_not_truncated_at_300(self, db):
        long_text = "x" * 900
        conn = sqlite3.connect(str(db))
        conn.execute(
            "INSERT INTO message (id, session_id, time_created, time_updated, data)"
            " VALUES ('ses_a-m9', 'ses_a', ?, ?, ?)",
            (NOW, NOW, json.dumps({"role": "agent"})))
        conn.execute(
            "INSERT INTO part (id, message_id, session_id, time_created, time_updated, data)"
            " VALUES ('ses_a-m9-p', 'ses_a-m9', 'ses_a', ?, ?, ?)",
            (NOW, NOW, json.dumps({"type": "text", "text": long_text})))
        conn.commit()
        conn.close()

        session = read_opencode_session("ses_a", db_path=str(db))
        assert session is not None
        assert "x" * 900 in session.text  # демо-профиль обрезал бы до 300

    def test_roles_prefixed_and_tool_parts_skipped(self, db):
        session = read_opencode_session("ses_b", db_path=str(db))
        assert "пользователь: какую пагинацию" in session.text
        assert "агент: cursor-based" in session.text
        assert "tool output" not in session.text  # не-text parts не попадают в транскрипт

    def test_unknown_session_returns_none(self, db):
        assert read_opencode_session("ses_none", db_path=str(db)) is None

    def test_missing_db_returns_none(self, tmp_path):
        assert read_opencode_session("ses_a", db_path=str(tmp_path / "none.db")) is None
