"""Контрактные тесты: вывод MCP-тулзов содержит все ключевые поля.

Защита от ситуации «поле добавили в модель, но забыли показать в выводе».
Бэкенд сидится в :memory: — тесты не зависят от реальной БД.
"""

from types import SimpleNamespace

import pytest
import curator.server as server_mod
from curator.server import _improve, _query, _status, _feedback
from curator.backend.local import LocalBackend
from curator.improve_loop import ImproveLoop
from curator.models import StructuredFact


@pytest.fixture(autouse=True)
def seeded_backend(monkeypatch):
    be = LocalBackend(":memory:")
    be.store_fact(StructuredFact(
        type="Reference", title="ImmutableList нужен только для стабильных коллекций",
        tags=["kotlin"], status="verified",
        content_summary="Для read-only данных ImmutableList оправдан, иначе overhead.",
    ))
    be.store_fact(StructuredFact(
        type="Reference", title="Старая гипотеза про производительность боксинга",
        tags=["kotlin"], status="hypothesis",
        content_summary="Гипотетическое знание, которое должно попасть в stale.",
    ))
    monkeypatch.setattr(server_mod, "backend", be)
    monkeypatch.setattr(server_mod, "improve", ImproveLoop(be))
    monkeypatch.delenv("CURATOR_MAP", raising=False)


def _improve_with_deprecated(monkeypatch):
    fact = StructuredFact(
        type="Reference", title="Устаревшее semantic project знание",
        tags=["project"], status="deprecated",
        content_summary="Факт был обновлён backend improve и требует lifecycle обработки.",
        source_file="docs/knowledge.md",
    )
    report = SimpleNamespace(
        deprecated=[fact], stats={"total_facts": 1, "duplicates_found": 0,
                                  "stale_found": 1, "contradictions_found": 0},
        metrics_before=None, metrics_after=None, duplicates=[], stale=[fact],
        contradictions=[], resolutions=[], events=[],
    )
    monkeypatch.setattr(server_mod, "improve", SimpleNamespace(run=lambda: report))
    return fact


class TestImproveOutput:
    def test_contains_stats_fields(self):
        output = _improve()
        assert "Всего фактов:" in output
        assert "Найдено дубликатов:" in output
        assert "Устаревших:" in output
        assert "Противоречий:" in output

    def test_contains_sections_when_data_present(self):
        output = _improve()
        sections = ["Дубликаты:", "Устаревшие:", "Противоречия", "Eval-решения:", "Часто запрашиваемые:"]
        found = [s for s in sections if s in output]
        assert len(found) > 0, f"No sections found in output:\n{output}"

    def test_eval_decisions_format(self):
        output = _improve()
        if "Eval-решения:" in output:
            assert "применено" in output or "отклонено" in output

    def test_output_is_valid_string(self):
        output = _improve()
        assert isinstance(output, str)
        assert len(output) > 50

    def test_project_map_skips_sync_lifecycle_writeback(self, monkeypatch, tmp_path):
        fact = _improve_with_deprecated(monkeypatch)
        monkeypatch.setenv("CURATOR_MAP", str(tmp_path / "DOCUMENTATION-MAP.md"))
        calls = []
        monkeypatch.setattr("curator.sync_engine.SyncEngine.rewrite_status",
                            lambda self, changed: calls.append(changed.title))

        _improve()

        assert calls == [], "semantic project docs меняет только нейронный write-back"
        assert fact.status == "deprecated", "backend improve result сохраняется"

    def test_without_project_map_keeps_legacy_sync_writeback(self, monkeypatch):
        fact = _improve_with_deprecated(monkeypatch)
        calls = []
        monkeypatch.setattr("curator.sync_engine.SyncEngine.rewrite_status",
                            lambda self, changed: calls.append(changed.title))

        _improve()

        assert calls == [fact.title]

    def test_worker_project_map_skips_sync_lifecycle_writeback(self, monkeypatch, tmp_path):
        from curator import worker

        fact = _improve_with_deprecated(monkeypatch)
        report = server_mod.improve.run()
        monkeypatch.setattr("curator.improve_loop.ImproveLoop",
                            lambda backend: SimpleNamespace(run=lambda: report))
        monkeypatch.setenv("CURATOR_MAP", str(tmp_path / "DOCUMENTATION-MAP.md"))
        calls = []
        monkeypatch.setattr("curator.sync_engine.SyncEngine.rewrite_status",
                            lambda self, changed: calls.append(changed.title))

        worker.run_improve_cycle(server_mod.backend, tmp_path / "reports", base_dir=tmp_path)

        assert calls == []
        assert fact.status == "deprecated"

    def test_cli_project_map_skips_sync_lifecycle_writeback(self, monkeypatch, tmp_path):
        from curator import control

        _improve_with_deprecated(monkeypatch)
        report = server_mod.improve.run()
        monkeypatch.setattr(control, "_make_backend", lambda: server_mod.backend)
        monkeypatch.setattr("curator.improve_loop.ImproveLoop",
                            lambda backend: SimpleNamespace(run=lambda: report))
        monkeypatch.setenv("CURATOR_MAP", str(tmp_path / "DOCUMENTATION-MAP.md"))
        calls = []
        monkeypatch.setattr("curator.sync_engine.SyncEngine.rewrite_status",
                            lambda self, changed: calls.append(changed.title))

        control.cmd_improve()

        assert calls == []


class TestStatusOutput:
    def test_contains_type_and_status(self):
        output = _status()
        assert "Всего фактов:" in output
        assert "По типам:" in output
        assert "По статусам:" in output

    def test_output_is_json_parseable(self):
        output = _status()
        assert "{" in output

    def test_total_facts_is_number(self):
        output = _status()
        import re
        match = re.search(r"Всего фактов: (\d+)", output)
        assert match, f"No total facts found in: {output}"


class TestFeedbackOutput:
    def test_contains_header(self):
        output = _feedback()
        assert "Статистика использования" in output

    def test_output_is_valid(self):
        output = _feedback()
        assert isinstance(output, str)


class TestQueryDefaultStatus:
    """curator_query по умолчанию не показывает deprecated (мусор improve-петли);
    hypothesis остаётся видимой; явный status и «all» управляют полнотой."""

    def _add_deprecated(self):
        server_mod.backend.store_fact(StructuredFact(
            type="Reference", title="Отозванный факт про deprecated мусор",
            tags=["kotlin"], status="deprecated",
            content_summary="Deprecated знание не должно показываться в выдаче по умолчанию.",
        ))

    def test_default_hides_deprecated_keeps_rest(self):
        self._add_deprecated()
        out = _query({})
        assert "Отозванный факт" not in out
        assert "ImmutableList" in out
        assert "гипотеза про производительность" in out

    def test_search_default_hides_deprecated(self):
        self._add_deprecated()
        out = _query({"search": "Deprecated"})
        assert "Отозванный факт" not in out

    def test_explicit_deprecated_status_shows_only_them(self):
        self._add_deprecated()
        out = _query({"status": "deprecated"})
        assert "Отозванный факт" in out
        assert "ImmutableList" not in out
        assert "гипотеза" not in out

    def test_all_shows_everything(self):
        self._add_deprecated()
        out = _query({"status": "all"})
        assert "Отозванный факт" in out
        assert "ImmutableList" in out
