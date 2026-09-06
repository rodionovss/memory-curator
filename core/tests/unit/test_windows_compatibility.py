"""Регрессии запуска Memory Curator на Windows."""

import os
import subprocess
import sys
from pathlib import Path

import pytest


pytestmark = pytest.mark.skipif(os.name != "nt", reason="проверка только для Windows")


def test_server_module_imports_on_windows(tmp_path):
    """MCP-сервер обязан импортироваться без Unix-only зависимостей."""
    core_dir = Path(__file__).resolve().parents[2]

    env = os.environ.copy()
    env.update({
        "CURATOR_STATE_DIR": str(tmp_path / ".curator"),
        "CURATOR_BASE_DIR": str(tmp_path / "memory"),
        "CURATOR_AUTO_WORKER": "false",
    })
    result = subprocess.run(
        [sys.executable, "-c", "import curator.server"],
        cwd=core_dir,
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )

    assert result.returncode == 0, result.stderr


def test_worker_process_is_recognized_on_windows():
    """Живой worker из pid-файла не должен запускаться повторно."""
    from curator import daemon

    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)", "-m", "curator.worker"]
    )
    try:
        assert daemon.pid_is_curator_worker(proc.pid) is True
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def test_mcp_stdio_handshake_with_auto_worker_on_windows(tmp_path):
    """Проверка worker не должна обрывать MCP-процесс сигналом Ctrl+C."""
    core_dir = Path(__file__).resolve().parents[2]
    script = """
import asyncio
import os
import sys
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

async def check():
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "curator.server"],
        env=os.environ.copy(),
        cwd=os.getcwd(),
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write, read_timeout_seconds=5) as session:
            result = await session.initialize()
            tools = await session.list_tools()
            assert result.server_info.name == "memory-curator"
            assert any(tool.name == "curator_status" for tool in tools.tools)

from curator.daemon import stop_worker
try:
    asyncio.run(check())
finally:
    stop_worker()
"""
    env = os.environ.copy()
    env.update({
        "USERPROFILE": str(tmp_path),
        "CURATOR_STATE_DIR": str(tmp_path / ".curator"),
        "CURATOR_BASE_DIR": str(tmp_path / "memory"),
        "CURATOR_AUTO_WORKER": "true",
    })

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=core_dir,
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )

    assert result.returncode == 0, result.stderr


def test_cli_status_works_with_cp1251_console(tmp_path):
    """Unicode-значки не должны ронять CLI в стандартной Windows-консоли."""
    env = os.environ.copy()
    env.update({
        "USERPROFILE": str(tmp_path),
        "CURATOR_STATE_DIR": str(tmp_path / ".curator"),
        "CURATOR_BASE_DIR": str(tmp_path / "memory"),
        "PYTHONIOENCODING": "cp1251",
    })

    result = subprocess.run(
        [sys.executable, "-m", "curator.control", "status"],
        env=env,
        capture_output=True,
        timeout=15,
    )

    assert result.returncode == 0, result.stderr.decode("cp1251")
    assert "Worker:" in result.stdout.decode("cp1251")
