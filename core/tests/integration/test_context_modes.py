"""Контракт режимов CURATOR_DELIVERY_MODE для CLI `curator context` (Task 10).

`curator context` — транспорт плагина OpenCode (ADR 002). Режимы читает
Python CLI, не плагин: off (default) — пустой контракт без retrieval;
shadow — retrieval + локальное событие, карточки не возвращаются;
inject — событие + возврат карточек.

Инварианты: сырой промпт не персистится (только SHA-256 хэш), кандидаты
идентифицируются по title (natural key, без row id), сбой retrieval не
роняет CLI, usage-телеметрия не пишется (feedback=None — proactive
доставка ≠ ручной доступ), запись под локом с ротацией 10 MB.
"""

import hashlib
import json
import os
import re
import threading
from pathlib import Path

import pytest

import curator.control as control_mod
from curator import shadow_log
from curator.backend.local import LocalBackend
from curator.delivery import ContextCard
from curator.models import StructuredFact

TRIGGER = "хендлеры MCP"


def _fact(title="Хендлеры MCP", source_file="session/tool.md"):
    return StructuredFact(
        type="Reference", title=title, tags=["mcp"], status="verified",
        content_summary="Знание про хендлеры и сигнатуры MCP-сервера.",
        source_file=source_file,
    )


def _backend(tmp_path, *facts):
    be = LocalBackend(str(tmp_path / "db.db"))
    for fact in facts:
        be.store_fact(fact)
    return be


class _Boom:
    """Backend-детектор: retrieval в off-режиме не должен происходить."""

    def query_facts(self, query):
        raise AssertionError("off не должен трогать retrieval")


class _BrokenBackend:
    def query_facts(self, query):
        raise RuntimeError("db corrupted")


def _run(capsys, monkeypatch, tmp_path, backend, *, mode=None, session="ses_test",
         trigger=TRIGGER):
    """cmd_context в изолированном окружении → (parsed stdout, путь лога)."""
    log = tmp_path / "shadow.jsonl"
    monkeypatch.setenv("CURATOR_SHADOW_LOG_PATH", str(log))
    if mode is None:
        monkeypatch.delenv("CURATOR_DELIVERY_MODE", raising=False)
    else:
        monkeypatch.setenv("CURATOR_DELIVERY_MODE", mode)
    if session is None:
        monkeypatch.delenv("CURATOR_SESSION_ID", raising=False)
    else:
        monkeypatch.setenv("CURATOR_SESSION_ID", session)
    monkeypatch.setattr(control_mod, "_make_backend", lambda: backend)
    control_mod.cmd_context([trigger])
    return json.loads(capsys.readouterr().out), log


def _events(log: Path) -> list[dict]:
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line.strip()]


class TestOffMode:
    def test_дефолт_off_без_retrieval(self, capsys, monkeypatch, tmp_path):
        result, log = _run(capsys, monkeypatch, tmp_path, _Boom(), mode=None)
        assert result == {"cards": [], "count": 0}
        assert not log.exists(), "off не пишет событий"

    def test_явный_off(self, capsys, monkeypatch, tmp_path):
        result, log = _run(capsys, monkeypatch, tmp_path, _Boom(), mode="off")
        assert result == {"cards": [], "count": 0}
        assert not log.exists()

    def test_неизвестный_режим_failsafe(self, capsys, monkeypatch, tmp_path):
        result, log = _run(capsys, monkeypatch, tmp_path, _Boom(), mode="banana")
        assert result == {"cards": [], "count": 0}
        assert not log.exists(), "опечатка в режиме — безопасный off, не inject"


class TestShadowMode:
    def test_карточки_не_возвращаются_событие_пишется(self, capsys, monkeypatch, tmp_path):
        be = _backend(tmp_path, _fact())
        result, log = _run(capsys, monkeypatch, tmp_path, be, mode="shadow")
        assert result == {"cards": [], "count": 0}, "shadow никогда не возвращает карточки"

        events = _events(log)
        assert len(events) == 1
        event = events[0]
        assert set(event) == {
            "session_id", "trigger_hash", "mode", "candidate_titles", "scores",
            "delivered", "silent", "latency_ms", "source_files",
        }
        assert event["mode"] == "shadow"
        assert event["candidate_titles"] == ["Хендлеры MCP"]
        assert event["scores"] and isinstance(event["scores"][0], float)
        assert event["delivered"] is False
        assert event["silent"] is False
        assert event["source_files"] == ["session/tool.md"]
        assert event["session_id"] == "ses_test"
        assert isinstance(event["latency_ms"], int) and event["latency_ms"] >= 0

    def test_хэш_вместо_сырого_промпта(self, capsys, monkeypatch, tmp_path):
        secret = "секретная_строка_промпта_42"
        trigger = f"хендлеры MCP {secret}"
        be = _backend(tmp_path, _fact())
        result, log = _run(capsys, monkeypatch, tmp_path, be, mode="shadow", trigger=trigger)

        raw = log.read_text(encoding="utf-8")
        assert secret not in raw, "сырой промпт не персистится никогда"
        assert TRIGGER not in raw
        event = _events(log)[0]
        assert event["trigger_hash"] == hashlib.sha256(trigger.encode("utf-8")).hexdigest()

    def test_пустой_retrieval_молчит(self, capsys, monkeypatch, tmp_path):
        be = _backend(tmp_path)  # база без подходящих фактов
        result, log = _run(capsys, monkeypatch, tmp_path, be, mode="shadow")
        assert result == {"cards": [], "count": 0}
        event = _events(log)[0]
        assert event["silent"] is True
        assert event["candidate_titles"] == []
        assert event["delivered"] is False

    def test_сбой_retrieval_не_роняет_cli(self, capsys, monkeypatch, tmp_path):
        result, log = _run(capsys, monkeypatch, tmp_path, _BrokenBackend(), mode="shadow")
        assert result == {"cards": [], "count": 0}
        assert not log.exists(), "сбой retrieval — не наблюдение, событие не пишется"

    @pytest.mark.parametrize("mode", ["shadow", "inject"])
    def test_usage_телеметрия_не_пишется(self, capsys, monkeypatch, tmp_path, mode):
        be = _backend(tmp_path, _fact())
        _run(capsys, monkeypatch, tmp_path, be, mode=mode)
        usage = Path(os.environ["CURATOR_USAGE_PATH"])
        assert not usage.exists(), \
            "proactive доставка ≠ ручной доступ: fetch_context(feedback=None)"


class TestInjectMode:
    def test_карточки_возвращаются_и_событие_пишется(self, capsys, monkeypatch, tmp_path):
        be = _backend(tmp_path, _fact())
        result, log = _run(capsys, monkeypatch, tmp_path, be, mode="inject")
        assert result["count"] == 1
        assert result["cards"][0]["title"] == "Хендлеры MCP"
        event = _events(log)[0]
        assert event["mode"] == "inject"
        assert event["delivered"] is True
        assert event["silent"] is False

    def test_пустой_retrieval_инжект(self, capsys, monkeypatch, tmp_path):
        be = _backend(tmp_path)
        result, log = _run(capsys, monkeypatch, tmp_path, be, mode="inject")
        assert result == {"cards": [], "count": 0}
        event = _events(log)[0]
        assert event["delivered"] is False
        assert event["silent"] is True

    def test_сбой_retrieval_не_роняет_cli(self, capsys, monkeypatch, tmp_path):
        result, log = _run(capsys, monkeypatch, tmp_path, _BrokenBackend(), mode="inject")
        assert result == {"cards": [], "count": 0}


class TestModeSwitching:
    def test_переключение_режимов_в_одном_процессе(self, capsys, monkeypatch, tmp_path):
        be = _backend(tmp_path, _fact())
        log = tmp_path / "shadow.jsonl"
        monkeypatch.setenv("CURATOR_SHADOW_LOG_PATH", str(log))
        monkeypatch.setenv("CURATOR_SESSION_ID", "ses_switch")
        monkeypatch.setattr(control_mod, "_make_backend", lambda: be)

        monkeypatch.setenv("CURATOR_DELIVERY_MODE", "off")
        control_mod.cmd_context([TRIGGER])
        off = json.loads(capsys.readouterr().out)

        monkeypatch.setenv("CURATOR_DELIVERY_MODE", "shadow")
        control_mod.cmd_context([TRIGGER])
        shadow = json.loads(capsys.readouterr().out)

        monkeypatch.setenv("CURATOR_DELIVERY_MODE", "inject")
        control_mod.cmd_context([TRIGGER])
        inject = json.loads(capsys.readouterr().out)

        assert off["cards"] == []
        assert shadow["cards"] == []
        assert inject["count"] == 1
        modes = [e["mode"] for e in _events(log)]
        assert modes == ["shadow", "inject"], "off не пишет событий; смена режима видна сразу"


class TestLogPath:
    def test_дефолт_в_state_dir(self, tmp_path, monkeypatch):
        monkeypatch.delenv("CURATOR_SHADOW_LOG_PATH", raising=False)
        monkeypatch.setenv("CURATOR_STATE_DIR", str(tmp_path / "state"))
        assert shadow_log.shadow_log_path() == tmp_path / "state" / "delivery-shadow.jsonl"

    def test_env_переопределяет(self, tmp_path, monkeypatch):
        custom = tmp_path / "custom" / "events.jsonl"
        monkeypatch.setenv("CURATOR_SHADOW_LOG_PATH", str(custom))
        assert shadow_log.shadow_log_path() == custom


class TestBuildEvent:
    def _card(self, title="T", source_file="x.md", score=0.5):
        return ContextCard(title=title, summary="s", tags=["a"], type="Reference",
                           status="verified", source_file=source_file, score=score, reason="r")

    def test_контракт_события(self):
        event = shadow_log.build_event(
            "триггер", [self._card()], mode="shadow",
            session_id="ses_1", delivered=False, latency_ms=7,
        )
        assert event == {
            "session_id": "ses_1",
            "trigger_hash": hashlib.sha256("триггер".encode("utf-8")).hexdigest(),
            "mode": "shadow",
            "candidate_titles": ["T"],
            "scores": [0.5],
            "delivered": False,
            "silent": False,
            "latency_ms": 7,
            "source_files": ["x.md"],
        }

    def test_кандидаты_по_title_без_row_id(self):
        event = shadow_log.build_event(
            "триггер", [self._card(), self._card(title="T2")], mode="shadow",
            session_id="ses_1", delivered=False, latency_ms=7,
        )
        assert event["candidate_titles"] == ["T", "T2"], "natural key — title"
        assert "id" not in event and "fact_id" not in event

    def test_дубликаты_source_file_схлопываются(self):
        event = shadow_log.build_event(
            "триггер", [self._card(), self._card(title="T2")], mode="shadow",
            session_id="ses_1", delivered=False, latency_ms=7,
        )
        assert event["source_files"] == ["x.md"]

    def test_карточка_без_source_file(self):
        event = shadow_log.build_event(
            "триггер", [self._card(source_file=None)], mode="shadow",
            session_id="ses_1", delivered=False, latency_ms=7,
        )
        assert event["source_files"] == []


class TestRotation:
    def test_ротация_по_размеру(self, tmp_path, monkeypatch):
        monkeypatch.setattr(shadow_log, "ROTATE_BYTES", 1)
        log = tmp_path / "shadow.jsonl"
        shadow_log.append_event({"n": 1}, path=log)
        shadow_log.append_event({"n": 2}, path=log)

        rotated = [p for p in tmp_path.glob("shadow.*.jsonl")]
        assert len(rotated) == 1
        lines = rotated[0].read_text(encoding="utf-8").strip().splitlines()
        assert [json.loads(l)["n"] for l in lines] == [1], "ротация уносит старое содержимое"
        current = log.read_text(encoding="utf-8").strip().splitlines()
        assert [json.loads(l)["n"] for l in current] == [2]

    def test_имя_ротации_с_таймстампом(self, tmp_path, monkeypatch):
        monkeypatch.setattr(shadow_log, "ROTATE_BYTES", 1)
        log = tmp_path / "shadow.jsonl"
        shadow_log.append_event({"n": 1}, path=log)
        shadow_log.append_event({"n": 2}, path=log)
        rotated = next(p for p in tmp_path.glob("shadow.*.jsonl"))
        assert re.fullmatch(r"shadow\.\d{8}T\d{6}(-\d+)?\.jsonl", rotated.name), \
            "суффикс — таймстамп, не перезапись"

    def test_предел_не_достигнут_без_ротации(self, tmp_path, monkeypatch):
        monkeypatch.setattr(shadow_log, "ROTATE_BYTES", 10 * 1024 * 1024)
        log = tmp_path / "shadow.jsonl"
        shadow_log.append_event({"n": 1}, path=log)
        shadow_log.append_event({"n": 2}, path=log)
        assert not list(tmp_path.glob("shadow.*.jsonl"))
        assert len(log.read_text(encoding="utf-8").strip().splitlines()) == 2


class TestLocking:
    def test_конкурентные_дописывания_не_теряются(self, tmp_path):
        log = tmp_path / "shadow.jsonl"

        def worker(i):
            for j in range(10):
                shadow_log.append_event({"worker": i, "j": j}, path=log)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        lines = [json.loads(l) for l in log.read_text(encoding="utf-8").splitlines() if l.strip()]
        assert len(lines) == 80, "flock сериализует аппенды — потерь и склеек нет"
        assert len({(l["worker"], l["j"]) for l in lines}) == 80


class TestLogEventSafe:
    def test_log_event_глотает_ошибки_записи(self, tmp_path, monkeypatch, capsys):
        log = tmp_path / "subdir" / "shadow.jsonl"
        monkeypatch.setattr(shadow_log, "shadow_log_path", lambda: log)

        def boom(event, **kwargs):
            raise OSError("disk full")

        monkeypatch.setattr(shadow_log, "append_event", boom)
        shadow_log.log_event(
            "триггер", [], mode="shadow", session_id="ses_1",
            delivered=False, latency_ms=1,
        )
        assert "shadow" in capsys.readouterr().err, "сбой телеметрии виден в stderr, но не валит CLI"
