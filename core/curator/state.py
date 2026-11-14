"""Единый корень служебных файлов Memory Curator."""

import json
import os
from pathlib import Path

from curator.fs import atomic_write_text


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


def configured_base() -> str | None:
    """База знаний из state-конфига (пишет `curator install`).

    ~/.curator/config.json → {"base_dir": "<абсолютный путь>"}. Это
    единственная персистенция базы после ухода от MCP-секций: env
    CURATOR_BASE_DIR всегда выигрывает, state-конфиг — между env и
    дефолтом.
    """
    try:
        data = json.loads((state_dir() / "config.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    base = data.get("base_dir")
    if isinstance(base, str) and base.strip():
        return base.strip()
    return None


def write_configured_base(base_dir: str) -> None:
    """Записать базу в state-конфиг (создаёт ~/.curator при необходимости)."""
    path = state_dir() / "config.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            data = {}
    except (OSError, json.JSONDecodeError):
        data = {}
    data["base_dir"] = str(base_dir)
    atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def default_base_dir() -> str:
    """Нейтральный дефолт базы знаний (не привязан к машине автора).

    Цепочка резолва везде одна: env CURATOR_BASE_DIR >
    configured_base() (state-конфиг) > default_base_dir().
    """
    return os.path.expanduser("~/memory-curator")
