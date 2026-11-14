"""Регрессии запуска Memory Curator на Windows."""

import os
import subprocess
import sys
from pathlib import Path

import pytest


pytestmark = pytest.mark.skipif(os.name != "nt", reason="проверка только для Windows")


def test_cli_module_imports_on_windows(tmp_path):
    """CLI обязан импортироваться без Unix-only зависимостей."""
    core_dir = Path(__file__).resolve().parents[2]

    env = os.environ.copy()
    env.update({
        "CURATOR_STATE_DIR": str(tmp_path / ".curator"),
        "CURATOR_BASE_DIR": str(tmp_path / "memory"),
    })
    result = subprocess.run(
        [sys.executable, "-c", "import curator.control; import curator.installer"],
        cwd=core_dir,
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
