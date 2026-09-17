"""Runner эксперимента 01: routing format.

Один прогон = (task, variant, model, repeat):
- свежий isolated HOME (минимальный opencode config, без глобального сетапа);
- workspace из fixture + kb + вариант AGENTS.md;
- `opencode run --dir ws --model <m> --title <run_id> "<task>"`;
- транскрипт из isolated opencode.db → events;
- детерминированный check → application_pass;
- результат в results/01-routing-format/runs/<run_id>.json (schemas/run.json).

Полная матрица: 8 задач × 4 варианта × 3 повтора × 2 модели = 192.
Запуск: python runner.py --experiment 01 [--tasks T01,K1] [--variants R0,R2]
        [--models strong,weak] [--repeats 3] [--dry]
"""

import argparse
import json
import subprocess
import sys
import time
import uuid
from pathlib import Path

from checkrun import run_check
from isolate import build_isolated_home, cleanup_isolated_home, isolated_env
from transcript import kb_events, parse_session_db
from workspace import build_workspace, load_models, load_tasks, task_prompt

EXPERIMENTS = {
    "01": {
        "name": "01-routing-format",
        "variants": ["R0", "R1", "R2", "R3"],
    },
}
RESULTS_DIR = Path(__file__).resolve().parents[1] / "results"
DB_REL = ".local/share/opencode/opencode.db"


def run_single(task: dict, variant: str, model_name: str, model_id: str,
               repeat: int, scratch: Path) -> dict:
    run_id = f"{task['task_id']}_{variant}_{model_name}_r{repeat}_{uuid.uuid4().hex[:6]}"
    run_dir = scratch / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    ws = build_workspace(run_dir, task, variant)
    home = build_isolated_home(run_dir, model_id)
    prompt = task_prompt(task)

    started = time.perf_counter()
    proc = subprocess.run(
        ["opencode", "run", "--dir", str(ws), "--title", run_id, prompt],
        env=isolated_env(home),
        capture_output=True,
        text=True,
        timeout=900,
    )
    latency_ms = (time.perf_counter() - started) * 1000

    transcript = parse_session_db(home / DB_REL)
    events = kb_events(transcript, ws)

    ok, message = run_check(task["check"], ws)
    false_application = False
    if task["class"] == "false_application_control" and not ok:
        false_application = True

    result = {
        "experiment": "01-routing-format",
        "run_id": run_id,
        "task_id": task["task_id"],
        "task_class": task["class"],
        "variant": variant,
        "model": model_name,
        "expected_fact_ids": [task["expected_fact_id"]] if task["expected_fact_id"] else [],
        "memory_required": task["memory_required"],
        "looks_easy": task["looks_easy"],
        "events": events,
        "checks": {
            "application_pass": ok,
            "false_application": false_application,
            "review_status": "not_needed",
            "message": message,
        },
        "metrics": {
            "tool_calls": len(transcript["tool_calls"]),
            "input_tokens": transcript["tokens_input"],
            "output_tokens": transcript["tokens_output"],
            "latency_ms": round(latency_ms),
            "kb_reads": len(events),
        },
        "session_id": transcript["session_id"],
        "returncode": proc.returncode,
        "stderr_tail": proc.stderr[-500:] if proc.returncode != 0 else "",
    }

    cleanup_isolated_home(run_dir)
    return result


def emit(result: dict) -> Path:
    out_dir = RESULTS_DIR / "01-routing-format" / "runs"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{result['run_id']}.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment", default="01", choices=EXPERIMENTS)
    parser.add_argument("--tasks", default="all")
    parser.add_argument("--variants", default="R0,R1,R2,R3")
    parser.add_argument("--models", default="strong")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--scratch", default="/tmp/curator-experiments")
    parser.add_argument("--dry", action="store_true")
    args = parser.parse_args()

    tasks = load_tasks()
    if args.tasks != "all":
        wanted = {t.strip() for t in args.tasks.split(",")}
        tasks = [t for t in tasks if t["task_id"] in wanted]
    variants = [v.strip() for v in args.variants.split(",")]
    models = load_models()
    chosen = {k.strip(): v for k, v in
              (pair.split(":", 1) if ":" in pair else (pair, models[pair])
               for pair in args.models.split(","))}

    scratch = Path(args.scratch)
    scratch.mkdir(parents=True, exist_ok=True)

    total = len(tasks) * len(variants) * len(chosen) * args.repeats
    print(f"plan: {len(tasks)} tasks × {len(variants)} variants × "
          f"{len(chosen)} models × {args.repeats} repeats = {total} runs")

    done = 0
    for task in tasks:
        for variant in variants:
            for model_name, model_id in chosen.items():
                for repeat in range(1, args.repeats + 1):
                    done += 1
                    if args.dry:
                        print(f"[dry] {task['task_id']} {variant} {model_name} r{repeat}")
                        continue
                    result = run_single(task, variant, model_name, model_id,
                                        repeat, scratch)
                    out = emit(result)
                    print(f"[{done}/{total}] {result['run_id']} → "
                          f"pass={result['checks']['application_pass']} "
                          f"kb_reads={result['metrics']['kb_reads']} ({out.name})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
