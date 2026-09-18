"""Контракт плагина OpenCode proactive delivery (issue #28, ADR 002).

Плагин — единственный поддерживаемый lifecycle hook (`chat.message`,
до генерации ответа). Контракт: изоляция от storage backend (только CLI
`curator context`), ошибки глушатся, доставка один раз на сессию,
ручной fallback (curator get) остаётся.

Desktop-контракт (проверено дебагом 2026-09-18, OpenCode 1.18.18):
- default export — функция-фабрика (все экспорты модуля обязаны быть
  функциями, иначе загрузчик отбрасывает плагин молча);
- контекст фабрики не содержит рабочего Bun shell `$` — CLI зовётся
  через node:child_process.execFile;
- плагин подключается абсолютным путём в plugin[] opencode.json.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
PLUGIN = REPO / "integrations" / "curator-context.js"

# Поведенческий драйвер: подделываем сам curator-бинарь (fake HOME) —
# тестируется реальная цепочка execFile → env → JSON, без моков child_process.
# node запускается с HOME=<tmp>, где лежит .local/bin/curator (shell-скрипт,
# пишущий session_id в счётчик и печатающий FAKE_RESPONSE).
_DRIVER = r"""
const [,, pluginPath, scenario, homeDir] = process.argv
const fs = await import("node:fs")
const path = await import("node:path")

const binDir = path.join(homeDir, ".local", "bin")
fs.mkdirSync(binDir, { recursive: true })
const callsFile = path.join(homeDir, "calls.log")
fs.writeFileSync(callsFile, "")
fs.writeFileSync(path.join(binDir, "curator"), [
  "#!/bin/sh",
  'echo "$CURATOR_SESSION_ID" >> "$CALLS_FILE"',
  'echo "$FAKE_RESPONSE"',
  "",
].join("\n"), { mode: 0o755 })

const card = { title: "T", summary: "s", tags: [], type: "Reference",
               status: "verified", source_file: "a.md", score: 0.8, reason: "r" }
const cards = scenario === "inject" ? [card] : []
process.env.FAKE_RESPONSE = JSON.stringify({ cards, count: cards.length })
process.env.CALLS_FILE = callsFile

const { pathToFileURL } = await import("node:url")
const mod = await import(pathToFileURL(pluginPath).href)
const factory = mod.default
if (typeof factory !== "function") throw new Error("default export is not a function")
const plugin = await factory({})
const sessionId = "ses_node_1"

function output(text) {
  return { parts: [{ type: "text", text }] }
}

if (scenario === "inject") {
  const out1 = output("задача один")
  await plugin["chat.message"]({ sessionID: sessionId }, out1)
  const afterFirst = { calls: fs.readFileSync(callsFile, "utf-8").trim().split("\n").filter(Boolean).length,
                       parts: out1.parts.length }
  const out2 = output("задача два")
  await plugin["chat.message"]({ sessionID: sessionId }, out2)
  const totalCalls = fs.readFileSync(callsFile, "utf-8").trim().split("\n").filter(Boolean).length
  console.log(JSON.stringify({
    firstTurnDelivered: afterFirst.parts === 2,
    firstTurnCliCalls: afterFirst.calls,
    secondTurnCliCalls: totalCalls - afterFirst.calls,
    secondTurnParts: out2.parts.length,
  }))
} else {
  const outs = [output("a"), output("b"), output("c")]
  for (const o of outs) await plugin["chat.message"]({ sessionID: sessionId }, o)
  const calls = fs.readFileSync(callsFile, "utf-8").trim().split("\n").filter(Boolean)
  console.log(JSON.stringify({
    cliCalls: calls.length,
    appendedParts: outs.reduce((n, o) => n + o.parts.length, 0) - outs.length,
    sessionForwarded: calls.length > 0 && calls.every((c) => c === sessionId),
  }))
}
"""


def _run_node(tmp_path, scenario):
    node = shutil.which("node")
    if not node:
        pytest.skip("node недоступен")
    driver = tmp_path / "driver.mjs"
    driver.write_text(_DRIVER, encoding="utf-8")
    plugin_mjs = tmp_path / "curator-context.mjs"
    shutil.copy(PLUGIN, plugin_mjs)
    fake_home = tmp_path / "fake-home"
    fake_home.mkdir()
    env_patch = {"HOME": str(fake_home), "CALLS_FILE": "", "FAKE_RESPONSE": ""}
    import os
    env = {k: v for k, v in os.environ.items() if k not in env_patch}
    env.update({k: v for k, v in env_patch.items() if v})
    env["HOME"] = str(fake_home)
    proc = subprocess.run(
        [node, str(driver), str(plugin_mjs), scenario, str(fake_home)],
        check=True, capture_output=True, text=True, timeout=30, env=env,
    )
    return json.loads(proc.stdout)


class TestPluginContract:
    def test_плагин_существует(self):
        assert PLUGIN.exists()

    def test_hook_до_генерации_ответа(self):
        """chat.message вызывается до сохранения сообщения и ответа LLM."""
        assert '"chat.message"' in PLUGIN.read_text(encoding="utf-8")

    def test_изоляция_от_storage_backend(self):
        src = PLUGIN.read_text(encoding="utf-8")
        for forbidden in ("curator.", "knowledge.db", "sqlite", "Backend"):
            assert forbidden not in src, f"плагин не должен знать про storage: {forbidden}"
        assert "curator context" not in src or "context" in src
        # CLI-контракт: execFile зовёт curator с args ["context", trigger]
        assert '"context"' in src or "'context'" in src or "[\"context\"" in src, \
            "доставка через CLI-контракт ADR 002"

    def test_ошибки_глушатся(self):
        src = PLUGIN.read_text(encoding="utf-8")
        assert "try {" in src and "catch" in src

    def test_одна_доставка_на_сессию(self):
        src = PLUGIN.read_text(encoding="utf-8")
        assert "deliveredSessions" in src

    def test_ручной_fallback_упомянут(self):
        src = PLUGIN.read_text(encoding="utf-8")
        assert "curator get" in src

    def test_синтаксис_esm(self):
        node = shutil.which("node")
        if not node:
            pytest.skip("node недоступен")
        tmp = PLUGIN.with_name(PLUGIN.stem + ".check.mjs")
        try:
            shutil.copy(PLUGIN, tmp)
            subprocess.run([node, "--check", str(tmp)], check=True, capture_output=True)
        finally:
            tmp.unlink(missing_ok=True)


class TestDesktopContract:
    """Контракт Desktop-сборки OpenCode 1.18 (дебаг 2026-09-18):
    default export-функция, без Bun shell, CLI через node:child_process."""

    def test_default_экспорт_функция(self):
        """Загрузчик: все экспорты модуля обязаны быть функциями;
        фабрика — default export."""
        src = PLUGIN.read_text(encoding="utf-8")
        assert "export default" in src, \
            "фабрика обязана быть default export (named export отбрасывается молча)"

    def test_cli_через_child_process_не_bun_shell(self):
        """ctx.$ в Desktop === undefined — Bun shell недоступен."""
        src = PLUGIN.read_text(encoding="utf-8")
        assert "child_process" in src, "CLI зовётся через node:child_process"
        assert "execFile" in src
        assert "await $" not in src, "Bun shell $ в Desktop не работает"

    def test_gui_path_фолбэк_бинаря(self):
        """Desktop наследует дефолтный PATH без ~/.local/bin — плагин
        резолвит абсолютный фолбэк (existsSync, без сабпроцесса)."""
        src = PLUGIN.read_text(encoding="utf-8")
        assert "_curatorBin" in src, "резолв бинаря вынесен в функцию"
        assert '".local"' in src and '"bin"' in src and '"curator"' in src, \
            "фолбэк — ~/.local/bin/curator (uv/pipx)"
        assert "existsSync" in src, "проверка существования без сабпроцесса"

    def test_session_id_передаётся_в_env_cli(self):
        src = PLUGIN.read_text(encoding="utf-8")
        assert "CURATOR_SESSION_ID" in src, \
            "сессия OpenCode передаётся CLI через env execFile"
        assert "input.sessionID" in src, "источник — sessionID входа хука"

    def test_режим_доставки_не_читается_плагином(self):
        src = PLUGIN.read_text(encoding="utf-8")
        assert "CURATOR_DELIVERY_MODE" not in src, \
            "off/shadow/inject решает CLI; плагин не знает про режим"


class TestPluginLifecycle:
    """Жизненный цикл доставки (Task 10): inject — гард one-delivery-per-session;
    shadow — карточек нет, гард не трипится, каждый оборот наблюдается."""

    def test_inject_одна_доставка_на_сессию(self, tmp_path):
        result = _run_node(tmp_path, "inject")
        assert result["firstTurnDelivered"] is True, "карточка добавлена в parts"
        assert result["firstTurnCliCalls"] == 1
        assert result["secondTurnCliCalls"] == 0, \
            "после доставки сессия помечена — второго вызова CLI нет"
        assert result["secondTurnParts"] == 1, "второй оборот без доставки"

    def test_shadow_гард_никогда_не_срабатывает(self, tmp_path):
        result = _run_node(tmp_path, "shadow")
        assert result["cliCalls"] == 3, \
            "shadow возвращает пустой контракт — гард не трипится, каждый оборот наблюдается"
        assert result["appendedParts"] == 0, "shadow ничего не доставляет"
        assert result["sessionForwarded"] is True, \
            "каждый вызов CLI несёт CURATOR_SESSION_ID сессии"
