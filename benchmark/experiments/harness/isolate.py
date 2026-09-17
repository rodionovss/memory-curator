"""Изолированный HOME для прогона opencode run без глобального сетапа.

Глобальный ~/.config/opencode содержит memory-curator-правила, MCP и плагины —
в routing-эксперименте они contamination-ят все руки. Изоляция:

- минимальный config: только $schema, model, provider (скопированные у юзера);
- symlink на auth.json (и account.json при наличии) — авторизация та же;
- никакой глобальный AGENTS.md / instructions / plugin не попадает в run;
- mcp — только явным параметром (эксперименты 02/03, руки с curator MCP).
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


def build_isolated_home(base: Path, model: str, mcp: dict | None = None) -> Path:
    """Создать <base>/home с минимальным opencode-конфигом под модель.

    mcp: словарь mcp-записей ({"memory-curator": {...}}) — включается в
    конфиг как поле "mcp" только когда передан (эксперименты 02/03).
    """
    home = base / "home"
    config_dir = home / ".config" / "opencode"
    config_dir.mkdir(parents=True, exist_ok=True)

    real = _real_config()
    minimal = {
        "$schema": real.get("$schema", "https://opencode.ai/config.json"),
        "model": model,
        "provider": real.get("provider", {}),
    }
    if mcp is not None:
        minimal["mcp"] = mcp
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


def isolated_env(home: Path, extra: dict | None = None) -> dict:
    """env для subprocess: HOME подменён, остальное наследуется, extra мержится."""
    env = dict(os.environ)
    env["HOME"] = str(home)
    if extra:
        env.update({k: str(v) for k, v in extra.items()})
    return env


def curator_mcp_entry(db_path: Path) -> dict:
    """Точная mcp-запись "memory-curator" из реального конфига + CURATOR_DB_PATH.

    Копия не мутирует источник. CURATOR_DB_PATH добавляется в environment
    записи: MCP-сервер (MEMORY_BACKEND=local) читает базу из этого env.
    """
    real = _real_config()
    entry = real.get("mcp", {}).get("memory-curator")
    if not entry:
        raise RuntimeError(
            "mcp.memory-curator отсутствует в ~/.config/opencode/opencode.json — "
            "руки P1/P2 с curator MCP запустить нельзя"
        )
    entry = json.loads(json.dumps(entry))
    entry.setdefault("environment", {})["CURATOR_DB_PATH"] = str(db_path)
    return {"memory-curator": entry}


def cleanup_isolated_home(base: Path) -> None:
    """Удалить изолированный home, аккуратно обходя symlink-и."""
    home = base / "home"
    if not home.exists():
        return
    for link in (home / ".local" / "share" / "opencode").glob("*.json"):
        if link.is_symlink():
            link.unlink()
    shutil.rmtree(home, ignore_errors=True)
