"""Управление фоновым worker-демоном (improve loop).

pid-файл и лог живут в CURATOR_STATE_DIR (default: ~/.curator). Инвариант: worker жив, пока жив
MCP-сервер — server.main() зовёт ensure_worker(). `curator start` —
тот же ensure (идемпотентный): живой наш worker → ничего не делает,
мёртвый/чужой/отсутствующий pid → подчистка pid-файла и запуск.
"""

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from curator.state import state_path


def _pid_file() -> Path:
    return state_path("worker.pid")


def _worker_log() -> Path:
    return state_path("worker.log")


def read_pid() -> int | None:
    pid_file = _pid_file()
    if not pid_file.exists():
        return None
    try:
        return int(pid_file.read_text().strip())
    except (ValueError, OSError):
        return None


def is_running(pid: int) -> bool:
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel32.GetExitCodeProcess.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

        handle = kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        try:
            exit_code = wintypes.DWORD()
            return bool(kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))) and exit_code.value == 259
        finally:
            kernel32.CloseHandle(handle)

    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, OSError):
        return False


def pid_is_curator_worker(pid: int) -> bool:
    """Верификация перед kill: pid-файл мог протухнуть, ОС переиспользовала pid.

    Матчим точные токены командной строки: `python -m curator.worker`
    (как запускает start_worker) и entrypoint `curator-worker`. Подстрочные
    совпадения (`rg curator.worker`, `tail -f curator.worker.log`) — нет.
    """
    if os.name == "nt":
        command = [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            f"(Get-CimInstance Win32_Process -Filter 'ProcessId = {int(pid)}').CommandLine",
        ]
    else:
        command = ["ps", "-p", str(pid), "-o", "command="]

    try:
        out = subprocess.run(
            command,
            capture_output=True, text=True, timeout=5,
        )
    except Exception:
        return False
    tokens = [token.strip('"') for token in out.stdout.split()]
    for i, tok in enumerate(tokens):
        if tok == "-m" and i + 1 < len(tokens) and tokens[i + 1] == "curator.worker":
            return True
        normalized = tok.replace("\\", "/").lower()
        if normalized == "curator-worker" or normalized.endswith("/curator-worker"):
            return True
        if normalized == "curator-worker.exe" or normalized.endswith("/curator-worker.exe"):
            return True
    return False


def start_worker() -> str:
    """Запустить worker-демон, вернуть человекочитаемый статус."""
    pid_file = _pid_file()
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    interval = os.getenv("IMPROVE_INTERVAL_MINUTES", "1440")

    worker_cmd = [sys.executable, "-m", "curator.worker", "--daemon"]
    env = os.environ.copy()
    env["IMPROVE_INTERVAL_MINUTES"] = interval

    log_file = _worker_log()
    from datetime import datetime
    with open(log_file, "a") as log:
        log.write(f"\n[{datetime.now().isoformat()}] Starting worker...\n")
        proc = subprocess.Popen(
            worker_cmd, env=env,
            stdout=log, stderr=log,
            start_new_session=True,
        )
        pid_file.write_text(str(proc.pid))

    time.sleep(0.5)
    if is_running(proc.pid):
        return f"✅ Worker запущен (pid {proc.pid}, интервал {interval} мин, лог {log_file})"
    return f"❌ Worker не запустился. Проверьте лог: {log_file}"


def ensure_worker(spawn=None) -> str:
    """Инвариант «worker жив»: идемпотентный запуск.

    Живой наш worker → ничего не делает. Мёртвый или чужой (pid
    переиспользован ОС) pid-файл → подчистка + запуск. `spawn` — точка
    подмены для тестов.
    """
    spawn = spawn or start_worker
    pid_file = _pid_file()
    pid = read_pid()
    if pid and is_running(pid) and pid_is_curator_worker(pid):
        return f"Worker уже запущен (pid {pid})"
    if pid:
        pid_file.unlink(missing_ok=True)
    return spawn()


def stop_worker() -> str:
    pid_file = _pid_file()
    pid = read_pid()
    if not pid:
        return "Worker не запущен."
    if not is_running(pid):
        pid_file.unlink(missing_ok=True)
        return f"Процесс {pid} не существует. Удаляю pid-файл."
    if not pid_is_curator_worker(pid):
        pid_file.unlink(missing_ok=True)
        return (f"Процесс {pid} не похож на curator-worker (pid переиспользован ОС?) "
                f"— не убиваю, удаляю pid-файл.")
    os.kill(pid, signal.SIGTERM)
    time.sleep(0.5)
    if is_running(pid):
        os.kill(pid, signal.SIGKILL)
        time.sleep(0.3)
    pid_file.unlink(missing_ok=True)
    return f"✅ Worker остановлен (pid {pid})"
