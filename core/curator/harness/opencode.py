"""Health-чеки живой интеграции OpenCode для curator status.

Каждый чек закрывает конкретный режим отказа, найденный дебагом
2026-09-18 (см. reference/opencode.md личной базы):
плагины не зарегистрированы, копия на диске устарела, env не доходит
до GUI, бинарь вне PATH, shadow-лог не растёт.
"""

import json
import os
from datetime import datetime, timedelta
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _opencode_dir() -> Path:
    home = Path(os.environ.get("HOME", str(Path.home())))
    return home / ".config" / "opencode"


def check_plugins_sync() -> tuple[bool, str]:
    """Плагины на диске совпадают с версиями репо."""
    plugins_dir = _opencode_dir() / "plugins"
    names = ("curator-context.js", "curator-reminder.js")
    stale, missing = [], []
    for name in names:
        source = _repo_root() / "integrations" / name
        target = plugins_dir / name
        if not target.exists():
            missing.append(name)
        elif source.exists() and target.read_text(encoding="utf-8") != source.read_text(encoding="utf-8"):
            stale.append(name)
    if missing:
        return False, f"плагины не установлены: {', '.join(missing)} — curator install"
    if stale:
        return False, f"копии на диске устарели: {', '.join(stale)} — curator install"
    return True, "плагины на диске = версии репо"


def check_plugins_registered() -> tuple[bool, str]:
    """Плагины прописаны абсолютными путями в plugin[] opencode.json.

    Desktop-сборка OpenCode 1.18 не автозагружает ~/.config/opencode/plugins/.
    """
    config_path = _opencode_dir() / "opencode.json"
    if not config_path.exists():
        return False, f"{config_path} не найден — плагины не зарегистрированы"
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        return False, f"{config_path} не читается: {e}"
    plugins = [p for p in config.get("plugin", []) if isinstance(p, str)]
    plugins_dir = _opencode_dir() / "plugins"
    unregistered = [
        name for name in ("curator-context.js", "curator-reminder.js")
        if not any(p == str(plugins_dir / name) for p in plugins)
    ]
    if unregistered:
        return False, (
            f"не в plugin[]: {', '.join(unregistered)} — абсолютный путь "
            f"в plugin[] ({plugins_dir}/<имя>.js), иначе Desktop их не грузит"
        )
    return True, "плагины зарегистрированы в plugin[]"


def check_curator_bin() -> tuple[bool, str]:
    """Бинарь curator резолвится (GUI PATH не содержит ~/.local/bin —
    плагин сам фолбэкится на абсолютный путь; чек предупреждает о
    недоступности для окружения без фолбэка)."""
    fallback = Path(os.environ.get("HOME", str(Path.home()))) / ".local" / "bin" / "curator"
    if fallback.exists():
        return True, f"бинарь: {fallback}"
    from shutil import which
    if which("curator"):
        return True, "бинарь в PATH"
    return False, "curator не найден ни в ~/.local/bin, ни в PATH"


def check_delivery_mode() -> tuple[bool, str]:
    """CURATOR_DELIVERY_MODE задан (off — телеметрия не собирается)."""
    mode = (os.getenv("CURATOR_DELIVERY_MODE") or "").strip().lower()
    if mode in ("shadow", "inject"):
        return True, f"режим доставки: {mode}"
    hint = "launchctl setenv CURATOR_DELIVERY_MODE shadow" if mode == "" else f"неизвестный режим '{mode}'"
    return False, f"CURATOR_DELIVERY_MODE не задан — {hint}"


def check_shadow_log(state_dir: Path) -> tuple[bool, str]:
    """Shadow-лог растёт: есть записи за последние 24 часа."""
    log = state_dir / "delivery-shadow.jsonl"
    if not log.exists():
        return False, f"{log} не существует — доставки не было ни разу"
    try:
        lines = log.read_text(encoding="utf-8").strip().splitlines()
    except OSError as e:
        return False, f"{log} не читается: {e}"
    if not lines:
        return False, f"{log} пуст — доставки не было ни разу"
    day_ago = datetime.now() - timedelta(days=1)
    recent = 0
    last_session = ""
    for line in reversed(lines):
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        ts = event.get("ts")
        when = None
        if ts:
            try:
                when = datetime.fromisoformat(str(ts))
            except ValueError:
                pass
        if when is None:
            # mtime файла — оценка снизу: лог append-only, последняя строка свежее
            when = datetime.fromtimestamp(log.stat().st_mtime)
        if when >= day_ago:
            recent += 1
        if not last_session and event.get("session_id"):
            last_session = str(event["session_id"])
    if recent == 0:
        return False, (
            "shadow-лог: нет записей за 24ч — телеметрия мертва; чек плагинов "
            "и режим доставки выше, доставка = плагин → CLI → лог"
        )
    return True, f"shadow-лог: {recent} записей за 24ч (последняя сессия {last_session[:16]})"


def checks(state_dir: Path | None = None) -> list[tuple[bool, str]]:
    """Все чеки интеграции OpenCode: [(ok, сообщение), ...]."""
    from curator.state import state_dir as default_state_dir
    checks = [
        check_plugins_sync(),
        check_plugins_registered(),
        check_curator_bin(),
        check_delivery_mode(),
    ]
    checks.append(check_shadow_log(state_dir or default_state_dir()))
    return checks
