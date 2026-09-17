"""Изолированный HOME для прогона opencode run без глобального сетапа.

Глобальный ~/.config/opencode содержит memory-curator-правила, MCP и плагины —
в routing-эксперименте они contamination-ят все руки. Изоляция:

- минимальный config: только $schema, model, provider (скопированные у юзера);
- symlink на auth.json (и account.json при наличии) — авторизация та же;
- никакой глобальный AGENTS.md / instructions / mcp / plugin не попадает в run.
"""

import json
import os
import re
import shutil
from pathlib import Path

_FILE_REF = re.compile(r"\{file:([^}]+)\}")


def _real_config() -> dict:
    path = Path.home() / ".config" / "opencode" / "opencode.json"
    return json.loads(path.read_text(encoding="utf-8"))


def build_isolated_home(base: Path, model: str) -> Path:
    """Создать <base>/home с минимальным opencode-конфигом под модель."""
    home = base / "home"
    config_dir = home / ".config" / "opencode"
    config_dir.mkdir(parents=True, exist_ok=True)

    real = _real_config()
    minimal = {
        "$schema": real.get("$schema", "https://opencode.ai/config.json"),
        "model": model,
        "provider": real.get("provider", {}),
    }
    (config_dir / "opencode.json").write_text(
        json.dumps(minimal, indent=2), encoding="utf-8"
    )

    # provider-конфиг ссылается на секреты как {file:~/.config/opencode/X}:
    # при подменённом HOME таких файлов нет — симлинкаем каждый в isolated home
    config_text = json.dumps(minimal)
    for ref in set(_FILE_REF.findall(config_text)):
        ref_path = ref.strip()
        if not ref_path.startswith("~/"):
            continue
        rel = ref_path[2:]
        src = Path.home() / rel
        if not src.exists():
            continue
        dst = home / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if not dst.exists():
            os.symlink(src.resolve(), dst)

    share = home / ".local" / "share" / "opencode"
    share.mkdir(parents=True, exist_ok=True)
    real_share = Path.home() / ".local" / "share" / "opencode"
    for name in ("auth.json", "account.json"):
        src = real_share / name
        if src.exists():
            dst = share / name
            if not dst.exists():
                os.symlink(src.resolve(), dst)

    return home


def isolated_env(home: Path) -> dict:
    """env для subprocess: HOME подменён, остальное наследуется."""
    env = dict(os.environ)
    env["HOME"] = str(home)
    return env


def cleanup_isolated_home(base: Path) -> None:
    """Удалить изолированный home, аккуратно обходя symlink-и."""
    home = base / "home"
    if not home.exists():
        return
    for link in (home / ".local" / "share" / "opencode").glob("*.json"):
        if link.is_symlink():
            link.unlink()
    shutil.rmtree(home, ignore_errors=True)
