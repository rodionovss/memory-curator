"""Эксперимент 04: Markdown scan vs SQLite retrieval (backend benchmark, без LLM).

S1 (markdown): naive scan по .md-файлам — как выглядел бы поиск без Curator:
casefold-подстрока по заголовку/тегу/телу, ранжирование по числу попаданий.
S2 (sqlite): delivery.fetch_context через LocalBackend (stemming, scoring,
threshold, deprecated-out).

Оба backend-а видят одинаковый набор фактов: 6 из corpus/kb + 1 synthetic
deprecated-факт (проверка status-фильтра). 20 замороженных запросов
(corpus/storage-queries.json) × 5 повторов.

Метрики: precision/recall@limit-3, false positives на no_result-запросах,
детерминированность порядка, p50/p95 latency, размер выдачи в токенах.

Запуск: python storage_bench.py [--repeats 5]
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
            "content": "\n".join(l for l in text.splitlines()
                                 if not l.startswith("---") and not l.startswith("# ")
                                 and not l.startswith("type:") and not l.startswith("tags:")),
        })
    meta = json.loads((CORPUS / "storage-queries.json").read_text(encoding="utf-8"))
    d = meta["deprecated_synth_fact"]
    facts.append({"fact_id": d["fact_id"], "title": d["title"], "tags": d["tags"],
                  "status": "deprecated", "content": d["content"]})
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


def run(repeats: int) -> dict:
    facts = load_kb_facts()
    queries = json.loads((CORPUS / "storage-queries.json").read_text(encoding="utf-8"))["queries"]

    be = LocalBackend(":memory:")
    for f in facts:
        be.store_fact(StructuredFact(
            type="Reference", title=f["title"], tags=f["tags"],
            status=f["status"], content_summary=f["content"],
        ))
    # store_fact генерит случайный id — маппинг title→fact_id из нашего списка
    id_by_title = {f["title"]: f["fact_id"] for f in facts}

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
                    cards = fetch_context(q["query"], be, feedback=None, limit=LIMIT)
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

    return summarize(runs)


def summarize(runs: list[dict]) -> dict:
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
    out = RESULTS
    out.mkdir(parents=True, exist_ok=True)
    (out / "runs.json").write_text(json.dumps(runs, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=5)
    args = parser.parse_args()
    run(args.repeats)
    return 0


if __name__ == "__main__":
    sys.exit(main())
