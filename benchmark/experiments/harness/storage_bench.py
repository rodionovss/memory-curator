"""Эксперимент 04: Markdown scan vs SQLite retrieval (backend benchmark, без LLM).

S1 (markdown): naive scan по .md-файлам — как выглядел бы поиск без Curator:
casefold-подстрока по заголовку/тегу/телу, ранжирование по числу попаданий.
S2 (sqlite): delivery.fetch_context через LocalBackend — retrieval v2:
маршруты (Task 7, source_file фактов corpus/kb + base_dir) + детерминированное
расширение запроса алиасами (Task 8), stemming, scoring, threshold,
deprecated-out.

Оба backend-а видят одинаковый набор фактов: 6 из corpus/kb + 1 synthetic
deprecated-факт (проверка status-фильтра). 20 замороженных запросов
(corpus/storage-queries.json) × 5 повторов.

Метрики: precision/recall@limit-3, false positives на no_result-запросах,
детерминированность порядка, p50/p95 latency, размер выдачи в токенах.

Пороговый sweep (Task 8): `--thresholds 0.20,0.30,0.40,0.50,0.60` — те же
замороженные запросы, S2 per-threshold метрики + гейты; артефакт
results/04-storage/threshold-sweep.json (numbers only).

Запуск: python storage_bench.py [--repeats 5] [--thresholds 0.20,...]
"""

import argparse
import json
import re
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "core"))

from curator.backend.local import LocalBackend  # noqa: E402
from curator.delivery import fetch_context  # noqa: E402
from curator.models import StructuredFact  # noqa: E402

CORPUS = Path(__file__).resolve().parents[1] / "corpus"
RESULTS = Path(__file__).resolve().parents[1] / "results" / "04-storage"
LIMIT = 3
_TOKEN_RE = re.compile(r"\w+", re.UNICODE)

# Замороженный baseline S2 (committed summary.json, retrieval v1):
# число для гейта recall sweep'а.
BASELINE_RECALL = 0.312
GATE_PRECISION_MIN = 0.90
GATE_FP_MAX = 0.10
CONTROL_CLASSES = ("no_result", "deprecated_silence")


def load_kb_facts() -> list[dict]:
    """Факты из corpus/kb + synthetic deprecated-факт из queries-файла."""
    facts = []
    for md in sorted((CORPUS / "kb").glob("F*.md")):
        text = md.read_text(encoding="utf-8")
        title = next(l[2:] for l in text.splitlines() if l.startswith("# "))
        tags = re.findall(r"tags:\s*\[([^\]]*)\]", text)
        facts.append({
            "fact_id": md.stem.split("-", 1)[0],
            "title": title,
            "tags": [t.strip() for t in tags[0].split(",")] if tags else [],
            "status": "verified",
            "source_file": md.name,
            "content": "\n".join(l for l in text.splitlines()
                                 if not l.startswith("---") and not l.startswith("# ")
                                 and not l.startswith("type:") and not l.startswith("tags:")),
        })
    meta = json.loads((CORPUS / "storage-queries.json").read_text(encoding="utf-8"))
    d = meta["deprecated_synth_fact"]
    facts.append({"fact_id": d["fact_id"], "title": d["title"], "tags": d["tags"],
                  "status": "deprecated", "source_file": None, "content": d["content"]})
    return facts


def md_search(query: str, facts: list[dict]) -> list[str]:
    """S1: naive casefold-substring scan, ранжирование по числу попаданий."""
    tokens = [t for t in _TOKEN_RE.findall(query.casefold()) if len(t) >= 3]
    hits = []
    for f in facts:
        haystack = " ".join([f["title"], " ".join(f["tags"]), f["content"]]).casefold()
        score = sum(1 for t in tokens if t in haystack)
        if score > 0:
            hits.append((score, f["fact_id"]))
    hits.sort(key=lambda x: (-x[0], x[1]))
    return [fid for _, fid in hits[:LIMIT]]


def _make_backend(facts: list[dict]) -> tuple[LocalBackend, dict[str, str]]:
    """S2: LocalBackend на тех же фактах + маппинг title→fact_id.

    store_fact генерит случайный id — сравнение с corpus-идентификаторами
    (F72 и пр.) только через title, никогда по row id.
    """
    be = LocalBackend(":memory:")
    for f in facts:
        be.store_fact(StructuredFact(
            type="Reference", title=f["title"], tags=f["tags"],
            status=f["status"], content_summary=f["content"],
            source_file=f.get("source_file"),
        ))
    return be, {f["title"]: f["fact_id"] for f in facts}


def _run_s2(
    queries: list[dict],
    facts: list[dict],
    repeats: int,
    relevance_threshold: float,
) -> list[dict]:
    """Прогоны S2 (retrieval v2: маршруты + расширение) на одном пороге."""
    be, id_by_title = _make_backend(facts)
    runs = []
    for rep in range(1, repeats + 1):
        for q in queries:
            t0 = time.perf_counter()
            cards = fetch_context(
                q["query"], be, feedback=None, limit=LIMIT,
                relevance_threshold=relevance_threshold, base_dir=CORPUS / "kb",
            )
            latency_ms = (time.perf_counter() - t0) * 1000
            returned = [id_by_title[c.title] for c in cards]
            runs.append({
                "repeat": rep, "query_id": q["id"], "class": q["class"],
                "backend": "S2", "returned": returned,
                "expected": q["expected_fact_ids"],
                "latency_ms": round(latency_ms, 3),
                "result_tokens": round(sum(len(f["content"]) for f in facts
                                           if f["fact_id"] in returned) / 4),
            })
    return runs


def run(repeats: int, out_dir: Path | None = None) -> dict:
    facts = load_kb_facts()
    queries = json.loads((CORPUS / "storage-queries.json").read_text(encoding="utf-8"))["queries"]
    be, id_by_title = _make_backend(facts)

    runs = []
    for rep in range(1, repeats + 1):
        for q in queries:
            for backend_name, search in (("S1", md_search), ("S2", None)):
                if backend_name == "S1":
                    t0 = time.perf_counter()
                    returned = search(q["query"], facts)
                    latency_ms = (time.perf_counter() - t0) * 1000
                else:
                    t0 = time.perf_counter()
                    cards = fetch_context(
                        q["query"], be, feedback=None, limit=LIMIT,
                        base_dir=CORPUS / "kb",
                    )
                    latency_ms = (time.perf_counter() - t0) * 1000
                    returned = [id_by_title[c.title] for c in cards]
                runs.append({
                    "repeat": rep, "query_id": q["id"], "class": q["class"],
                    "backend": backend_name, "returned": returned,
                    "expected": q["expected_fact_ids"],
                    "latency_ms": round(latency_ms, 3),
                    "result_tokens": round(sum(len(f["content"]) for f in facts
                                               if f["fact_id"] in returned) / 4),
                })

    return summarize(runs, out_dir=out_dir)


def summarize(runs: list[dict], out_dir: Path | None = None) -> dict:
    def group_by(pred):
        return [r for r in runs if pred(r)]

    summary_rows = {}
    for backend in ("S1", "S2"):
        b = group_by(lambda r: r["backend"] == backend)
        evaluable = [r for r in b if r["class"] != "no_result" or True]
        precision_hits, precision_total = 0, 0
        recall_hits, recall_total = 0, 0
        for r in evaluable:
            returned, expected = set(r["returned"]), set(r["expected"])
            if returned:
                precision_hits += len(returned & expected)
                precision_total += len(returned)
            if expected:
                recall_hits += len(returned & expected)
                recall_total += len(expected)
        no_result = [r for r in b if r["class"] == "no_result"]
        false_positives = sum(1 for r in no_result if r["returned"])
        dep = [r for r in b if r["class"] == "deprecated_silence"]
        dep_leak = sum(1 for r in dep if "FD1" in r["returned"])
        latencies = [r["latency_ms"] for r in b]

        # детерминированность: одинаковый порядок выдачи между повторами
        by_query = {}
        for r in b:
            by_query.setdefault(r["query_id"], []).append(r["returned"])
        deterministic = all(len({json.dumps(x) for x in v}) == 1 for v in by_query.values())

        summary_rows[backend] = {
            "runs": len(b),
            "precision": round(precision_hits / precision_total, 3) if precision_total else None,
            "recall": round(recall_hits / recall_total, 3) if recall_total else None,
            "no_result_false_positive_rate": round(false_positives / len(no_result), 3) if no_result else None,
            "deprecated_leak_rate": round(dep_leak / len(dep), 3) if dep else None,
            "latency_p50_ms": round(statistics.median(latencies), 3),
            "latency_p95_ms": round(sorted(latencies)[int(len(latencies) * 0.95) - 1], 3) if latencies else None,
            "avg_result_tokens": round(statistics.mean([r["result_tokens"] for r in b]), 1),
            "deterministic_order": deterministic,
        }

    summary = {
        "experiment": "04-storage",
        "runs": len(runs),
        "backends": summary_rows,
        "primary_metric": "recall",
    }
    out = out_dir or RESULTS
    out.mkdir(parents=True, exist_ok=True)
    (out / "runs.json").write_text(json.dumps(runs, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


def _s2_metrics(runs: list[dict]) -> dict:
    """Per-threshold метрики S2. Агрегация как в summarize(): micro-precision
    Σ|returned∩expected|/Σ|returned|, micro-recall Σ|returned∩expected|/Σ|expected|.

    silence_rate — доля прогонов с ожидаемыми фактами, вернувших пустоту.
    control_false_application_rate — доля контрольных прогонов
    (no_result + deprecated_silence), вернувших хоть один факт.
    Точные (не округлённые) значения — на них считаются гейты.
    """
    precision_hits, precision_total = 0, 0
    recall_hits, recall_total = 0, 0
    for r in runs:
        returned, expected = set(r["returned"]), set(r["expected"])
        if returned:
            precision_hits += len(returned & expected)
            precision_total += len(returned)
        if expected:
            recall_hits += len(returned & expected)
            recall_total += len(expected)
    no_result = [r for r in runs if r["class"] == "no_result"]
    control = [r for r in runs if r["class"] in CONTROL_CLASSES]
    dep = [r for r in runs if r["class"] == "deprecated_silence"]
    with_expected = [r for r in runs if r["expected"]]
    latencies = [r["latency_ms"] for r in runs]

    by_query: dict[str, list[list[str]]] = {}
    for r in runs:
        by_query.setdefault(r["query_id"], []).append(r["returned"])
    deterministic = all(
        len({json.dumps(x) for x in v}) == 1 for v in by_query.values()
    )

    return {
        "runs": len(runs),
        "precision": precision_hits / precision_total if precision_total else None,
        "recall": recall_hits / recall_total if recall_total else None,
        "no_result_false_positive_rate":
            (sum(1 for r in no_result if r["returned"]) / len(no_result))
            if no_result else None,
        "deprecated_leak_rate":
            (sum(1 for r in dep if "FD1" in r["returned"]) / len(dep))
            if dep else None,
        "control_false_application_rate":
            (sum(1 for r in control if r["returned"]) / len(control))
            if control else None,
        "silence_rate":
            (sum(1 for r in with_expected if not r["returned"]) / len(with_expected))
            if with_expected else None,
        "deterministic_order": deterministic,
        "latency_p50_ms": round(statistics.median(latencies), 3),
        "latency_p95_ms":
            round(sorted(latencies)[int(len(latencies) * 0.95) - 1], 3)
            if latencies else None,
    }


def _evaluate_gates(metrics: dict) -> dict:
    """Исполнимый контракт порога (Task 8): все пять гейтов на точных значениях."""
    return {
        "precision_ge_090": metrics["precision"] is not None
        and metrics["precision"] >= GATE_PRECISION_MIN,
        "deprecated_leak_eq_0": metrics["deprecated_leak_rate"] == 0.0,
        "no_result_fp_le_010": metrics["no_result_false_positive_rate"] is not None
        and metrics["no_result_false_positive_rate"] <= GATE_FP_MAX,
        "control_false_application_eq_0":
            metrics["control_false_application_rate"] == 0.0,
        "recall_gt_baseline": metrics["recall"] is not None
        and metrics["recall"] > BASELINE_RECALL,
    }


def run_threshold_sweep(
    thresholds: list[float], repeats: int, out_dir: Path | None = None
) -> dict:
    """Пороговый sweep S2 (retrieval v2: маршруты + алиасы), замороженные запросы.

    Один прогон на каждый порог; per-threshold метрики + гейты; артефакт
    threshold-sweep.json (numbers only). Tie-break: среди прошедших все
    гейты — НАИВЫСШИЙ порог (минимум ложных срабатываний в доставке).
    Ни один порог не прошёл → chosen_threshold=None, гейты не расслабляются.
    """
    facts = load_kb_facts()
    queries = json.loads(
        (CORPUS / "storage-queries.json").read_text(encoding="utf-8")
    )["queries"]

    results = []
    for threshold in thresholds:
        runs = _run_s2(queries, facts, repeats, threshold)
        metrics = _s2_metrics(runs)
        gates = _evaluate_gates(metrics)
        results.append({
            "threshold": threshold,
            "runs": metrics["runs"],
            "precision": round(metrics["precision"], 3)
            if metrics["precision"] is not None else None,
            "recall": round(metrics["recall"], 3)
            if metrics["recall"] is not None else None,
            "no_result_false_positive_rate":
                round(metrics["no_result_false_positive_rate"], 3)
                if metrics["no_result_false_positive_rate"] is not None else None,
            "deprecated_leak_rate": round(metrics["deprecated_leak_rate"], 3)
                if metrics["deprecated_leak_rate"] is not None else None,
            "control_false_application_rate":
                round(metrics["control_false_application_rate"], 3)
                if metrics["control_false_application_rate"] is not None else None,
            "silence_rate": round(metrics["silence_rate"], 3)
                if metrics["silence_rate"] is not None else None,
            "deterministic_order": metrics["deterministic_order"],
            "latency_p50_ms": metrics["latency_p50_ms"],
            "latency_p95_ms": metrics["latency_p95_ms"],
            "gates": gates,
            "all_gates_pass": all(gates.values()),
        })

    passing = [r["threshold"] for r in results if r["all_gates_pass"]]
    sweep = {
        "experiment": "04-storage-threshold-sweep",
        "backend": "S2 retrieval v2 (knowledge routes + query expansion)",
        "repeats": repeats,
        "baseline_recall": BASELINE_RECALL,
        "gate_contract": {
            "precision_min": GATE_PRECISION_MIN,
            "deprecated_leak_rate_eq": 0.0,
            "no_result_false_positive_rate_max": GATE_FP_MAX,
            "control_false_application_rate_eq": 0.0,
            "recall_min_strict": BASELINE_RECALL,
        },
        "tie_break": "highest threshold among all-gates-pass (min false positives)",
        "results": results,
        "chosen_threshold": max(passing) if passing else None,
    }
    out = out_dir or RESULTS
    out.mkdir(parents=True, exist_ok=True)
    (out / "threshold-sweep.json").write_text(
        json.dumps(sweep, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(sweep, ensure_ascii=False, indent=2))
    return sweep


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--out-dir", default=None,
                        help="куда писать артефакты (по умолчанию results/04-storage); "
                             "ре-раны указывают отдельный каталог, чтобы не затирать замороженный baseline")
    parser.add_argument(
        "--thresholds", type=str, default=None,
        help="comma-separated sweep, e.g. 0.20,0.30,0.40,0.50,0.60",
    )
    args = parser.parse_args()
    out_dir = Path(args.out_dir) if args.out_dir else None
    if args.thresholds:
        thresholds = [float(t) for t in args.thresholds.split(",") if t.strip()]
        run_threshold_sweep(thresholds, args.repeats, out_dir=out_dir)
    else:
        run(args.repeats, out_dir=out_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
