"""Юнит-тесты harness-а эксперимента 05 (route placement, без живых агентов).

Проверяется: corpus placement-вариантов, сборка workspace-ов, правила
маркера, конфиг-виринг (M3 instructions), mock probe-сервер, метрики,
агрегация summary и dry-run CLI. LLM-сессии не запускаются.

Запуск из core: .venv/bin/python -m pytest ../benchmark/experiments/harness/tests/ -q
"""

import hashlib
import json
import sys
import urllib.request
from pathlib import Path

import pytest

HARNESS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HARNESS))

import route_placement_runner as rp  # noqa: E402
from isolate import build_isolated_home, cleanup_isolated_home  # noqa: E402
from workspace import load_tasks  # noqa: E402

CORPUS = HARNESS.parent / "corpus"
PLACEMENT = CORPUS / "placement-variants"

ALL_SOURCES = [
    "kb/F72-withcontext-suspend-dao.md",
    "kb/F109-retrofit-path-prefix.md",
    "kb/F121-dagger-intomap.md",
    "kb/F86-required-fields-no-orempty.md",
    "kb/F68-textalign-viewstart-port.md",
    "kb/F6-modifier-root-compose.md",
]


def _task(task_id: str) -> dict:
    return {t["task_id"]: t for t in load_tasks()}[task_id]


class TestPlacementCorpus:
    """Файлы corpus/placement-variants: маркер, структура, заморозка."""

    def test_маркер_в_m1_и_каталоге_но_не_в_указателях(self):
        m1 = (PLACEMENT / "m1-agents.md").read_text(encoding="utf-8")
        routes = (PLACEMENT / rp.ROUTE_FILE).read_text(encoding="utf-8")
        m2 = (PLACEMENT / "m2-agents.md").read_text(encoding="utf-8")
        m3 = (PLACEMENT / "m3-agents.md").read_text(encoding="utf-8")
        assert rp.ROUTE_MARKER in m1
        assert rp.ROUTE_MARKER in routes
        assert rp.ROUTE_MARKER not in m2
        assert rp.ROUTE_MARKER not in m3

    def test_m2_и_m3_указатели_идентичны(self):
        assert ((PLACEMENT / "m2-agents.md").read_bytes()
                == (PLACEMENT / "m3-agents.md").read_bytes())

    def test_m2_указатель_ссылается_на_файл_без_содержания(self):
        m2 = (PLACEMENT / "m2-agents.md").read_text(encoding="utf-8")
        assert rp.ROUTE_FILE in m2
        # только указатель — сами маршруты в файле, не в AGENTS.md
        for source in ALL_SOURCES:
            assert source not in m2

    def test_каталог_и_m1_содержат_все_6_маршрутов(self):
        for name in ("m1-agents.md", rp.ROUTE_FILE):
            text = (PLACEMENT / name).read_text(encoding="utf-8")
            for source in ALL_SOURCES:
                assert source in text, f"{source} отсутствует в {name}"
            # структура каталога маршрутов (design/knowledge-route-format.md)
            assert "**Description:**" in text
            assert "**When to use:**" in text
            assert "**Source:**" in text

    def test_frozen_sha_актуален(self):
        lines = (PLACEMENT / "FROZEN.sha").read_text(encoding="utf-8").splitlines()
        assert len(lines) == 4
        for line in lines:
            digest, name = line.split()
            content = (PLACEMENT / name).read_bytes()
            assert hashlib.sha256(content).hexdigest() == digest, name

    def test_маркер_уникален_в_corpus(self):
        hits = []
        for path in CORPUS.rglob("*.md"):
            if rp.ROUTE_MARKER in path.read_text(encoding="utf-8"):
                hits.append(path.relative_to(CORPUS).as_posix())
        assert set(hits) == {"placement-variants/m1-agents.md",
                              f"placement-variants/{rp.ROUTE_FILE}"}


class TestPlacementWorkspace:
    """Сборка workspace по варианту: файлы и маркеры."""

    @pytest.mark.parametrize("variant", rp.VARIANTS)
    def test_общий_слой_fixture_kb_agents(self, tmp_path, variant):
        ws = rp.build_placement_workspace(tmp_path, _task("T01"), variant)
        assert (ws / "AGENTS.md").exists()
        assert (ws / "kb" / "index.md").exists()
        assert (ws / "ProfileDao.kt").exists()

    def test_M1_маркер_в_agents_файла_каталога_нет(self, tmp_path):
        ws = rp.build_placement_workspace(tmp_path, _task("T01"), "M1")
        agents = (ws / "AGENTS.md").read_text(encoding="utf-8")
        assert rp.ROUTE_MARKER in agents
        assert not (ws / rp.ROUTE_FILE).exists()
        for source in ALL_SOURCES:
            assert source in agents

    @pytest.mark.parametrize("variant", ["M2", "M3"])
    def test_M23_маркер_только_в_файле(self, tmp_path, variant):
        ws = rp.build_placement_workspace(tmp_path, _task("T01"), variant)
        agents = (ws / "AGENTS.md").read_text(encoding="utf-8")
        routes = (ws / rp.ROUTE_FILE).read_text(encoding="utf-8")
        assert rp.ROUTE_MARKER not in agents
        assert rp.ROUTE_MARKER in routes
        # указатель из AGENTS.md ведёт на файл
        assert rp.ROUTE_FILE in agents

    def test_M3_agents_идентичен_M2(self, tmp_path):
        ws2 = rp.build_placement_workspace(tmp_path / "m2", _task("T01"), "M2")
        ws3 = rp.build_placement_workspace(tmp_path / "m3", _task("T01"), "M3")
        assert (ws2 / "AGENTS.md").read_bytes() == (ws3 / "AGENTS.md").read_bytes()
        assert (ws2 / rp.ROUTE_FILE).read_bytes() == (ws3 / rp.ROUTE_FILE).read_bytes()


class TestConfigWiring:
    """Инструкции M3 и probe-провайдер в конфиге изолированного home."""

    def _wired(self, tmp_path, variant, model="bifrost_GA/glm-5.3"):
        run_dir = tmp_path / variant
        ws = rp.build_placement_workspace(run_dir, _task("T01"), variant)
        home = build_isolated_home(run_dir, model)
        rp.patch_config(home,
                        instructions=([str(ws / rp.ROUTE_FILE)]
                                      if variant == "M3" else None),
                        probe_port=41234)
        return ws, home, model

    @pytest.mark.parametrize("variant", rp.VARIANTS)
    def test_verify_wiring_чистый_для_всех_вариантов(self, tmp_path, variant):
        ws, home, model = self._wired(tmp_path, variant)
        assert rp.verify_wiring(ws, home, variant, model) == []

    def test_M3_instructions_указывают_на_файл_workspace(self, tmp_path):
        _, home, _ = self._wired(tmp_path, "M3")
        cfg = json.loads((home / ".config" / "opencode" / "opencode.json")
                         .read_text(encoding="utf-8"))
        instructions = cfg["instructions"]
        assert len(instructions) == 1
        assert instructions[0].endswith(rp.ROUTE_FILE)

    def test_M1_M2_без_instructions(self, tmp_path):
        for variant in ("M1", "M2"):
            _, home, _ = self._wired(tmp_path, variant)
            cfg = json.loads((home / ".config" / "opencode" / "opencode.json")
                             .read_text(encoding="utf-8"))
            assert "instructions" not in cfg

    def test_probe_провайдер_в_конфиге(self, tmp_path):
        _, home, _ = self._wired(tmp_path, "M3")
        cfg = json.loads((home / ".config" / "opencode" / "opencode.json")
                         .read_text(encoding="utf-8"))
        entry = cfg["provider"][rp.PROBE_PROVIDER]
        assert entry["options"]["baseURL"] == "http://127.0.0.1:41234"
        assert entry["models"]["capture"]

    def test_verify_wiring_ловит_отсутствие_M3_instructions(self, tmp_path):
        run_dir = tmp_path / "broken"
        ws = rp.build_placement_workspace(run_dir, _task("T01"), "M3")
        home = build_isolated_home(run_dir, "bifrost_GA/glm-5.3")
        rp.patch_config(home, probe_port=41234)  # instructions забыли
        problems = rp.verify_wiring(ws, home, "M3", "bifrost_GA/glm-5.3")
        assert any("instructions" in p for p in problems)

    def test_verify_wiring_ловит_чужие_instructions_в_M2(self, tmp_path):
        run_dir = tmp_path / "broken"
        ws = rp.build_placement_workspace(run_dir, _task("T01"), "M2")
        home = build_isolated_home(run_dir, "bifrost_GA/glm-5.3")
        rp.patch_config(home, instructions=[str(ws / rp.ROUTE_FILE)],
                        probe_port=41234)
        problems = rp.verify_wiring(ws, home, "M2", "bifrost_GA/glm-5.3")
        assert any("instructions" in p for p in problems)

    def test_verify_wiring_ловит_маркер_в_M2_agents(self, tmp_path):
        ws, home, model = self._wired(tmp_path, "M2")
        # саботаж: маркер попал в AGENTS.md M2
        agents = ws / "AGENTS.md"
        agents.write_text(
            agents.read_text(encoding="utf-8") + "\n" + rp.ROUTE_MARKER + "\n",
            encoding="utf-8")
        problems = rp.verify_wiring(ws, home, "M2", model)
        assert any("маркер" in p for p in problems)

    def test_cleanup_после_wiring_не_трогает_реальный_auth(self, tmp_path):
        _, home, _ = self._wired(tmp_path, "M2")
        assert home.exists()
        cleanup_isolated_home(tmp_path / "M2")
        assert not (tmp_path / "M2" / "home").exists()


class TestProbeServer:
    """Mock-провайдер: захват request payload и детект маркера — без LLM."""

    def _post(self, server, payload):
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.port}/v1/chat/completions",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST")
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, response.read()

    def test_захват_и_маркер_в_system_message(self):
        server = rp.ProbeServer()
        try:
            payload = {"stream": False, "messages": [
                {"role": "system", "content": "каталог\n" + rp.ROUTE_MARKER},
                {"role": "user", "content": "ping"},
            ]}
            status, _ = self._post(server, payload)
            assert status == 200
            requests = server.requests
            assert len(requests) == 1
            assert rp.marker_in_system_messages(requests) is True
        finally:
            server.shutdown()

    def test_без_маркера_и_без_system(self):
        server = rp.ProbeServer()
        try:
            self._post(server, {"stream": False, "messages": [
                {"role": "system", "content": "обычный системный промпт"},
                {"role": "user", "content": "ping"},
            ]})
            assert rp.marker_in_system_messages(server.requests) is False

            self._post(server, {"stream": False, "messages": [
                {"role": "user", "content": "ping"},
            ]})
            assert rp.marker_in_system_messages(server.requests) is False
        finally:
            server.shutdown()

    def test_content_массивом_частей(self):
        server = rp.ProbeServer()
        try:
            self._post(server, {"stream": False, "messages": [
                {"role": "system", "content": [
                    {"type": "text", "text": "часть без маркера"},
                    {"type": "text", "text": rp.ROUTE_MARKER},
                ]},
            ]})
            assert rp.marker_in_system_messages(server.requests) is True
        finally:
            server.shutdown()

    def test_stream_true_отвечает_SSE(self):
        server = rp.ProbeServer()
        try:
            status, body = self._post(server, {"stream": True, "messages": []})
            assert status == 200
            assert b"data:" in body
            assert b"[DONE]" in body
        finally:
            server.shutdown()

    def test_requests_изолированы_между_инстансами(self):
        first = rp.ProbeServer()
        try:
            self._post(first, {"stream": False, "messages": [
                {"role": "system", "content": rp.ROUTE_MARKER}]})
            self._post(first, {"stream": False, "messages": [
                {"role": "system", "content": "без маркера"}]})
            assert len(first.requests) == 2
            # marker_present ищется по любому request (первый содержит маркер)
            assert rp.marker_in_system_messages(first.requests) is True
        finally:
            first.shutdown()
        second = rp.ProbeServer()
        try:
            assert second.requests == []  # свежий сервер ничего не помнит
        finally:
            second.shutdown()


class TestEventsAndMetrics:
    """События чтения route-файла и placement-метрики на синтетике."""

    def test_routes_file_events_только_по_файлу_каталога(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        transcript = {"tool_calls": [
            {"tool": "read", "args": {"filePath": str(ws / rp.ROUTE_FILE)}},
            {"tool": "read", "args": {"filePath": str(ws / "AGENTS.md")}},
            {"tool": "read", "args": {"filePath": str(ws / "kb" / "index.md")}},
            {"tool": "grep", "args": {"pattern": "x", "path": str(ws)}},
        ]}
        events = rp.routes_file_events(transcript, ws)
        assert events == [{"event": "routes_file_read", "source": "file_read",
                           "fact_id": None, "path": rp.ROUTE_FILE}]

    def test_placement_metrics_попадание_в_ожидаемый_факт(self):
        task = _task("T01")  # expected F72
        kb_ev = [{"event": "source_file_read", "fact_id": "F72"}]
        metrics = rp.placement_metrics(task, kb_ev, [])
        assert metrics["routing_hit"] is True
        assert metrics["source_file_reads"] == 1
        assert metrics["unnecessary_reads"] == 0

    def test_placement_metrics_чужой_факт_miss_и_лишнее_чтение(self):
        task = _task("T01")
        kb_ev = [{"event": "source_file_read", "fact_id": "F109"},
                 {"event": "source_file_read", "fact_id": "F121"}]
        metrics = rp.placement_metrics(task, kb_ev, [{"event": "routes_file_read"}])
        assert metrics["routing_hit"] is False
        assert metrics["unnecessary_reads"] == 2
        assert metrics["routes_file_reads"] == 1

    def test_placement_metrics_контроль_K1_все_чтения_лишние(self):
        task = _task("K1")  # expected_fact_id None
        kb_ev = [{"event": "source_file_read", "fact_id": "F72"},
                 {"event": "index_read", "fact_id": None}]
        metrics = rp.placement_metrics(task, kb_ev, [])
        assert metrics["routing_hit"] is False
        assert metrics["unnecessary_reads"] == 1  # index_read не считается
        assert metrics["source_file_reads"] == 1


def _write_run(runs_dir: Path, run_id: str, variant: str, model: str,
               task_id: str, *, memory: bool, hit: bool, passed: bool,
               marker_expected: bool, marker_present: bool, tokens: int,
               routes_reads: int, rc: int = 0) -> dict:
    run = {
        "experiment": rp.EXPERIMENT,
        "run_id": run_id,
        "task_id": task_id,
        "task_class": "hidden_trigger" if memory else "no_memory_control",
        "variant": variant,
        "model": model,
        "expected_fact_ids": ["F72"] if memory else [],
        "memory_required": memory,
        "looks_easy": True,
        "events": [],
        "checks": {"application_pass": passed, "false_application": False,
                   "review_status": "not_needed", "message": ""},
        "metrics": {
            "tool_calls": 2, "input_tokens": tokens, "output_tokens": 50,
            "latency_ms": 500, "kb_reads": 1,
            "source_file_reads": 1, "unnecessary_reads": 0,
            "routing_hit": hit, "routes_file_reads": routes_reads,
        },
        "placement": {
            "marker": rp.ROUTE_MARKER,
            "marker_expected": marker_expected,
            "marker_present": marker_present,
            "probe_valid": True,
        },
        "session_id": "ses_x",
        "returncode": rc,
        "stderr_tail": "",
    }
    runs_dir.mkdir(parents=True, exist_ok=True)
    (runs_dir / f"{run_id}.json").write_text(json.dumps(run), encoding="utf-8")
    return run


class TestSummarize:
    """Агрегация summary.json на синтетических прогонах."""

    def _runs_dir(self, tmp_path):
        return tmp_path / "05-route-placement" / "runs"

    def test_агрегация_и_входы_решения(self, tmp_path, monkeypatch):
        monkeypatch.setattr(rp, "RESULTS_DIR", tmp_path)
        runs = self._runs_dir(tmp_path)
        _write_run(runs, "a1", "M1", "strong", "T01", memory=True, hit=True,
                   passed=True, marker_expected=True, marker_present=True,
                   tokens=1100, routes_reads=0)
        _write_run(runs, "a2", "M1", "weak", "T01", memory=True, hit=False,
                   passed=False, marker_expected=True, marker_present=True,
                   tokens=1100, routes_reads=0)
        _write_run(runs, "a3", "M2", "strong", "T01", memory=True, hit=True,
                   passed=True, marker_expected=False, marker_present=False,
                   tokens=1400, routes_reads=1)
        _write_run(runs, "a4", "M3", "strong", "T01", memory=True, hit=True,
                   passed=True, marker_expected=True, marker_present=True,
                   tokens=1000, routes_reads=0)
        _write_run(runs, "a5", "M3", "weak", "T01", memory=True, hit=True,
                   passed=True, marker_expected=True, marker_present=False,
                   tokens=1000, routes_reads=0, rc=1)
        _write_run(runs, "a6", "M3", "strong", "K1", memory=False, hit=False,
                   passed=True, marker_expected=True, marker_present=True,
                   tokens=1000, routes_reads=0)

        summary = rp.summarize()
        assert summary["runs"] == 6
        m3 = summary["per_variant"]["M3"]
        assert m3["routing_recall"] == 1.0
        assert m3["application_rate"] == 1.0
        assert m3["marker_rate"] == round(2 / 3, 3)
        assert m3["marker_wiring_ok_rate"] == round(2 / 3, 3)
        assert summary["per_variant"]["M2"]["routes_file_reads_mean"] == 1.0
        inputs = summary["decision_inputs"]
        assert inputs["M3_vs_M2_input_tokens_delta"] == -400.0
        assert inputs["M3_vs_M1_routing_recall_delta"] == round(1.0 - 0.5, 3)
        assert inputs["M2_extra_hop"] is True
        assert summary["failures"] == ["a5"]
        assert summary["decision"] == "pending: full matrix required"
        assert (tmp_path / "05-route-placement" / "summary.json").exists()

    def _full_matrix(self, runs_dir, *, m3_marker_rate: float = 1.0):
        task_ids = ["T01", "T02", "T03", "T04", "T06", "T07", "K1", "K2"]
        i = 0
        m3_marker_on = True
        for task_id in task_ids:
            memory = task_id != "K1"
            for variant in ("M1", "M2", "M3"):
                for model in ("strong", "weak"):
                    for repeat in (1, 2, 3):
                        i += 1
                        if variant == "M3" and repeat == 1:
                            # каждая тройка: доля включённых marker_present
                            m3_marker_on = ((i // 6) % 10) < m3_marker_rate * 10
                        if variant == "M1":
                            _write_run(runs_dir, f"m{i}", "M1", model, task_id,
                                       memory=memory, hit=True, passed=True,
                                       marker_expected=True, marker_present=True,
                                       tokens=1100, routes_reads=0)
                        elif variant == "M2":
                            _write_run(runs_dir, f"m{i}", "M2", model, task_id,
                                       memory=memory, hit=True, passed=True,
                                       marker_expected=False,
                                       marker_present=False,
                                       tokens=1400, routes_reads=1)
                        else:
                            _write_run(runs_dir, f"m{i}", "M3", model, task_id,
                                       memory=memory, hit=True, passed=True,
                                       marker_expected=True,
                                       marker_present=m3_marker_on,
                                       tokens=1000, routes_reads=0)

    def test_полная_матрица_предпочитает_M3(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(rp, "RESULTS_DIR", tmp_path)
        self._full_matrix(self._runs_dir(tmp_path))
        summary = rp.summarize()
        capsys.readouterr()
        assert summary["runs"] == 144
        assert summary["per_variant"]["M3"]["marker_rate"] == 1.0
        assert summary["decision"].startswith("prefer M3")

    def test_ненадёжная_загрузка_M3_отдаёт_M1(self, tmp_path, monkeypatch):
        monkeypatch.setattr(rp, "RESULTS_DIR", tmp_path)
        self._full_matrix(self._runs_dir(tmp_path), m3_marker_rate=0.5)
        summary = rp.summarize()
        assert summary["per_variant"]["M3"]["marker_rate"] <= 0.95
        assert summary["decision"].startswith("prefer M1")

    def test_пустые_прогоны_не_пишут_summary(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(rp, "RESULTS_DIR", tmp_path)
        (tmp_path / "05-route-placement").mkdir()
        assert rp.summarize() == {}
        assert capsys.readouterr().err
        assert not (tmp_path / "05-route-placement" / "summary.json").exists()


class TestEmit:
    def test_emit_кладёт_в_папку_эксперимента(self, tmp_path, monkeypatch):
        monkeypatch.setattr(rp, "RESULTS_DIR", tmp_path)
        out = rp.emit({"experiment": rp.EXPERIMENT, "run_id": "x1"})
        assert out == (tmp_path / "05-route-placement" / "runs" / "x1.json")
        assert out.exists()


class TestCli:
    """CLI без LLM: dry-run wiring, валидация аргументов, summarize."""

    def test_dry_run_проверяет_виринг_без_llm_и_без_results(
            self, tmp_path, monkeypatch, capsys):
        scratch = tmp_path / "scratch"
        monkeypatch.setattr(rp, "RESULTS_DIR", tmp_path / "results")
        monkeypatch.setattr(sys, "argv", [
            "route_placement_runner.py", "--dry-run",
            "--tasks", "T01", "--repeats", "1", "--models", "strong",
            "--scratch", str(scratch),
        ])
        assert rp.main() == 0
        out = capsys.readouterr().out
        assert "[dry] T01 M1 strong r1 ok" in out
        assert "[dry] T01 M2 strong r1 ok" in out
        assert "[dry] T01 M3 strong r1 ok" in out
        assert "wiring OK" in out
        # dry-run ничего не пишет в results/ и не оставляет scratch-директорий
        assert not (tmp_path / "results").exists()
        assert list(scratch.iterdir()) == []

    def test_dry_run_полная_матрица_число_комбинаций(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(rp, "RESULTS_DIR", tmp_path / "results")
        monkeypatch.setattr(sys, "argv", [
            "route_placement_runner.py", "--dry-run",
            "--models", "strong,weak", "--repeats", "1",
            "--scratch", str(tmp_path / "scratch"),
        ])
        assert rp.main() == 0
        out = capsys.readouterr().out
        assert "48 combos" in out  # 8 tasks × 3 variants × 2 models × 1 repeat
        assert out.count(" ok\n") + out.count(" ok") >= 48

    def test_отвергает_чужие_варианты(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", [
            "route_placement_runner.py", "--dry-run", "--variants", "R0",
            "--scratch", "/tmp/rp-cli-test",
        ])
        with pytest.raises(SystemExit):
            rp.main()

    def test_отвергает_чужие_задачи(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", [
            "route_placement_runner.py", "--dry-run", "--tasks", "T99",
            "--scratch", "/tmp/rp-cli-test",
        ])
        with pytest.raises(SystemExit):
            rp.main()

    def test_отвергает_чужую_модель(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", [
            "route_placement_runner.py", "--dry-run", "--models", "unknown",
            "--scratch", "/tmp/rp-cli-test",
        ])
        with pytest.raises(SystemExit):
            rp.main()

    def test_summarize_без_прогонов_exit_1(self, tmp_path, monkeypatch):
        monkeypatch.setattr(rp, "RESULTS_DIR", tmp_path)
        monkeypatch.setattr(sys, "argv", ["route_placement_runner.py", "--summarize"])
        assert rp.main() == 1

    def test_суммаризация_через_cli(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(rp, "RESULTS_DIR", tmp_path)
        runs_dir = tmp_path / "05-route-placement" / "runs"
        _write_run(runs_dir, "cli1", "M3", "strong", "T01", memory=True,
                   hit=True, passed=True, marker_expected=True,
                   marker_present=True, tokens=100, routes_reads=0)
        monkeypatch.setattr(sys, "argv", ["route_placement_runner.py", "--summarize"])
        assert rp.main() == 0
        assert "05-route-placement" in capsys.readouterr().out
