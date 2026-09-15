"""Установщик Memory Curator: opencode / Claude Code.

Одна команда, ноль вопросов:

    curator install

Автодетект: находит opencode и Claude Code на машине и ставит во всё
найденное (идемпотентно). Ничего не найдено — opencode-раскладка с
подсказкой. База знаний — молчаливый дефолт ~/memory-curator; где она
лежит — `curator status`, смена — попроси агента в opencode поправить
env CURATOR_BASE_DIR в конфиге (или руками). Флаги — только явные
переопределения для скриптов: --opencode, --claude, --base-dir ПУТЬ.
"""

import json
import os
import re
import shutil
import sys
from pathlib import Path


_RETIRED_COMMANDS = ("curator-project-save",)
_RETIRED_SKILLS = ("curator-project-save",)


def _server_command() -> tuple[str, list[str]]:
    """(command, args) запуска MCP-сервера из этого окружения.

    Prefer готовый entrypoint-скрипт в venv; editable-окружение без
    скрипта откатывается на `python -m curator.server`.
    """
    exe_dir = Path(sys.executable).parent
    candidate = exe_dir / "curator-mcp-server"
    if candidate.exists():
        return str(candidate), []
    return sys.executable, ["-m", "curator.server"]


def default_base_dir() -> str:
    """Дефолт базы знаний — нейтральный путь (не привязан к машине автора)."""
    return os.path.expanduser("~/memory-curator")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _install_skills(dest_root: Path) -> list[Path]:
    """Скопировать ВСЕ скиллы из репо (curator-save, mapping-documentation,
    curator-update-docs и будущие) в <dest_root>/. wheel-установка без репо — пусто."""
    for name in _RETIRED_SKILLS:
        retired = dest_root / name
        if retired.is_symlink() or retired.is_file():
            retired.unlink()
        elif retired.exists():
            shutil.rmtree(retired)
    skills_root = _repo_root() / ".agents" / "skills"
    if not skills_root.is_dir():
        return []
    installed = []
    for source in sorted(skills_root.iterdir()):
        if not (source / "SKILL.md").exists():
            continue
        dest = dest_root / source.name
        if dest.is_symlink():
            # симлинк (например, из ранней ручной установки) нельзя rmtree — только unlink
            dest.unlink()
        elif dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(source, dest)
        installed.append(dest)
    return installed


_RULES_BEGIN = "<!-- memory-curator:begin -->"
_RULES_END = "<!-- memory-curator:end -->"


def _rules_section() -> str:
    """Текст правил памяти из репо (integrations/curator-rules.md)."""
    path = _repo_root() / "integrations" / "curator-rules.md"
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _install_global_rules(rules_path: Path, body: str) -> bool:
    """Секция Memory Curator в глобальный файл правил (AGENTS.md / CLAUDE.md).

    Read-side без хуков: правило «сверяйся с базой» попадает в контекст
    каждой сессии. Файла может не быть — создаём; чужой контент не трогаем,
    заменяем только свою секцию между маркерами (идемпотентно).
    """
    if not body:
        return False
    existing = rules_path.read_text(encoding="utf-8") if rules_path.exists() else ""
    pattern = re.compile(re.escape(_RULES_BEGIN) + r".*?" + re.escape(_RULES_END) + r"\n?", re.DOTALL)
    without_ours = pattern.sub("", existing).rstrip()
    section = f"{_RULES_BEGIN}\n{body}\n{_RULES_END}"
    rules_path.parent.mkdir(parents=True, exist_ok=True)
    rules_path.write_text(without_ours + ("\n\n" if without_ours else "") + section + "\n", encoding="utf-8")
    return True


def _install_plugin(plugins_dir: Path) -> bool:
    """Плагин-реминдер (session.idle → нотификация) в каталог плагинов opencode."""
    source = _repo_root() / "integrations" / "curator-reminder.js"
    if not source.exists():
        return False
    plugins_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, plugins_dir / source.name)
    return True


def _commands_source() -> dict:
    """Команды (/curator-*) из репо — источник правды для opencode и Claude Code."""
    path = _repo_root() / "integrations" / "commands.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _read_json_config(config_path: Path) -> tuple[dict | None, str | None]:
    if not config_path.exists():
        return {}, None
    try:
        text = config_path.read_text(encoding="utf-8")
    except OSError as e:
        return None, f"не смог прочитать {config_path} ({e})"
    # Конфиги правят руками → jsonc-хвосты (запятая перед } или ]) встречаются;
    # строгий json.loads на них падает. Читаем снисходительно, записываем
    # обратно чистым JSON — заодно вылечиваем конфиг.
    text = re.sub(r",(\s*[}\]])", r"\1", text)
    try:
        config = json.loads(text)
    except json.JSONDecodeError as e:
        return None, f"не смог прочитать {config_path} ({e}) — боюсь сломать твой конфиг, добавь секции руками"
    if not isinstance(config, dict):
        return None, f"{config_path} не JSON-объект — добавь секции руками"
    return config, None


def _write_json_config(config_path: Path, config: dict) -> None:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _mcp_entry_opencode(base_dir: str, existing_env: dict | None = None) -> dict:
    """MCP-секция по официальной схеме opencode (opencode.ai/docs/mcp-servers):
    command — МАССИВ (команда и аргументы), переменные окружения — ключ
    environment (не env), type/enabled обязательны. Отклонение от схемы =
    молча не стартовавший сервер (не видно в списке MCP)."""
    command, args = _server_command()
    return {
        "type": "local",
        "enabled": True,
        "command": [command, *args],
        "environment": _mcp_env(base_dir, existing_env),
    }


def _mcp_entry_claude(base_dir: str, existing_env: dict | None = None) -> dict:
    """Формат Claude Code (.mcp.json): command (строка) + args + env —
    своя схема, type/environment не нужны."""
    command, args = _server_command()
    return {
        "command": command,
        **({"args": args} if args else {}),
        "env": _mcp_env(base_dir, existing_env),
    }


def _mcp_env(base_dir: str, existing_env: dict | None = None) -> dict:
    env = dict(existing_env or {})
    env.setdefault("MEMORY_BACKEND", "local")
    env.update({
        "CURATOR_BASE_DIR": base_dir,
        # MapRouter без карты молча = дефолт (session/{type}.md);
        # карта появится в базе — маршрутизация по темам включится сама
        "ROUTER_CLASS": "curator.routing.map_router.MapRouter",
    })
    return env


def detect_harnesses() -> tuple[bool, bool]:
    """(opencode, claude) — что найдено на машине."""
    home = Path(os.environ.get("HOME", str(Path.home())))
    has_opencode = (home / ".config" / "opencode").is_dir()
    has_claude = (home / ".claude").is_dir() or (home / ".claude.json").exists()
    return has_opencode, has_claude


def _effective_base(config: dict, section: str, key: str, base_dir: str | None) -> str:
    """База для записи в конфиг.

    Патч (повторный install) не имеет права сбрасывать существующую
    настройку: без явного --base-dir сохраняем CURATOR_BASE_DIR из
    установленной секции; флаг — осознанное переопределение; свежая
    установка — дефолт.
    """
    if base_dir:
        return base_dir
    try:
        entry = config.get(section, {}).get(key, {})
        # совместимость: старые ручные конфиги держали env, схема opencode — environment
        env = entry.get("environment") or entry.get("env") or {}
        existing = env.get("CURATOR_BASE_DIR")
        if existing:
            return str(existing)
    except AttributeError:
        pass
    return default_base_dir()


def _install_footer() -> list[str]:
    return [
        "",
        "Готово. Перезапусти opencode / Claude Code — появятся команды /curator-*, "
        "тулзы curator_*, скиллы, правила памяти и плагин-реминдер.",
        "База: дефолт ~/memory-curator, существующая настройка сохраняется при обновлении.",
        "Где база сейчас: curator status · смена: попроси агента «смени базу знаний на <путь>»",
    ]


def install_all(target: str | None = None, base_dir: str | None = None) -> list[str]:
    """Установка без вопросов: автодетект → ставим во всё найденное."""
    do_opencode, do_claude = detect_harnesses()
    steps: list[str] = []

    if target == "opencode":
        do_opencode, do_claude = True, False
    elif target == "claude":
        do_opencode, do_claude = False, True
    elif not do_opencode and not do_claude:
        do_opencode = True
        steps.append("◦ opencode / Claude Code не обнаружены — ставлю opencode-раскладку")
        steps.append("  (для Claude Code потом: curator install --claude)")

    if do_opencode:
        steps.extend(_install_opencode_steps(base_dir))
    if do_claude:
        if do_opencode:
            steps.append("")
        steps.extend(_install_claude_steps(base_dir))

    steps.extend(_install_footer())
    return steps


def _install_opencode_steps(base_dir: str | None) -> list[str]:
    """MCP + команды + скиллы + worker в ~/.config/opencode (без футера)."""
    home = Path(os.environ.get("HOME", str(Path.home())))

    config_path = home / ".config" / "opencode" / "opencode.json"
    config, error = _read_json_config(config_path)
    if config is None:
        return [f"⛔ opencode: {error}"]
    base = _effective_base(config, "mcp", "memory-curator", base_dir)
    previous = config.get("mcp", {}).get("memory-curator", {})
    previous_env = previous.get("environment") or previous.get("env") or {}
    config.setdefault("mcp", {})["memory-curator"] = _mcp_entry_opencode(base, previous_env)
    commands = _commands_source()
    installed_commands = config.setdefault("command", {})
    for name in _RETIRED_COMMANDS:
        installed_commands.pop(name, None)
    if commands:
        installed_commands.update(commands)
    _write_json_config(config_path, config)
    steps = [f"✅ opencode: MCP-сервер и {len(commands)} команд /curator-*: {config_path} (остальное не тронуто)",
             f"✅ opencode: база знаний: {base}"]

    skills = _install_skills(home / ".config" / "opencode" / "skills")
    if skills:
        steps.append(f"✅ opencode: скиллы {', '.join(s.name for s in skills)}")
    else:
        steps.append("⚠ скиллы не найдены в репо (wheel-установка?) — MCP и команды работают")

    if _install_global_rules(home / ".config" / "opencode" / "AGENTS.md", _rules_section()):
        steps.append("✅ opencode: правила памяти в глобальном AGENTS.md — база в контексте каждой сессии")
    if _install_plugin(home / ".config" / "opencode" / "plugins"):
        steps.append("✅ opencode: плагин-реминдер session.idle → /curator-save")

    try:
        from curator.daemon import ensure_worker
        steps.append(f"✅ Worker: {ensure_worker()}")
    except Exception as e:
        steps.append(f"⚠ worker не поднялся: {e} — запусти позже: curator start")
    return steps


def _install_claude_steps(base_dir: str | None) -> list[str]:
    """.mcp.json в проекте (cwd) + слэш-команды ~/.claude/commands + скиллы (без футера)."""
    home = Path(os.environ.get("HOME", str(Path.home())))
    project = Path.cwd()

    mcp_path = project / ".mcp.json"
    config, error = _read_json_config(mcp_path)
    if config is None:
        return [f"⛔ Claude Code: {error}"]
    base = _effective_base(config, "mcpServers", "memory-curator", base_dir)
    previous = config.get("mcpServers", {}).get("memory-curator", {})
    previous_env = previous.get("env") or previous.get("environment") or {}
    config.setdefault("mcpServers", {})["memory-curator"] = _mcp_entry_claude(base, previous_env)
    _write_json_config(mcp_path, config)
    steps = [f"✅ Claude Code: MCP-сервер: {mcp_path}",
             f"✅ Claude Code: база знаний: {base}"]

    commands = _commands_source()
    commands_dir = home / ".claude" / "commands"
    if commands_dir.exists():
        for name in _RETIRED_COMMANDS:
            retired = commands_dir / f"{name}.md"
            if retired.exists():
                retired.unlink()
    if commands:
        commands_dir.mkdir(parents=True, exist_ok=True)
        for name, spec in commands.items():
            description = spec.get("description", "")
            template = spec.get("template", "")
            (commands_dir / f"{name}.md").write_text(
                f"---\ndescription: {description}\n---\n\n{template}\n",
                encoding="utf-8",
            )
        steps.append(f"✅ Claude Code: слэш-команды: {len(commands)} в {commands_dir}")

    skills = _install_skills(home / ".claude" / "skills")
    if skills:
        steps.append(f"✅ Claude Code: скиллы {', '.join(s.name for s in skills)}")
    else:
        steps.append("⚠ скиллы не найдены в репо (wheel-установка?) — MCP и команды работают")

    if _install_global_rules(home / ".claude" / "CLAUDE.md", _rules_section()):
        steps.append("✅ Claude Code: правила памяти в ~/.claude/CLAUDE.md (хуков до спринта нет — правила вместо них)")
    return steps
