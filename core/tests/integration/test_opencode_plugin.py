"""Контракт плагина OpenCode proactive delivery (issue #28, ADR 002).

Плагин — единственный поддерживаемый lifecycle hook (`chat.message`,
до генерации ответа). Контракт: изоляция от storage backend (только CLI
`curator context`), ошибки глушатся, доставка один раз на сессию,
ручной fallback (curator get) остаётся.

Task 10: плагин форвардит CURATOR_SESSION_ID в env подпроцесса CLI;
режим доставки читает CLI, не плагин. Shadow: CLI не возвращает карточки
→ гард one-delivery-per-session никогда не срабатывает → каждый
substantive turn наблюдается. Inject: карточка добавлена → сессия
помечена delivered → повторный вызов CLI не происходит.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
PLUGIN = REPO / "integrations" / "curator-context.js"

# Поведенческий драйвер: подделываем $ (Bun Shell) объектом
# {exitCode, stdout} — реальный контракт вывода opencode (Bun.$),
# и прогоняем оба сценария жизненного цикла плагина.
_DRIVER = r"""
const [,, pluginPath, scenario] = process.argv
const calls = []

function makeFake$(response) {
  return (strings, ...values) => {
    const cmd = strings.reduce((acc, s, i) => acc + s + (i < values.length ? String(values[i]) : ""), "")
    calls.push(cmd)
    return {
      quiet() { return this },
      nothrow() { return this },
      then(resolve, reject) { return Promise.resolve(response).then(resolve, reject) },
    }
  }
}

function output(text) {
  return { parts: [{ type: "text", text }] }
}

const { pathToFileURL } = await import("node:url")
const mod = await import(pathToFileURL(pluginPath).href)
const sessionId = "ses_node_1"
const card = { title: "T", summary: "s", tags: [], type: "Reference",
               status: "verified", source_file: "a.md", score: 0.8, reason: "r" }

if (scenario === "inject") {
  const plugin = await mod.CuratorContext({ $: makeFake$({ exitCode: 0, stdout: JSON.stringify({ cards: [card], count: 1 }) }) })
  const out1 = output("задача один")
  await plugin["chat.message"]({ sessionID: sessionId }, out1)
  const afterFirst = { calls: calls.length, parts: out1.parts.length }
  const out2 = output("задача два")
  await plugin["chat.message"]({ sessionID: sessionId }, out2)
  console.log(JSON.stringify({
    firstTurnDelivered: afterFirst.parts === 2,
    firstTurnCliCalls: afterFirst.calls,
    secondTurnCliCalls: calls.length - afterFirst.calls,
    secondTurnParts: out2.parts.length,
  }))
} else {
  const plugin = await mod.CuratorContext({ $: makeFake$({ exitCode: 0, stdout: JSON.stringify({ cards: [], count: 0 }) }) })
  const outs = [output("a"), output("b"), output("c")]
  for (const o of outs) await plugin["chat.message"]({ sessionID: sessionId }, o)
  console.log(JSON.stringify({
    cliCalls: calls.length,
    appendedParts: outs.reduce((n, o) => n + o.parts.length, 0) - outs.length,
    sessionForwarded: calls.length > 0 && calls.every((c) => c.includes("CURATOR_SESSION_ID=" + sessionId)),
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
    proc = subprocess.run(
        [node, str(driver), str(plugin_mjs), scenario],
        check=True, capture_output=True, text=True, timeout=30,
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
        assert "curator context" in src, "доставка через CLI-контракт ADR 002"

    def test_ошибки_глушатся(self):
        src = PLUGIN.read_text(encoding="utf-8")
        assert "try {" in src and "catch" in src

    def test_одна_доставка_на_сессию(self):
        src = PLUGIN.read_text(encoding="utf-8")
        assert "deliveredSessions" in src

    def test_ручной_fallback_упомянут(self):
        src = PLUGIN.read_text(encoding="utf-8")
        assert "curator get" in src

    def test_gui_path_фолбэк_бинаря(self):
        """Desktop OpenCode наследует дефолтный PATH без ~/.local/bin —
        голое имя curator даёт exit 127 и глушится. Плагин резолвит
        абсолютный фолбэк до вызова (existsSync, без сабпроцесса)."""
        src = PLUGIN.read_text(encoding="utf-8")
        assert "_curatorBin" in src, "резолв бинаря вынесен в функцию"
        assert '".local"' in src and '"bin"' in src and '"curator"' in src, \
            "фолбэк — ~/.local/bin/curator (uv/pipx)"
        assert "existsSync" in src, "проверка существования без сабпроцесса"

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


class TestModeForwardingContract:
    """Task 10: session id форвардится в env CLI; режим читает CLI, не плагин."""

    def test_session_id_форвардится_в_cli(self):
        src = PLUGIN.read_text(encoding="utf-8")
        assert "CURATOR_SESSION_ID" in src, \
            "сессия OpenCode передаётся CLI через env"
        assert "input.sessionID" in src, "источник — sessionID входа хука"

    def test_режим_доставки_не_читается_плагином(self):
        src = PLUGIN.read_text(encoding="utf-8")
        assert "CURATOR_DELIVERY_MODE" not in src, \
            "off/shadow/inject решает CLI; плагин не знает про режим"

    def test_один_spawn_на_субстантивный_оборот(self):
        src = PLUGIN.read_text(encoding="utf-8")
        assert src.count("await $`") == 1, \
            "контракт — один вызов curator context на substantive turn"


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
