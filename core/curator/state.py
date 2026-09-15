"""Единый корень служебных файлов Memory Curator."""

import os
from pathlib import Path


def state_dir() -> Path:
    configured = os.getenv("CURATOR_STATE_DIR", "").strip()
    if configured:
        return Path(configured).expanduser()
    home = os.environ.get("HOME", "")
    if home and (os.name != "nt" or Path(home).drive):
        return Path(home) / ".curator"
    return Path.home() / ".curator"


def state_path(name: str) -> Path:
    return state_dir() / name


def env_path(variable: str, name: str) -> Path:
    configured = os.getenv(variable, "").strip()
    return Path(configured).expanduser() if configured else state_path(name)
