"""Runner экспериментов 01/02/03.

Один прогон = (task, variant, model, repeat):
- свежий isolated HOME (минимальный opencode config; mcp — только руки с curator);
- workspace из fixture + kb + routing (--routing для 02/03);
- `opencode run --dir ws --model <m> --title <run_id> "<task>"`;
- транскрипт из isolated opencode.db → events (kb reads + curator tool calls);
- детерминированный check → application_pass;
- результат в results/<experiment>/runs/<run_id>.json (schemas/run.json).

Эксперименты:
- 01-routing-format: варианты R0-R3 (routing-формат, без --routing);
- 02-access-path: руки P0-P3 поверх routing из --routing (по умолчанию R2 —
  победитель 01 ещё неизвестен);
  * P0: routing + kb в workspace, curator отсутствует;
  * P1: routing + curator MCP (изолированная засеянная SQLite-база);
  * P2: P1 + каталожная карта «тема → curator query» (p2-catalog.md);
  * P3: routing + oracle-факт в промпте, kb в workspace НЕ кладём;
- 03-proactive-delivery: руки O0/O1/Q0/Q1 поверх routing из --routing;
  * O0/Q0: идентично P0; O1: oracle-карточка в промпте;
  * Q1: реальный retriever curator fetch_context до запуска; пусто →
    delivery "silent" + silent_delivery=true.

Полная матрица: 8 задач × варианты × повторы × модели.
Запуск: python runner.py --experiment 01|02|03 [--routing R2]
        [--tasks T01,K1] [--variants ...] [--models strong,weak]
        [--repeats 3] [--dry]
"""

import argparse
import json
import subprocess
import sys
import time
import uuid
from pathlib import Path

from checkrun import run_check
from curator_seed import proactive_delivery, seed_curator_db
from isolate import build_isolated_home, cleanup_isolated_home, curator_mcp_entry, isolated_env
from transcript import curator_events, kb_events, parse_session_db
from workspace import build_workspace, knowledge_prompt, load_models, load_tasks, oracle_fact_content, task_prompt

EXPERIMENTS = {
    "01": {
        "name": "01-routing-format",
        "variants": ["R0", "R1", "R2", "R3"],
    },
    "02": {
        "name": "02-access-path",
        "variants": ["P0", "P1", "P2", "P3"],
    },
    "03": {
        "name": "03-proactive-delivery",
        "variants": ["O0", "O1", "Q0", "Q1"],
    },
}

# Руки эксперимента 02. routing везде из --routing.
EXP02_ARMS = {
    "P0": {"include_kb": True, "curator_mcp": False, "catalog": False, "oracle": False},
    "P1": {"include_kb": True, "curator_mcp": True, "catalog": False, "oracle": False},
    "P2": {"include_kb": True, "curator_mcp": True, "catalog": True, "oracle": False},
    "P3": {"include_kb": False, "curator_mcp": False, "catalog": False, "oracle": True},
}

# Руки эксперимента 03. O0/Q0 идентичны P0; curator MCP в сессии нет —
# карточка (или её отсутствие) приходит в промпте до запуска агента.
EXP03_ARMS = {
    "O0": {"include_kb": True, "oracle": False, "retriever": False, "delivery": "none"},
    "O1": {"include_kb": True, "oracle": True, "retriever": False, "delivery": "oracle_card"},
    "Q0": {"include_kb": True, "oracle": False, "retriever": False, "delivery": "none"},
    "Q1": {"include_kb": True, "oracle": False, "retriever": True, "delivery": "real_retriever"},
}


def arm_table(experiment: str) -> dict:
    return EXP02_ARMS if experiment == "02" else EXP03_ARMS


RESULTS_DIR = Path(__file__).resolve().parents[1] / "results"
DB_REL = ".local/share/opencode/opencode.db"


def _run_id(task: dict, variant: str, model_name: str, repeat: int) -> str:
    return f"{task['task_id']}_{variant}_{model_name}_r{repeat}_{uuid.uuid4().hex[:6]}"


def _prepare(task: dict, arm: dict | None, run_dir: Path, routing: str) -> dict:
    """Подготовка прогона: workspace, mcp-конфиг, промпт, delivery.

    arm=None — эксперимент 01 (routing=variant, kb в workspace, без curator).
    Без запуска агента — вызывается из run_single и тестируется юнит-тестами.
    """
    arm = arm or {}
    setup = {
        "mcp": None,
        "env_extra": None,
        "delivery": arm.get("delivery"),
        "silent_delivery": False,
    }

    setup["ws"] = build_workspace(
        run_dir, task, routing,
        include_kb=arm.get("include_kb", True),
        catalog=arm.get("catalog", False),
    )

    task_text = task_prompt(task)
    prompt = task_text

    if arm.get("curator_mcp"):
        db_path = run_dir / "curator.db"
        seed_curator_db(db_path)
        setup["mcp"] = curator_mcp_entry(db_path)
        setup["env_extra"] = {"CURATOR_DB_PATH": str(db_path)}
    elif arm.get("retriever"):
        retriever_db = run_dir / "curator.db"
        seed_curator_db(retriever_db)
        prompt, setup["delivery"], setup["silent_delivery"] = (
            proactive_delivery(task_text, retriever_db)
        )
    elif arm.get("oracle") and task["expected_kb_file"]:
        prompt = knowledge_prompt(oracle_fact_content(task), task_text)
    elif arm.get("oracle"):
        # контрольная задача без expected-факта: доставлять нечего
        setup["delivery"] = "none"

    setup["prompt"] = prompt
    return setup


def run_single(task: dict, variant: str, model_name: str, model_id: str,
               repeat: int, scratch: Path,
               experiment: str = "01", routing: str = "R2") -> dict:
    run_id = _run_id(task, variant, model_name, repeat)
    run_dir = scratch / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    arm = arm_table(experiment)[variant] if experiment in ("02", "03") else None
    setup = _prepare(task, arm, run_dir, routing if arm else variant)

    home = build_isolated_home(run_dir, model_id, mcp=setup["mcp"])
    prompt = setup["prompt"]

    started = time.perf_counter()
    proc = subprocess.run(
        ["opencode", "run", "--dir", str(setup["ws"]), "--title", run_id, prompt],
        env=isolated_env(home, extra=setup["env_extra"]),
        capture_output=True,
        text=True,
        timeout=900,
    )
    latency_ms = (time.perf_counter() - started) * 1000

    transcript = parse_session_db(home / DB_REL)
    kb_ev = kb_events(transcript, setup["ws"])
    events = kb_ev + curator_events(transcript)

    ok, message = run_check(task["check"], setup["ws"])
    false_application = False
    if task["class"] == "false_application_control" and not ok:
        false_application = True

    result = {
        "experiment": EXPERIMENTS[experiment]["name"],
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
            "kb_reads": len(kb_ev),
        },
        "session_id": transcript["session_id"],
        "returncode": proc.returncode,
        "stderr_tail": proc.stderr[-500:] if proc.returncode != 0 else "",
    }

    if experiment in ("02", "03"):
        result["routing"] = routing
    if experiment == "03":
        result["delivery"] = setup["delivery"]
        if setup["silent_delivery"]:
            result["silent_delivery"] = True

    cleanup_isolated_home(run_dir)
    return result


def emit(result: dict, results_dir: Path | None = None) -> Path:
    out_dir = (results_dir or RESULTS_DIR) / result["experiment"] / "runs"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{result['run_id']}.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment", default="01", choices=EXPERIMENTS)
    parser.add_argument("--routing", default="R2", choices=["R0", "R1", "R2", "R3"],
                        help="routing-вариант для рук 02/03 (по умолчанию R2)")
    parser.add_argument("--tasks", default="all")
    parser.add_argument("--variants", default=None,
                        help="по умолчанию все варианты эксперимента")
    parser.add_argument("--models", default="strong")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--scratch", default="/tmp/curator-experiments")
    parser.add_argument("--results-dir", default=None,
                        help="корень для результатов (по умолчанию benchmark/experiments/results); "
                             "ре-раны пишут в отдельный корень, чтобы не затирать замороженные артефакты")
    parser.add_argument("--dry", action="store_true")
    args = parser.parse_args()

    tasks = load_tasks()
    if args.tasks != "all":
        wanted = {t.strip() for t in args.tasks.split(",")}
        tasks = [t for t in tasks if t["task_id"] in wanted]
    variants = ([v.strip() for v in args.variants.split(",")]
                if args.variants else EXPERIMENTS[args.experiment]["variants"])
    known = EXPERIMENTS[args.experiment]["variants"]
    unknown = [v for v in variants if v not in known]
    if unknown:
        parser.error(f"недопустимые варианты {unknown} для эксперимента "
                     f"{args.experiment}; доступны: {','.join(known)}")
    models = load_models()
    chosen = {k.strip(): v for k, v in
              (pair.split(":", 1) if ":" in pair else (pair, models[pair])
               for pair in args.models.split(","))}

    scratch = Path(args.scratch)
    scratch.mkdir(parents=True, exist_ok=True)
    results_dir = Path(args.results_dir) if args.results_dir else None

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
                                        repeat, scratch,
                                        experiment=args.experiment,
                                        routing=args.routing)
                    out = emit(result, results_dir=results_dir)
                    print(f"[{done}/{total}] {result['run_id']} → "
                          f"pass={result['checks']['application_pass']} "
                          f"kb_reads={result['metrics']['kb_reads']} ({out.name})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
