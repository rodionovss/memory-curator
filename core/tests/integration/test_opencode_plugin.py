"""Контракт плагина OpenCode proactive delivery (issue #28, ADR 002).

Плагин — единственный поддерживаемый lifecycle hook (`chat.message`,
до генерации ответа). Контракт: изоляция от storage backend (только CLI
`curator context`), ошибки глушатся, доставка один раз на сессию,
ручной fallback (curator get) остаётся.
"""

import shutil
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
PLUGIN = REPO / "integrations" / "curator-context.js"


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

    def test_синтаксис_esm(self):
        node = shutil.which("node")
        if not node:
            import pytest
            pytest.skip("node недоступен")
        import subprocess
        tmp = PLUGIN.with_name(PLUGIN.stem + ".check.mjs")
        try:
            shutil.copy(PLUGIN, tmp)
            subprocess.run([node, "--check", str(tmp)], check=True, capture_output=True)
        finally:
            tmp.unlink(missing_ok=True)
