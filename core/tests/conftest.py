"""Общие фикстуры."""

import pytest


@pytest.fixture(autouse=True)
def isolated_curator_logs(tmp_path, monkeypatch):
    """Инвариант: тесты никогда не пишут в реальные данные пользователя.

    improve-лог и usage-телеметрия по умолчанию живут в ~/.curator/ —
    env-override уводит их в песочницу для каждого теста, независимо от слоя."""
    monkeypatch.setenv("CURATOR_OBS_PATH", str(tmp_path / "improve_events.jsonl"))
    monkeypatch.setenv("CURATOR_USAGE_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setenv("CURATOR_CANDIDATES_PATH", str(tmp_path / "candidates.jsonl"))
    monkeypatch.setenv("CURATOR_SHADOW_LOG_PATH", str(tmp_path / "delivery-shadow.jsonl"))


@pytest.fixture
def tmpdir(tmp_path):
    return tmp_path
