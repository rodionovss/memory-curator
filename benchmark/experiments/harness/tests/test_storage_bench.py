"""Тесты storage-бенчмарка (эксперимент 04, без LLM).

Запуск из core: .venv/bin/python -m pytest ../../benchmark/experiments/harness/tests/test_storage_bench.py -q
(из core: ../benchmark/...)
"""

import sys
from pathlib import Path

HARNESS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HARNESS))

sys.path.insert(0, str(HARNESS.parents[2] / "core"))

from storage_bench import (  # noqa: E402
    LIMIT,
    load_kb_facts,
    md_search,
    run,
    run_threshold_sweep,
)


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
        # артефакты пишутся в tmp_path — закоммиченный results/04-storage
        # (замороженный baseline) тесты мутировать не должны
        summary = run(repeats=1, out_dir=tmp_path)
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
        assert (tmp_path / "summary.json").exists()
        assert (tmp_path / "runs.json").exists()

    def test_kb_фактов_7_включая_deprecated(self):
        facts = load_kb_facts()
        assert len(facts) == 7
        assert {f["status"] for f in facts} == {"verified", "deprecated"}


class TestThresholdSweep:
    def test_sweep_пишет_артефакт_и_метрики_по_каждому_порогу(self, tmp_path):
        # артефакт пишется в out_dir — замороженный results/04-storage
        # тесты не мутируют
        sweep = run_threshold_sweep([0.2, 0.4], repeats=1, out_dir=tmp_path)
        assert (tmp_path / "threshold-sweep.json").exists()
        assert len(sweep["results"]) == 2
        assert [r["threshold"] for r in sweep["results"]] == [0.2, 0.4]
        for row in sweep["results"]:
            assert row["runs"] == 20  # 20 queries × 1 repeat, только S2
            assert row["deterministic_order"] is True
            assert set(row["gates"]) == {
                "precision_ge_090", "deprecated_leak_eq_0",
                "no_result_fp_le_010", "control_false_application_eq_0",
                "recall_gt_baseline",
            }
            assert row["all_gates_pass"] == all(row["gates"].values())
        # tie-break: chosen — прошедший гейты порог или None (не расслабляем)
        passing = [r["threshold"] for r in sweep["results"] if r["all_gates_pass"]]
        assert sweep["chosen_threshold"] == (max(passing) if passing else None)

    def test_sweep_факты_с_source_file_для_маршрутов(self):
        # retrieval v2: у corpus-фактов есть source_file → маршруты строятся,
        # deprecated-синтетика без source_file из маршрутов исключена
        facts = load_kb_facts()
        assert all(f["source_file"].endswith(".md")
                   for f in facts if f["status"] == "verified")
        assert next(f["source_file"] for f in facts
                    if f["fact_id"] == "FD1") is None
