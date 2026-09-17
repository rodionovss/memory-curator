from pathlib import Path


def test_state_dir_is_single_default_for_runtime_files(tmp_path, monkeypatch):
    monkeypatch.setenv("CURATOR_STATE_DIR", str(tmp_path / ".curator"))
    monkeypatch.delenv("CURATOR_OBS_PATH", raising=False)
    monkeypatch.delenv("CURATOR_USAGE_PATH", raising=False)
    monkeypatch.delenv("CURATOR_LOG_PATH", raising=False)
    monkeypatch.delenv("IMPROVE_REPORT_DIR", raising=False)

    from curator import daemon, models, server_log, worker
    from curator.backend.local import LocalBackend
    from curator.observability import Observability
    from curator.retrieval_feedback import RetrievalFeedback

    state_dir = tmp_path / ".curator"
    local = LocalBackend()

    try:
        assert Path(local._db_path) == state_dir / "knowledge.db"
        assert Observability().path == state_dir / "improve_events.jsonl"
        assert RetrievalFeedback().storage_path == state_dir / "usage.json"
        assert server_log._path() == state_dir / "server.log"
        assert models._registry_path() == state_dir / "fact_types.json"
        assert daemon._pid_file() == state_dir / "worker.pid"
        assert daemon._worker_log() == state_dir / "worker.log"
        assert worker._report_dir_from_env() == state_dir / "reports"
    finally:
        local._conn.close()


def test_component_overrides_win_over_state_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("CURATOR_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("CURATOR_OBS_PATH", str(tmp_path / "custom-observability.jsonl"))
    monkeypatch.setenv("CURATOR_USAGE_PATH", str(tmp_path / "custom-usage.json"))
    monkeypatch.setenv("CURATOR_LOG_PATH", str(tmp_path / "custom-server.log"))
    monkeypatch.setenv("IMPROVE_REPORT_DIR", str(tmp_path / "custom-reports"))

    from curator import server_log, worker
    from curator.observability import Observability
    from curator.retrieval_feedback import RetrievalFeedback

    assert Observability().path == tmp_path / "custom-observability.jsonl"
    assert RetrievalFeedback().storage_path == tmp_path / "custom-usage.json"
    assert server_log._path() == tmp_path / "custom-server.log"
    assert worker._report_dir_from_env() == tmp_path / "custom-reports"


def test_default_state_dir_remains_home_curator(tmp_path, monkeypatch):
    monkeypatch.delenv("CURATOR_STATE_DIR", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))

    from curator.state import state_dir

    assert state_dir() == tmp_path / ".curator"


def test_cli_loads_state_from_project_opencode_config(tmp_path, monkeypatch):
    import json

    project = tmp_path / "project"
    nested = project / "src"
    nested.mkdir(parents=True)
    (project / ".git").mkdir()
    config_dir = project / ".opencode"
    config_dir.mkdir()
    config_dir.joinpath("opencode.json").write_text(json.dumps({
        "mcp": {"memory-curator": {"environment": {
            "CURATOR_STATE_DIR": str(project / ".curator"),
            "CURATOR_BASE_DIR": str(project),
            "CURATOR_MAP": str(project / "DOCUMENTATION-MAP.md"),
        }}},
    }), encoding="utf-8")
    for name in ("CURATOR_STATE_DIR", "CURATOR_BASE_DIR", "CURATOR_MAP"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(nested)

    from curator import control
    control._apply_project_mcp_env()

    assert Path(control.os.environ["CURATOR_STATE_DIR"]) == project / ".curator"
    assert Path(control.os.environ["CURATOR_BASE_DIR"]) == project
    assert Path(control.os.environ["CURATOR_MAP"]) == project / "DOCUMENTATION-MAP.md"
