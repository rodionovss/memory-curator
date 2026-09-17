"""Агрегация прогонов эксперимента в summary.json (schemas/summary.json).

routing_recall:    на задачах с expected_fact — агент дошёл до файла факта.
routing_precision: на задачах без памяти (no_memory_control) — не пошёл в kb.
application_rate:  детерминированный check прошёл.
"""

import json
import math
import sys
from pathlib import Path

RESULTS_DIR = Path(__file__).resolve().parents[1] / "results"


def wilson_ci(k: int, n: int, z: float = 1.96) -> list[float]:
    if n == 0:
        return [0.0, 0.0]
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return [round(max(0.0, centre - margin), 3), round(min(1.0, centre + margin), 3)]


def summarize(experiment: str = "01-routing-format") -> dict:
    runs_dir = RESULTS_DIR / experiment / "runs"
    runs = []
    for path in sorted(runs_dir.glob("*.json")):
        runs.append(json.loads(path.read_text(encoding="utf-8")))

    def rate(subset: list[dict], predicate) -> tuple[int, int]:
        n = len(subset)
        k = sum(1 for r in subset if predicate(r))
        return k, n

    memory_tasks = [r for r in runs if r["memory_required"]]
    control_tasks = [r for r in runs if r["task_class"] == "no_memory_control"]

    got_fact = lambda r: any(e["event"] == "source_file_read"
                             and e["fact_id"] in r["expected_fact_ids"]
                             for e in r["events"])
    any_kb = lambda r: r["metrics"]["kb_reads"] > 0
    passed = lambda r: r["checks"]["application_pass"]

    routing_k, routing_n = rate(memory_tasks, got_fact)
    noise_k, noise_n = rate(control_tasks, any_kb)
    app_k, app_n = rate(memory_tasks, passed)

    per_variant = {}
    for variant in sorted({r["variant"] for r in runs}):
        v_runs = [r for r in runs if r["variant"] == variant]
        v_mem = [r for r in v_runs if r["memory_required"]]
        rk, rn = rate(v_mem, got_fact)
        ak, an = rate(v_mem, passed)
        per_variant[variant] = {
            "runs": len(v_runs),
            "routing_recall": rn and round(rk / rn, 3) or 0.0,
            "application_rate": an and round(ak / an, 3) or 0.0,
        }

    summary = {
        "experiment": experiment,
        "runs": len(runs),
        "models": sorted({r["model"] for r in runs}),
        "variants": sorted({r["variant"] for r in runs}),
        "primary_metric": "application_rate",
        "rates": {
            "routing_recall": routing_n and round(routing_k / routing_n, 3) or 0.0,
            "routing_precision_noisy_kb_reads": noise_n and round(noise_k / noise_n, 3) or 0.0,
            "application_rate": app_n and round(app_k / app_n, 3) or 0.0,
        },
        "confidence_intervals": {
            "application_rate": wilson_ci(app_k, app_n),
        },
        "per_variant": per_variant,
        "failures": [r["run_id"] for r in runs if r.get("returncode", 0) != 0],
        "decision": "pending: full matrix required",
    }

    out = RESULTS_DIR / experiment / "summary.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


if __name__ == "__main__":
    summarize(sys.argv[1] if len(sys.argv) > 1 else "01-routing-format")
