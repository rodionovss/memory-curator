"""Health-чеки живой интеграции OpenCode для curator status.

Пивот 2026-10-03: push-доставка и плагины удалены, MCP-сервер и worker
дорезаны окончательно — живой чек один: доступность бинаря CLI.
"""

import os
from pathlib import Path


def check_curator_bin() -> tuple[bool, str]:
    """Бинарь curator резолвится (GUI PATH не содержит ~/.local/bin —
    напоминание о недоступности для окружений без фолбэка)."""
    fallback = Path(os.environ.get("HOME", str(Path.home()))) / ".local" / "bin" / "curator"
    if fallback.exists():
        return True, f"бинарь: {fallback}"
    from shutil import which
    if which("curator"):
        return True, "бинарь в PATH"
    return False, "curator не найден ни в ~/.local/bin, ни в PATH"


def checks(state_dir: Path | None = None) -> list[tuple[bool, str]]:
    """Живые чеки интеграции OpenCode: [(ok, сообщение), ...]."""
    return [check_curator_bin()]
