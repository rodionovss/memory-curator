from pathlib import Path


def test_state_dir_is_single_default_for_runtime_files(tmp_path, monkeypatch):
    monkeypatch.setenv("CURATOR_STATE_DIR", str(tmp_path / ".curator"))
    monkeypatch.delenv("CURATOR_OBS_PATH", raising=False)
    monkeypatch.delenv("CURATOR_USAGE_PATH", raising=False)
    monkeypatch.delenv("CURATOR_LOG_PATH", raising=False)
    monkeypatch.delenv("IMPROVE_REPORT_DIR", raising=False)

    from curator import models
    from curator.backend.local import LocalBackend
    from curator.observability import Observability
    from curator.retrieval_feedback import RetrievalFeedback

    state_dir = tmp_path / ".curator"
    local = LocalBackend()

    try:
        assert Path(local._db_path) == state_dir / "knowledge.db"
        assert Observability().path == state_dir / "improve_events.jsonl"
        assert RetrievalFeedback().storage_path == state_dir / "usage.json"
        assert models._registry_path() == state_dir / "fact_types.json"
    finally:
        local._conn.close()


def test_component_overrides_win_over_state_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("CURATOR_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("CURATOR_OBS_PATH", str(tmp_path / "custom-observability.jsonl"))
    monkeypatch.setenv("CURATOR_USAGE_PATH", str(tmp_path / "custom-usage.json"))
    monkeypatch.setenv("CURATOR_LOG_PATH", str(tmp_path / "custom-server.log"))
    monkeypatch.setenv("IMPROVE_REPORT_DIR", str(tmp_path / "custom-reports"))

    from curator.observability import Observability
    from curator.retrieval_feedback import RetrievalFeedback

    assert Observability().path == tmp_path / "custom-observability.jsonl"
    assert RetrievalFeedback().storage_path == tmp_path / "custom-usage.json"


def test_default_state_dir_remains_home_curator(tmp_path, monkeypatch):
    monkeypatch.delenv("CURATOR_STATE_DIR", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))

    from curator.state import state_dir

    assert state_dir() == tmp_path / ".curator"


def test_configured_base_reads_state_config(tmp_path, monkeypatch):
    """База из state-конфига: env > ~/.curator/config.json (MCP-секций нет)."""
    import json

    monkeypatch.delenv("CURATOR_BASE_DIR", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    state = tmp_path / ".curator"
    state.mkdir()
    (state / "config.json").write_text(json.dumps(
        {"base_dir": str(tmp_path / "kb")}), encoding="utf-8")

    from curator import control

    assert control._configured_base_dir() == str(tmp_path / "kb")
    monkeypatch.setenv("CURATOR_BASE_DIR", "/env/wins")
    assert control._configured_base_dir() == "/env/wins", "env всегда выигрывает"
