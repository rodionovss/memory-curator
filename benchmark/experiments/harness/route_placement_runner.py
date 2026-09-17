"""Runner эксперимента 05: route placement (M1/M2/M3).

Один прогон = (task, variant, model, repeat):
- свежий isolated HOME (минимальный opencode-конфиг; M3 — в конфиг
  добавляется instructions: [<ws>/knowledge-routes.md]);
- workspace: fixture + kb + AGENTS.md варианта; M2/M3 + knowledge-routes.md;
- `opencode run --dir ws --title <run_id> "<task>"`;
- probe-сессия против локального mock-провайдера (127.0.0.1, реальный
  LLM не вызывается): прямой захват system message request payload-а
  → marker_present. Из application-результатов загрузка не выводится;
- транскрипт из isolated opencode.db → события (kb reads + чтения
  knowledge-routes.md);
- детерминированный check → application_pass;
- результат в results/05-route-placement/runs/<run_id>.json.

Варианты (содержание route-метаданных одинаковое, отличается размещение):
- M1: компактные route-метаданные в AGENTS.md — маркер в AGENTS.md;
- M2: AGENTS.md только указывает на knowledge-routes.md, файл не
  предзагружен — маркер только в файле, который агент читает сам;
- M3: knowledge-routes.md предзагружен через instructions изолированного
  конфига — маркер должен попасть в system message.

Матрица: 8 задач × 3 варианта × 3 повтора × 2 модели = 144 прогона.
Запуск: python route_placement_runner.py [--variants M1,M2,M3]
        [--models strong,weak] [--repeats 3] [--tasks all]
        [--dry-run] [--summarize]

--dry-run: self-check — собирает workspaces и isolated HOME-ы полной
матрицы, проверяет маркеры и конфиг-виринг, 0 LLM-сессий, ничего не
пишет в results/.
"""

import argparse
import json
import shutil
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from checkrun import run_check
from isolate import build_isolated_home, cleanup_isolated_home, isolated_env
from report import wilson_ci
from transcript import kb_events, parse_session_db
from workspace import CORPUS_DIR, load_models, load_tasks, task_prompt

EXPERIMENT = "05-route-placement"
VARIANTS = ["M1", "M2", "M3"]

PLACEMENT_DIR = CORPUS_DIR / "placement-variants"
ROUTE_FILE = "knowledge-routes.md"
VARIANT_FILES = {"M1": "m1-agents.md", "M2": "m2-agents.md", "M3": "m3-agents.md"}

# Уникальный маркер каталога маршрутов (та же строка заморожена в
# corpus/placement-variants/knowledge-routes.md и m1-agents.md).
ROUTE_MARKER = "<!-- route-catalog-marker: rp05-1f0c4b7e-93d2-45a8-8e6b-71c2ad9f04d3 -->"

# Ожидаемое присутствие маркера в system message по варианту:
# M1 — AGENTS.md (системный контекст), M2 — только в файле (не в system),
# M3 — файл предзагружен через instructions.
MARKER_EXPECTED = {"M1": True, "M2": False, "M3": True}

# Mock-провайдер для probe-сессий: захват request payload (system message).
PROBE_PROVIDER = "probe_mock"
PROBE_MODEL = "probe_mock/capture"
PROBE_TITLE_SUFFIX = "-probe"

RESULTS_DIR = Path(__file__).resolve().parents[1] / "results"
DB_REL = ".local/share/opencode/opencode.db"


# ---------------------------------------------------------------------------
# Workspace и конфиг
# ---------------------------------------------------------------------------

def build_placement_workspace(run_dir: Path, task: dict, variant: str) -> Path:
    """Собрать workspace placement-варианта. Возвращает путь к ws.

    Общий слой: fixture задачи + kb/ + AGENTS.md варианта.
    M1: каталог маршрутов уже внутри AGENTS.md, отдельного файла нет.
    M2/M3: + knowledge-routes.md (маркер только в нём).
    """
    ws = run_dir / "ws"
    ws.mkdir(parents=True, exist_ok=True)
    if task["fixture_dir"] is not None:
        shutil.copytree(task["fixture_dir"], ws, dirs_exist_ok=True)
    shutil.copytree(CORPUS_DIR / "kb", ws / "kb")
    shutil.copyfile(PLACEMENT_DIR / VARIANT_FILES[variant], ws / "AGENTS.md")
    if variant in ("M2", "M3"):
        shutil.copyfile(PLACEMENT_DIR / ROUTE_FILE, ws / ROUTE_FILE)
    return ws


def patch_config(home: Path, *, instructions: list[str] | None = None,
                 probe_port: int | None = None) -> None:
    """Дополнить конфиг изолированного home: instructions (M3) и probe-провайдер.

    Меняет только два поля поверх минимального конфига isolate.build_isolated_home;
    новых {file:...}-ссылок не появляется, поэтому symlink-слой не трогаем.
    """
    cfg_path = home / ".config" / "opencode" / "opencode.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    if instructions is not None:
        cfg["instructions"] = instructions
    if probe_port is not None:
        cfg.setdefault("provider", {})[PROBE_PROVIDER] = {
            "npm": "@ai-sdk/openai-compatible",
            "name": "route placement probe",
            "options": {"baseURL": f"http://127.0.0.1:{probe_port}", "apiKey": "probe"},
            "models": {"capture": {"name": "capture"}},
        }
    cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def verify_wiring(ws: Path, home: Path, variant: str, model_id: str) -> list[str]:
    """Проверить wiring варианта: файлы workspace-а + конфиг home.

    Возвращает список проблем (пустой = ок). Вызывается из dry-run и
    тестируется юнит-тестами без LLM.
    """
    problems: list[str] = []
    agents = ws / "AGENTS.md"
    routes_ws = ws / ROUTE_FILE

    if not agents.exists():
        problems.append(f"{variant}: нет AGENTS.md в workspace")
    else:
        agents_text = agents.read_text(encoding="utf-8")
        has_marker = ROUTE_MARKER in agents_text
        if has_marker != (variant == "M1"):
            problems.append(
                f"{variant}: маркер в AGENTS.md "
                + ("отсутствует, а должен быть" if variant == "M1"
                   else "присутствует, а не должен"))
    if not (ws / "kb" / "index.md").exists():
        problems.append(f"{variant}: нет kb/ в workspace")

    if variant == "M1":
        if routes_ws.exists():
            problems.append("M1: knowledge-routes.md не должен лежать в workspace")
    elif not routes_ws.exists():
        problems.append(f"{variant}: нет knowledge-routes.md в workspace")
    elif ROUTE_MARKER not in routes_ws.read_text(encoding="utf-8"):
        problems.append(f"{variant}: маркер отсутствует в knowledge-routes.md")

    cfg_path = home / ".config" / "opencode" / "opencode.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    if cfg.get("model") != model_id:
        problems.append(f"{variant}: model в конфиге != {model_id}")

    instructions = cfg.get("instructions")
    if variant == "M3":
        if instructions != [str(routes_ws)]:
            problems.append("M3: instructions != [<ws>/knowledge-routes.md]")
    elif instructions is not None:
        problems.append(f"{variant}: instructions в конфиге быть не должно")

    base_url = (cfg.get("provider", {}).get(PROBE_PROVIDER, {})
                .get("options", {}).get("baseURL", ""))
    if not base_url.startswith("http://127.0.0.1:"):
        problems.append(f"{variant}: probe-провайдер не прописан в конфиге")

    real_auth = Path.home() / ".local" / "share" / "opencode" / "auth.json"
    isolated_auth = home / ".local" / "share" / "opencode" / "auth.json"
    if real_auth.exists() and not isolated_auth.exists():
        problems.append(f"{variant}: auth symlink не создан")
    return problems


# ---------------------------------------------------------------------------
# Probe: mock-провайдер захватывает system message
# ---------------------------------------------------------------------------

class _ProbeHandler(BaseHTTPRequestHandler):
    """POST /chat/completions: записать request, ответить OK (SSE или JSON)."""

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length))
        except (json.JSONDecodeError, ValueError):
            body = {}
        self.server.requests.append(body)

        if body.get("stream"):
            payload = (b'data: {"choices":[{"delta":{"content":"OK"}}]}\n\n'
                       b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n'
                       b'data: [DONE]\n\n')
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            self.wfile.write(payload)
        else:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "choices": [{"message": {"role": "assistant", "content": "OK"},
                             "finish_reason": "stop"}],
            }).encode())

    def log_message(self, *args) -> None:
        pass


class ProbeServer:
    """Локальный mock LLM-провайдер: без реального LLM, только захват payload-ов."""

    def __init__(self) -> None:
        self._httpd = HTTPServer(("127.0.0.1", 0), _ProbeHandler)
        self._httpd.requests = []
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

    @property
    def port(self) -> int:
        return self._httpd.server_address[1]

    @property
    def requests(self) -> list[dict]:
        return list(self._httpd.requests)

    def shutdown(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()


def marker_in_system_messages(requests: list[dict],
                             marker: str = ROUTE_MARKER) -> bool:
    """Маркер в system message любого захваченного request payload-а.

    content бывает строкой или массивом частей ({type: text, text}).
    """
    for request in requests:
        for message in request.get("messages", []):
            if message.get("role") != "system":
                continue
            content = message.get("content")
            text = content if isinstance(content, str) else json.dumps(
                content, ensure_ascii=False)
            if marker in text:
                return True
    return False


def probe_marker(home: Path, ws: Path, run_id: str,
                 server: ProbeServer) -> dict:
    """Probe-сессия в том же workspace/HOME: маркер в system message?

    Реальный LLM не вызывается (mock-провайдер 127.0.0.1). probe_valid =
    захвачен хотя бы один request с messages; иначе результат probe-а
    ненадёжен и маркируется invalid.
    """
    try:
        proc = subprocess.run(
            ["opencode", "run", "--dir", str(ws), "--model", PROBE_MODEL,
             "--title", run_id + PROBE_TITLE_SUFFIX, "ping"],
            env=isolated_env(home), capture_output=True, text=True, timeout=120,
        )
        returncode = proc.returncode
    except subprocess.TimeoutExpired:
        returncode = -1
    requests = server.requests
    return {
        "marker_present": marker_in_system_messages(requests),
        "probe_valid": any(request.get("messages") for request in requests),
        "probe_returncode": returncode,
    }


# ---------------------------------------------------------------------------
# События и метрики
# ---------------------------------------------------------------------------

def routes_file_events(transcript: dict, ws: Path) -> list[dict]:
    """События чтения knowledge-routes.md — extra hop вариантов M2/M3.

    Нормализация путей та же, что в transcript.kb_events (macOS /private/tmp).
    """
    ws_prefix = str(ws.resolve()) + "/"
    events = []
    for call in transcript["tool_calls"]:
        tool = call["tool"]
        args = call["args"]
        if tool == "read":
            target = args.get("filePath") or args.get("path") or ""
        elif tool in ("glob", "grep"):
            target = args.get("path") or ""
        else:
            continue
        try:
            abs_target = str(Path(target).expanduser().resolve())
        except (OSError, RuntimeError):
            continue
        if abs_target.startswith(ws_prefix) and abs_target[len(ws_prefix):] == ROUTE_FILE:
            events.append({"event": "routes_file_read", "source": "file_read",
                           "fact_id": None, "path": ROUTE_FILE})
    return events


def placement_metrics(task: dict, kb_ev: list[dict],
                      routes_ev: list[dict]) -> dict:
    """Placement-метрики из событий прогона.

    routing_hit: прочитан source-файл ожидаемого факта (задачи с
    expected_fact_id; агрегация по ним = routing recall).
    unnecessary_reads: чтения kb source-файлов не по ожидаемому факту
    (для контроля K1 — все); навигационные чтения kb/index.md не считаются.
    """
    expected = task["expected_fact_id"]
    source_reads = [e for e in kb_ev if e["event"] == "source_file_read"]
    routing_hit = expected is not None and any(
        e["fact_id"] == expected for e in source_reads)
    unnecessary = [e for e in source_reads
                   if expected is None or e["fact_id"] != expected]
    return {
        "source_file_reads": len(source_reads),
        "unnecessary_reads": len(unnecessary),
        "routing_hit": routing_hit,
        "routes_file_reads": len(routes_ev),
    }


# ---------------------------------------------------------------------------
# Прогон
# ---------------------------------------------------------------------------

def _run_id(task: dict, variant: str, model_name: str, repeat: int) -> str:
    return f"{task['task_id']}_{variant}_{model_name}_r{repeat}_{uuid.uuid4().hex[:6]}"


def run_single(task: dict, variant: str, model_name: str, model_id: str,
               repeat: int, scratch: Path) -> dict:
    run_id = _run_id(task, variant, model_name, repeat)
    run_dir = scratch / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    ws = build_placement_workspace(run_dir, task, variant)
    home = build_isolated_home(run_dir, model_id)
    server = ProbeServer()
    try:
        patch_config(home,
                     instructions=[str(ws / ROUTE_FILE)] if variant == "M3" else None,
                     probe_port=server.port)

        started = time.perf_counter()
        try:
            proc = subprocess.run(
                ["opencode", "run", "--dir", str(ws), "--title", run_id,
                 task_prompt(task)],
                env=isolated_env(home), capture_output=True, text=True, timeout=900,
            )
            returncode = proc.returncode
            stderr_tail = proc.stderr[-500:] if proc.returncode != 0 else ""
        except subprocess.TimeoutExpired:
            returncode = -1
            stderr_tail = "timeout after 900s"
        latency_ms = (time.perf_counter() - started) * 1000

        transcript = parse_session_db(home / DB_REL)
        kb_ev = kb_events(transcript, ws)
        routes_ev = routes_file_events(transcript, ws)

        ok, message = run_check(task["check"], ws)
        false_application = task["class"] == "false_application_control" and not ok

        probe = probe_marker(home, ws, run_id, server)
        metrics = placement_metrics(task, kb_ev, routes_ev)

        result = {
            "experiment": EXPERIMENT,
            "run_id": run_id,
            "task_id": task["task_id"],
            "task_class": task["class"],
            "variant": variant,
            "model": model_name,
            "expected_fact_ids": [task["expected_fact_id"]] if task["expected_fact_id"] else [],
            "memory_required": task["memory_required"],
            "looks_easy": task["looks_easy"],
            "events": kb_ev + routes_ev,
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
                "source_file_reads": metrics["source_file_reads"],
                "unnecessary_reads": metrics["unnecessary_reads"],
                "routing_hit": metrics["routing_hit"],
                "routes_file_reads": metrics["routes_file_reads"],
            },
            "placement": {
                "marker": ROUTE_MARKER,
                "marker_expected": MARKER_EXPECTED[variant],
                "marker_present": probe["marker_present"],
                "probe_valid": probe["probe_valid"],
            },
            "session_id": transcript["session_id"],
            "returncode": returncode,
            "stderr_tail": stderr_tail,
        }
    finally:
        server.shutdown()
        cleanup_isolated_home(run_dir)
    return result


def emit(result: dict) -> Path:
    out_dir = RESULTS_DIR / result["experiment"] / "runs"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{result['run_id']}.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2),
                  encoding="utf-8")
    return out


# ---------------------------------------------------------------------------
# Агрегация
# ---------------------------------------------------------------------------

def _mean(rows: list[dict], key: str) -> float | None:
    if not rows:
        return None
    return round(sum(r["metrics"][key] for r in rows) / len(rows), 3)


def _agg(runs: list[dict]) -> dict:
    memory_runs = [r for r in runs if r["memory_required"]]
    routing = (round(sum(1 for r in memory_runs if r["metrics"]["routing_hit"])
                     / len(memory_runs), 3) if memory_runs else None)
    application = (round(sum(1 for r in memory_runs if r["checks"]["application_pass"])
                        / len(memory_runs), 3) if memory_runs else None)
    marker_rate = (round(sum(1 for r in runs if r["placement"]["marker_present"])
                        / len(runs), 3) if runs else None)
    wiring_ok = (round(sum(1 for r in runs
                           if r["placement"]["marker_present"]
                           == r["placement"]["marker_expected"]) / len(runs), 3)
                 if runs else None)
    return {
        "runs": len(runs),
        "routing_recall": routing,
        "application_rate": application,
        "marker_rate": marker_rate,
        "marker_wiring_ok_rate": wiring_ok,
        "source_file_reads_mean": _mean(runs, "source_file_reads"),
        "unnecessary_reads_mean": _mean(runs, "unnecessary_reads"),
        "routes_file_reads_mean": _mean(runs, "routes_file_reads"),
        "input_tokens_mean": _mean(runs, "input_tokens"),
        "latency_ms_mean": _mean(runs, "latency_ms"),
    }


def summarize() -> dict:
    """Агрегация прогонов в results/05-route-placement/summary.json.

    Входы decision rule: marker_rate M3 (порог 0.95), дельты
    routing/application M3 vs M1, дельта input tokens M3 vs M2,
    routes_file_reads (extra hop M2).
    """
    runs_dir = RESULTS_DIR / EXPERIMENT / "runs"
    paths = sorted(runs_dir.glob("*.json"))
    if not paths:
        print(f"нет прогонов в {runs_dir}", file=sys.stderr)
        return {}
    runs = [json.loads(p.read_text(encoding="utf-8")) for p in paths]

    per_variant = {v: _agg([r for r in runs if r["variant"] == v])
                   for v in sorted({r["variant"] for r in runs})}
    per_model = {}
    for variant in per_variant:
        for model in sorted({r["model"] for r in runs if r["variant"] == variant}):
            per_model.setdefault(variant, {})[model] = _agg(
                [r for r in runs if r["variant"] == variant and r["model"] == model])

    memory_runs = [r for r in runs if r["memory_required"]]
    app_k = sum(1 for r in memory_runs if r["checks"]["application_pass"])

    def variant_value(variant: str, key: str):
        row = per_variant.get(variant, {})
        return row.get(key)

    decision_inputs = {
        "M3_marker_rate": variant_value("M3", "marker_rate"),
        "M3_marker_threshold": 0.95,
        "M3_vs_M1_routing_recall_delta": (
            None if variant_value("M3", "routing_recall") is None
            or variant_value("M1", "routing_recall") is None
            else round(variant_value("M3", "routing_recall")
                       - variant_value("M1", "routing_recall"), 3)),
        "M3_vs_M1_application_rate_delta": (
            None if variant_value("M3", "application_rate") is None
            or variant_value("M1", "application_rate") is None
            else round(variant_value("M3", "application_rate")
                       - variant_value("M1", "application_rate"), 3)),
        "M3_vs_M2_input_tokens_delta": (
            None if variant_value("M3", "input_tokens_mean") is None
            or variant_value("M2", "input_tokens_mean") is None
            else round(variant_value("M3", "input_tokens_mean")
                       - variant_value("M2", "input_tokens_mean"), 3)),
        "M2_routes_file_reads_mean": variant_value("M2", "routes_file_reads_mean"),
        "M3_routes_file_reads_mean": variant_value("M3", "routes_file_reads_mean"),
        "M2_extra_hop": bool(variant_value("M2", "routes_file_reads_mean")),
        "probe_invalid_runs": sum(1 for r in runs if not r["placement"]["probe_valid"]),
    }

    full_matrix = (len(runs) == 144
                   and {r["variant"] for r in runs} == {"M1", "M2", "M3"}
                   and len({r["model"] for r in runs}) == 2
                   and len({r["task_id"] for r in runs}) == 8)
    if not full_matrix:
        decision = "pending: full matrix required"
    else:
        m3 = per_variant["M3"]
        m1 = per_variant["M1"]
        m2 = per_variant["M2"]
        if (m3["marker_rate"] >= 0.95
                and m3["routing_recall"] >= m1["routing_recall"]
                and m3["application_rate"] >= m1["application_rate"]
                and m3["input_tokens_mean"] < m2["input_tokens_mean"]):
            decision = ("prefer M3: route marker reliably loaded, "
                        "not lower than M1, cheaper than M2")
        elif m3["marker_rate"] < 0.95:
            decision = "prefer M1: M3 route file is not reliably auto-loaded"
        else:
            decision = ("manual review: M3 loaded but trade-off conditions "
                        "not all met (see decision_inputs)")

    summary = {
        "experiment": EXPERIMENT,
        "runs": len(runs),
        "models": sorted({r["model"] for r in runs}),
        "variants": sorted({r["variant"] for r in runs}),
        "primary_metric": "application_rate",
        "rates": {
            "routing_recall": (round(sum(1 for r in memory_runs
                                         if r["metrics"]["routing_hit"])
                                      / len(memory_runs), 3)
                               if memory_runs else None),
            "application_rate": (round(app_k / len(memory_runs), 3)
                                 if memory_runs else None),
        },
        "confidence_intervals": {
            "application_rate": wilson_ci(app_k, len(memory_runs)),
        },
        "per_variant": per_variant,
        "per_variant_model": per_model,
        "decision_inputs": decision_inputs,
        "failures": [r["run_id"] for r in runs if r.get("returncode", 0) != 0],
        "decision": decision,
    }

    out = RESULTS_DIR / EXPERIMENT / "summary.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


# ---------------------------------------------------------------------------
# Dry-run: self-check без LLM
# ---------------------------------------------------------------------------

def dry_run(tasks: list[dict], variants: list[str], chosen: dict[str, str],
            repeats: int, scratch: Path) -> int:
    """Собрать все workspaces/HOME-ы матрицы, проверить wiring, 0 LLM-сессий.

    Ничего не пишет в results/; после проверки каждой комбинации её
    run-директория удаляется.
    """
    combos = len(tasks) * len(variants) * len(chosen) * repeats
    print(f"[dry] wiring check: {len(tasks)} tasks × {len(variants)} variants × "
          f"{len(chosen)} models × {repeats} repeats = {combos} combos")
    problems_total = 0
    done = 0
    for task in tasks:
        for variant in variants:
            for model_name, model_id in chosen.items():
                for repeat in range(1, repeats + 1):
                    done += 1
                    run_dir = scratch / f"dry_{task['task_id']}_{variant}_{model_name}_r{repeat}"
                    ws = build_placement_workspace(run_dir, task, variant)
                    home = build_isolated_home(run_dir, model_id)
                    server = ProbeServer()
                    try:
                        patch_config(home,
                                     instructions=([str(ws / ROUTE_FILE)]
                                                   if variant == "M3" else None),
                                     probe_port=server.port)
                        problems = verify_wiring(ws, home, variant, model_id)
                    finally:
                        server.shutdown()
                        shutil.rmtree(run_dir, ignore_errors=True)
                    if problems:
                        problems_total += len(problems)
                        print(f"[dry] {task['task_id']} {variant} {model_name} "
                              f"r{repeat} FAIL")
                        for problem in problems:
                            print(f"      {problem}")
                    else:
                        print(f"[dry] {task['task_id']} {variant} {model_name} "
                              f"r{repeat} ok")
    if problems_total:
        print(f"[dry] wiring FAIL: {problems_total} problems")
        return 1
    print(f"[dry] wiring OK: {combos} combos, 0 problems, 0 LLM sessions")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--variants", default="M1,M2,M3")
    parser.add_argument("--models", default="strong")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--tasks", default="all")
    parser.add_argument("--scratch", default="/tmp/curator-route-placement")
    parser.add_argument("--dry-run", action="store_true",
                         help="self-check: workspaces + маркеры + конфиги, 0 LLM")
    parser.add_argument("--summarize", action="store_true",
                         help="агрегация results/05-route-placement → summary.json")
    args = parser.parse_args()
    if args.summarize and (args.dry_run or args.tasks != "all"):
        parser.error("--summarize не комбинируется с --dry-run/--tasks")

    if args.summarize:
        summary = summarize()
        return 0 if summary else 1

    tasks = load_tasks()
    if args.tasks != "all":
        wanted = {t.strip() for t in args.tasks.split(",")}
        tasks = [t for t in tasks if t["task_id"] in wanted]
        missing = wanted - {t["task_id"] for t in tasks}
        if missing:
            parser.error(f"неизвестные задачи: {','.join(sorted(missing))}")

    variants = [v.strip() for v in args.variants.split(",")]
    unknown = [v for v in variants if v not in VARIANTS]
    if unknown:
        parser.error(f"недопустимые варианты {unknown}; доступны: {','.join(VARIANTS)}")

    models = load_models()
    chosen = {}
    for pair in args.models.split(","):
        name, _, model_id = pair.partition(":")
        name = name.strip()
        if name not in models and not model_id:
            parser.error(f"неизвестная модель {name}; доступны: {','.join(models)}")
        chosen[name] = model_id.strip() or models[name]

    scratch = Path(args.scratch)
    scratch.mkdir(parents=True, exist_ok=True)

    total = len(tasks) * len(variants) * len(chosen) * args.repeats
    print(f"plan: {len(tasks)} tasks × {len(variants)} variants × "
          f"{len(chosen)} models × {args.repeats} repeats = {total} runs")

    if args.dry_run:
        return dry_run(tasks, variants, chosen, args.repeats, scratch)

    done = 0
    for task in tasks:
        for variant in variants:
            for model_name, model_id in chosen.items():
                for repeat in range(1, args.repeats + 1):
                    done += 1
                    result = run_single(task, variant, model_name, model_id,
                                        repeat, scratch)
                    out = emit(result)
                    print(f"[{done}/{total}] {result['run_id']} → "
                          f"pass={result['checks']['application_pass']} "
                          f"marker={result['placement']['marker_present']}/"
                          f"{str(result['placement']['marker_expected']).lower()} "
                          f"kb_reads={result['metrics']['kb_reads']} ({out.name})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
