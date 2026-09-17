"""Тесты storage-бенчмарка (эксперимент 04, без LLM).

Запуск из core: .venv/bin/python -m pytest ../../benchmark/experiments/harness/tests/test_storage_bench.py -q
(из core: ../benchmark/...)
"""

import sys
from pathlib import Path

HARNESS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HARNESS))

sys.path.insert(0, str(HARNESS.parents[2] / "core"))

from storage_bench import LIMIT, load_kb_facts, md_search, run  # noqa: E402


class TestMarkdownBackend:
    def test_exact_запрос_находит_F72(self):
        facts = load_kb_facts()
        assert "F72" in md_search("withContext вокруг suspend DAO", facts)

    def test_deprecated_факт_протекает_в_md_scan(self):
        # известный дефект S1: naive scan не знает про статусы
        facts = load_kb_facts()
        assert "FD1" in md_search("MVP Moxy legacy presenter", facts)

    def test_no_result_запрос_молчит(self):
        facts = load_kb_facts()
        assert md_search("рецепт борща", facts) == []

    def test_limit_3(self):
        facts = load_kb_facts()
        assert len(md_search("Compose экран modifier suspend", facts)) <= LIMIT


class TestBenchRun:
    def test_полный_прогон_даёт_обе_руки_и_метрики(self, tmp_path):
        summary = run(repeats=1)
        assert summary["runs"] == 40  # 20 queries × 2 backends × 1 repeat
        for backend in ("S1", "S2"):
            row = summary["backends"][backend]
            assert row["runs"] == 20
            assert row["deterministic_order"] is True
        # S2 не протаскивает deprecated-факт
        assert summary["backends"]["S2"]["deprecated_leak_rate"] == 0.0
        # S1 протаскивает — известный дефект markdown-скана
        assert summary["backends"]["S1"]["deprecated_leak_rate"] == 1.0
        # S2 точнее S1 на этом corpus
        assert summary["backends"]["S2"]["precision"] >= summary["backends"]["S1"]["precision"]

    def test_kb_фактов_7_включая_deprecated(self):
        facts = load_kb_facts()
        assert len(facts) == 7
        assert {f["status"] for f in facts} == {"verified", "deprecated"}
