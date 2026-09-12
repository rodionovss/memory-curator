"""Контракт review -> approve -> complete для MCP capture tools."""

import asyncio
import json
from pathlib import Path

import pytest

import curator.server as server_mod
from curator.backend.local import LocalBackend
from curator.gatekeeper import Gatekeeper
from curator.models import FactQuery
from curator.retrieval_feedback import RetrievalFeedback


VALID_FACT = {
    "type": "Reference",
    "title": "JvmInline value class внутри sealed interface бесполезен",
    "content_summary": "Бокс неизбежен, data class предпочтительнее для доменных типов-обёрток.",
    "tags": ["kotlin", "jvm"],
    "evidence": "агент: бокс неизбежен в sealed иерархии",
}

VALID_FACT_2 = {
    "type": "Style",
    "title": "Коммиты только по явной просьбе пользователя",
    "content_summary": "Никогда не коммитить автоматически после изменений, только по /commit.",
    "tags": ["workflow", "git"],
}


def _write_map(root: Path) -> Path:
    for relative in ("docs/knowledge.md", "docs/history.md", "docs/readonly.md"):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# Existing\n", encoding="utf-8")
    map_path = root / "DOCUMENTATION-MAP.md"
    map_path.write_text(
        """---
topics:
  - name: knowledge
    watch_for: Устойчивые знания
    targets:
      - path: docs/knowledge.md
        captures: [knowledge, rules]
        mode: update
        instructions: Обнови существующий раздел
      - path: docs/readonly.md
        captures: [knowledge]
        mode: readonly
  - name: history
    watch_for: Исторические записи
    targets:
      - path: docs/history.md
        captures: [records]
        mode: append
---
""",
        encoding="utf-8",
    )
    return map_path


@pytest.fixture
def memory_server(monkeypatch, tmp_path):
    be = LocalBackend(":memory:")
    usage_path = tmp_path / "usage.json"
    monkeypatch.setattr(server_mod, "backend", be)
    monkeypatch.setattr(server_mod, "gatekeeper", Gatekeeper(be))
    monkeypatch.setattr(server_mod, "feedback", RetrievalFeedback(storage_path=str(usage_path)))
    monkeypatch.setattr(server_mod, "base_dir", tmp_path)
    monkeypatch.setenv("CURATOR_BASE_DIR", str(tmp_path))
    monkeypatch.setenv("CURATOR_MAP", str(_write_map(tmp_path)))
    monkeypatch.delenv("AUTO_MODE", raising=False)
    with server_mod._captures_lock:
        server_mod._pending_captures.clear()
    return be, usage_path


def _review(candidates):
    return json.loads(server_mod._session_capture({"candidates": candidates}))


def _approve(capture_id, selected):
    return json.loads(server_mod._capture_approve({
        "capture_id": capture_id,
        "selected_candidate_ids": selected,
    }))


def _complete(capture_id, placements):
    return json.loads(server_mod._capture_complete({
        "capture_id": capture_id,
        "placements": placements,
    }))


def _placement(candidate_id="fact_1", **overrides):
    placement = {
        "candidate_id": candidate_id,
        "topic": "knowledge",
        "target": "docs/knowledge.md",
        "capture": "knowledge",
        "canonical_file": "docs/knowledge.md",
        "changed_files": ["docs/knowledge.md"],
    }
    placement.update(overrides)
    return placement


class TestReview:
    def test_returns_json_preview_without_side_effects(self, memory_server, tmp_path):
        be, usage_path = memory_server

        out = _review([VALID_FACT, VALID_FACT_2])

        assert out["status"] == "needs_human_approval"
        assert out["capture_id"].startswith("cap_")
        assert [fact["candidate_id"] for fact in out["eligible"]] == ["fact_1", "fact_2"]
        assert out["eligible"][0]["evidence"] == VALID_FACT["evidence"]
        assert out["rejected"] == []
        assert be.query_facts(FactQuery()) == []
        assert not usage_path.exists()
        assert not (tmp_path / "session").exists()

    def test_auto_mode_and_legacy_auto_approve_are_ignored(self, memory_server, monkeypatch):
        be, _ = memory_server
        monkeypatch.setenv("AUTO_MODE", "true")

        out = json.loads(server_mod._session_capture({
            "candidates": [VALID_FACT],
            "auto_approve": True,
        }))

        assert out["status"] == "needs_human_approval"
        assert be.query_facts(FactQuery()) == []

    def test_source_file_is_not_part_of_reviewed_fact(self, memory_server):
        candidate = {**VALID_FACT, "source_file": "docs/knowledge.md"}
        out = _review([candidate])
        assert "source_file" not in out["eligible"][0]

    def test_rejected_contains_input_and_gatekeeper_errors(self, memory_server):
        broken = {**VALID_FACT, "title": ""}
        noisy = {**VALID_FACT, "title": "Поправить верстку кнопки на экране входа"}

        out = _review([broken, noisy, VALID_FACT_2])

        assert [fact["candidate_id"] for fact in out["eligible"]] == ["fact_3"]
        assert len(out["rejected"]) == 2
        assert "нет title" in out["rejected"][0]["reason"]
        assert "фичевую" in out["rejected"][1]["reason"]

    @pytest.mark.parametrize("candidate, reason", [
        ({key: value for key, value in VALID_FACT.items() if key != "type"}, "нет type"),
        ({**VALID_FACT, "tags": 1}, "tags должен быть массивом строк"),
        ({**VALID_FACT, "tags": ["kotlin", 1]}, "tags должен быть массивом строк"),
    ])
    def test_malformed_candidate_is_rejected_as_json(self, memory_server, candidate, reason):
        out = _review([candidate])
        assert out["eligible"] == []
        assert reason in out["rejected"][0]["reason"]

    def test_duplicate_title_in_same_batch_is_rejected(self, memory_server):
        duplicate = {**VALID_FACT, "content_summary": "Другая достаточно длинная формулировка того же факта."}

        out = _review([VALID_FACT, duplicate])

        assert [fact["candidate_id"] for fact in out["eligible"]] == ["fact_1"]
        assert "дублирует title" in out["rejected"][0]["reason"]

    def test_candidates_json_string_and_invalid_input_return_json(self, memory_server):
        assert _review(json.dumps([VALID_FACT]))["status"] == "needs_human_approval"
        out = json.loads(server_mod._session_capture({"candidates": "{not json"}))
        assert out["status"] == "error"

    def test_pending_capture_limit_is_100(self, memory_server):
        for index in range(101):
            candidate = {**VALID_FACT, "title": f"Устойчивый заголовок знания номер {index}"}
            _review([candidate])
        with server_mod._captures_lock:
            assert len(server_mod._pending_captures) == 100

    def test_confirmed_new_type_is_registered_but_not_saved(self, memory_server, monkeypatch, tmp_path):
        be, _ = memory_server
        monkeypatch.setenv("CURATOR_STATE_DIR", str(tmp_path / ".curator"))
        candidate = {
            "type": "Note",
            "title": "Заметка об инструменте multica",
            "content_summary": "Наблюдение после недели использования инструмента.",
            "tags": ["tools"],
            "new_type": True,
            "type_description": "Заметки об инструментах после практического использования",
        }

        out = _review([candidate])

        assert out["eligible"][0]["type"] == "Note"
        assert be.query_facts(FactQuery()) == []
        assert (tmp_path / ".curator" / "fact_types.json").is_file()


class TestApprove:
    def test_freezes_selected_subset_and_returns_manifest(self, memory_server, tmp_path, monkeypatch):
        candidates = [dict(VALID_FACT), dict(VALID_FACT_2)]
        reviewed = _review(candidates)
        candidates[0]["title"] = "Изменено после review"

        out = _approve(reviewed["capture_id"], ["fact_1"])

        assert out == {
            "status": "update_project_docs",
            "next_action": "curator-update-docs",
            "capture_id": reviewed["capture_id"],
            "base_dir": str(tmp_path.resolve()),
            "map_path": str((tmp_path / "DOCUMENTATION-MAP.md").resolve()),
            "facts": [{"candidate_id": "fact_1", **VALID_FACT}],
        }

        changed = _approve(reviewed["capture_id"], ["fact_2"])
        assert changed["status"] == "error"
        assert "зафиксирован" in changed["error"]

        cancelled = _approve(reviewed["capture_id"], [])
        assert cancelled["status"] == "error"
        assert "зафиксирован" in cancelled["error"]

        same = _approve(reviewed["capture_id"], ["fact_1"])
        assert same["facts"][0]["title"] == VALID_FACT["title"]

    def test_unknown_candidate_id_is_rejected(self, memory_server):
        reviewed = _review([VALID_FACT])
        out = _approve(reviewed["capture_id"], ["fact_404"])
        assert out["status"] == "error"

    def test_empty_selection_cancels_and_removes_capture(self, memory_server, monkeypatch):
        reviewed = _review([VALID_FACT])
        monkeypatch.delenv("CURATOR_MAP")
        assert _approve(reviewed["capture_id"], []) == {
            "status": "cancelled",
            "capture_id": reviewed["capture_id"],
        }
        assert _approve(reviewed["capture_id"], ["fact_1"])["status"] == "error"


class TestComplete:
    @pytest.mark.parametrize(
        ("topic", "target", "capture", "canonical_file"),
        [
            ("knowledge", "docs/knowledge.md", "knowledge", "docs/knowledge.md"),
            ("history", "docs/history.md", "records", "docs/history.md"),
        ],
    )
    def test_writable_placement_saves_canonical_source(
        self, memory_server, topic, target, capture, canonical_file
    ):
        be, usage_path = memory_server
        reviewed = _review([VALID_FACT])
        _approve(reviewed["capture_id"], ["fact_1"])

        out = _complete(reviewed["capture_id"], [_placement(
            topic=topic,
            target=target,
            capture=capture,
            canonical_file=canonical_file,
            changed_files=[canonical_file],
        )])

        assert out == {
            "status": "completed",
            "capture_id": reviewed["capture_id"],
            "saved": 1,
            "documents": [canonical_file],
        }
        facts = be.query_facts(FactQuery())
        assert len(facts) == 1
        assert facts[0].source_file == canonical_file
        assert VALID_FACT["title"] in json.loads(usage_path.read_text(encoding="utf-8"))
        assert _complete(reviewed["capture_id"], [])["status"] == "error"

    @pytest.mark.parametrize(
        ("overrides", "message"),
        [
            ({"topic": "missing"}, "topic/target"),
            ({"target": "docs/missing.md"}, "topic/target"),
            ({"capture": "records"}, "capture"),
            ({"target": "docs/readonly.md", "canonical_file": "docs/readonly.md",
              "changed_files": ["docs/readonly.md"]}, "readonly"),
            ({"changed_files": []}, "changed_files"),
            ({"changed_files": ["docs/history.md"]}, "canonical_file"),
            ({"canonical_file": "../outside.md", "changed_files": ["../outside.md"]}, "безопасным"),
            ({"canonical_file": "docs/not-created.md", "changed_files": ["docs/not-created.md"]}, "существовать"),
        ],
    )
    def test_invalid_placement_is_rejected_before_store(self, memory_server, overrides, message):
        be, _ = memory_server
        reviewed = _review([VALID_FACT])
        _approve(reviewed["capture_id"], ["fact_1"])

        out = _complete(reviewed["capture_id"], [_placement(**overrides)])

        assert out["status"] == "error"
        assert message in out["error"]
        assert be.query_facts(FactQuery()) == []

    def test_requires_exactly_one_placement_per_selected_fact(self, memory_server):
        reviewed = _review([VALID_FACT, VALID_FACT_2])
        _approve(reviewed["capture_id"], ["fact_1", "fact_2"])
        out = _complete(reviewed["capture_id"], [_placement("fact_1")])
        assert out["status"] == "error"
        assert "ровно один placement" in out["error"]

    def test_malformed_candidate_id_returns_json_error(self, memory_server):
        reviewed = _review([VALID_FACT])
        _approve(reviewed["capture_id"], ["fact_1"])
        out = _complete(reviewed["capture_id"], [_placement(candidate_id=[])])
        assert out["status"] == "error"

    def test_symlink_is_checked_by_resolved_project_path(self, memory_server, tmp_path):
        map_path = tmp_path / "DOCUMENTATION-MAP.md"
        map_path.write_text(
            "---\ntopics:\n  - name: docs\n    targets:\n"
            "      - path: docs/*.md\n        captures: [knowledge]\n        mode: update\n---\n",
            encoding="utf-8",
        )
        private = tmp_path / "private" / "secret.md"
        private.parent.mkdir()
        private.write_text("# Private\n", encoding="utf-8")
        link = tmp_path / "docs" / "link.md"
        try:
            link.symlink_to(private)
        except OSError:
            pytest.skip("symlink недоступен в этом окружении")
        reviewed = _review([VALID_FACT])
        _approve(reviewed["capture_id"], ["fact_1"])

        out = _complete(reviewed["capture_id"], [_placement(
            topic="docs",
            target="docs/*.md",
            canonical_file="docs/link.md",
            changed_files=["docs/link.md"],
        )])

        assert out["status"] == "error"
        assert "не совпадает" in out["error"]


def test_mcp_schema_exposes_three_step_capture_without_legacy_fields(memory_server):
    result = asyncio.run(server_mod.handle_list_tools(None, None))
    tools = {tool.name: tool for tool in result.tools}

    capture_schema = tools["curator_session_capture"].input_schema
    candidate_properties = capture_schema["properties"]["candidates"]["items"]["properties"]
    assert "auto_approve" not in capture_schema["properties"]
    assert "source_file" not in candidate_properties
    assert {"curator_capture_approve", "curator_capture_complete"} <= tools.keys()
    assert tools["curator_session_capture"].output_schema["required"] == ["status"]


def test_capture_tool_returns_structured_content(memory_server):
    result = asyncio.run(server_mod.handle_call_tool(None, {
        "params": {
            "name": "curator_session_capture",
            "arguments": {"candidates": [VALID_FACT]},
        },
    }))

    assert result.structured_content["status"] == "needs_human_approval"
    assert json.loads(result.content[0].text) == result.structured_content
