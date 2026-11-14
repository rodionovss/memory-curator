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

from curator.fs import atomic_write_text


_RETIRED_COMMANDS = ("curator-project-save", "curator-setup",
                     "curator-start", "curator-stop", "curator-worker",
                     "curator-report", "curator-full")
_RETIRED_SKILLS = ("curator-project-save",)
# Синхронен control.KNOWLEDGE_ROUTES_CATALOG_NAME (локальная копия — без импорта control)
_ROUTES_CATALOG_NAME = "knowledge-routes.md"

# Дефолтная карта для нового пользователя: стандартная структура базы,
# правка опциональна. Формат — скилл mapping-documentation (MapRouter).
_DEFAULT_MAP_TEMPLATE = """---
title: Карта знаний — маршрутизация фактов по темам базы
on_unmatched: report

topics:
  - name: reference
    watch_for: kotlin, android, compose, архитектура, тесты, производительность
    targets:
      - path: "reference/general.md"
        captures: [knowledge]
        mode: update
        instructions: "Справочные знания: языки, платформа, архитектура, тесты"
  - name: style
    watch_for: стиль, код, ревью, процесс, коммиты
    targets:
      - path: "style/general.md"
        captures: [knowledge]
        mode: update
        instructions: "Правила стиля кода, ревью и рабочего процесса"
  - name: tools
    watch_for: инструмент, tool, cli, терминал, настройка
    targets:
      - path: "tools/general.md"
        captures: [knowledge]
        mode: update
        instructions: "Заметки об инструментах разработки"
  - name: agent-memory
    watch_for: память, память агента, знания, база
    targets:
      - path: "reference/agent-memory.md"
        captures: [knowledge]
        mode: update
        instructions: "Знания о памяти агентов и базах знаний"
---
"""


def _ensure_default_map(base: str) -> bool:
    """Дефолтная knowledge-map.md, если карты ещё нет.

    True — карта создана; False — уже есть (не трогаем: существующая
    карта — источник истины пользователя) или база недоступна для
    записи (карта опциональна: save работает и без неё, в session/)."""
    map_path = Path(os.path.abspath(os.path.expanduser(base))) / "knowledge-map.md"
    if map_path.exists():
        return False
    try:
        map_path.parent.mkdir(parents=True, exist_ok=True)
        map_path.write_text(_DEFAULT_MAP_TEMPLATE, encoding="utf-8")
    except OSError:
        return False
    return True


def default_base_dir() -> str:
    """Дефолт базы знаний — нейтральный путь (не привязан к машине автора)."""
    from curator.state import default_base_dir as _default
    return _default()


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _install_skills(dest_root: Path, mode: str = "preserve") -> list[Path]:
    """Установить все skills из репо в ``dest_root``.

    ``preserve`` сохраняет существующие dev symlink-и, ``link`` создаёт
    symlink-и на source, ``copy`` создаёт управляемые копии.
    """
    if mode not in {"preserve", "link", "copy"}:
        raise ValueError(f"неизвестный режим skills: {mode}")
    for name in _RETIRED_SKILLS:
        retired = dest_root / name
        if retired.is_symlink() or retired.is_file():
            retired.unlink()
        elif retired.exists():
            shutil.rmtree(retired)
    skills_root = _repo_root() / ".agents" / "skills"
    if not skills_root.is_dir():
        return []
    dest_root.mkdir(parents=True, exist_ok=True)
    installed = []
    for source in sorted(skills_root.iterdir()):
        if not (source / "SKILL.md").exists():
            continue
        dest = dest_root / source.name
        if dest.is_symlink():
            if mode == "preserve":
                installed.append(dest)
                continue
            dest.unlink()
        elif dest.exists():
            shutil.rmtree(dest)
        if mode == "link":
            dest.symlink_to(source, target_is_directory=True)
        else:
            shutil.copytree(source, dest)
        installed.append(dest)
    return installed


_RULES_BEGIN = "<!-- memory-curator:begin -->"
_RULES_END = "<!-- memory-curator:end -->"
_ROUTES_POINTER_BEGIN = "<!-- memory-curator-routes:begin -->"
_ROUTES_POINTER_END = "<!-- memory-curator-routes:end -->"


def _rules_section(base: str) -> str:
    """Текст правил памяти из репо (integrations/curator-rules.md).

    Единая секция Memory Curator: правила памяти + pointer каталога
    маршрутов + hint регенерации. Путь каталога подставляется при
    установке (плейсхолдер {catalog}) — текст генерируется, а не
    хранится с абсолютным путём.
    """
    path = _repo_root() / "integrations" / "curator-rules.md"
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    return text.replace("{catalog}", str(_routes_catalog_path(base)))


def _install_marked_section(rules_path: Path, body: str, begin: str, end: str) -> bool:
    """Своя секция между маркерами в файле правил (AGENTS.md / CLAUDE.md).

    Read-side без хуков: секция попадает в контекст каждой сессии.
    Файла может не быть — создаём; чужой контент не трогаем, заменяем
    только свою секцию между маркерами (идемпотентно). Запись атомарная
    (fs.atomic_write_text) — сбой посреди записи не обрезает чужой
    rules-файл.
    """
    if not body:
        return False
    existing = rules_path.read_text(encoding="utf-8") if rules_path.exists() else ""
    pattern = re.compile(re.escape(begin) + r".*?" + re.escape(end) + r"\n?", re.DOTALL)
    without_ours = pattern.sub("", existing).rstrip()
    section = f"{begin}\n{body}\n{end}"
    atomic_write_text(rules_path, without_ours + ("\n\n" if without_ours else "") + section + "\n")
    return True


def _install_global_rules(rules_path: Path, body: str) -> bool:
    """Секция Memory Curator в глобальный файл правил (AGENTS.md / CLAUDE.md)."""
    return _install_marked_section(rules_path, body, _RULES_BEGIN, _RULES_END)


def _routes_catalog_path(base: str) -> Path:
    """Абсолютный путь каталога маршрутов в базе."""
    return Path(os.path.abspath(os.path.expanduser(base))) / _ROUTES_CATALOG_NAME


def _remove_marked_section(rules_path: Path, begin: str, end: str) -> bool:
    """Удалить свою маркированную секцию (переход форматов, откат install).

    True — блок был и удалён; False — блока/файла не было. Чужой контент
    не трогаем; запись атомарная, как у _install_marked_section.
    """
    if not rules_path.exists():
        return False
    existing = rules_path.read_text(encoding="utf-8")
    pattern = re.compile(re.escape(begin) + r".*?" + re.escape(end) + r"\n?", re.DOTALL)
    without, removed = pattern.subn("", existing)
    if not removed:
        return False
    atomic_write_text(
        rules_path, without.rstrip() + "\n" if without.strip() else "")
    return True


def _remove_stale_routes_pointer(rules_path: Path) -> bool:
    """Протухшая routes-секция от старых установок (до слияния в единую)."""
    return _remove_marked_section(
        rules_path, _ROUTES_POINTER_BEGIN, _ROUTES_POINTER_END)


def publish_rules_sections(base: str) -> list[str]:
    """Единая секция Memory Curator (правила + pointer каталога) во все
    обнаруженные харнесы (publish шаг).

    Вызывается после записи каталога (`curator knowledge-routes --write`).
    Протухший routes-pointer блок от старых установок удаляется.
    Fault-isolation per harness: незаписываемый rules-файл одного харнеса
    (read-only, нет места) не валит publish остальных — деградирует в ⚠-шаг,
    из publish-пути исключение не выходит. Возвращает publish-строки;
    без найденных харнесов — пояснение.
    """
    home = Path(os.environ.get("HOME", str(Path.home())))
    do_opencode, do_claude = detect_harnesses()
    steps: list[str] = []
    if do_opencode:
        rules_path = home / ".config" / "opencode" / "AGENTS.md"
        try:
            _remove_stale_routes_pointer(rules_path)
            if _install_global_rules(rules_path, _rules_section(base)):
                steps.append("✅ opencode: единая секция Memory Curator в глобальном AGENTS.md")
        except Exception as e:
            steps.append(f"⚠ opencode: секция Memory Curator не записана: {e}")
    if do_claude:
        rules_path = home / ".claude" / "CLAUDE.md"
        try:
            _remove_stale_routes_pointer(rules_path)
            if _install_global_rules(rules_path, _rules_section(base)):
                steps.append("✅ Claude Code: единая секция Memory Curator в ~/.claude/CLAUDE.md")
        except Exception as e:
            steps.append(f"⚠ Claude Code: секция Memory Curator не записана: {e}")
    if not steps:
        steps.append("◦ opencode / Claude Code не обнаружены — секция не обновлена")
    return steps


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


def detect_harnesses() -> tuple[bool, bool]:
    """(opencode, claude) — что найдено на машине."""
    home = Path(os.environ.get("HOME", str(Path.home())))
    has_opencode = (home / ".config" / "opencode").is_dir()
    has_claude = (home / ".claude").is_dir() or (home / ".claude.json").exists()
    return has_opencode, has_claude


def _effective_base(base_dir: str | None) -> str:
    """База для state-конфига.

    Патч (повторный install) не имеет права сбрасывать существующую
    настройку: без явного --base-dir сохраняем базу из state-конфига
    (~/.curator/config.json); флаг — осознанное переопределение; свежая
    установка — дефолт. Установка старой (MCP-эпохи) версии мигрируется:
    её CURATOR_BASE_DIR переносится в state-конфиг, а не теряется.
    """
    if base_dir:
        return base_dir
    from curator.state import configured_base
    existing = configured_base()
    if existing:
        return existing
    legacy = _legacy_base_from_configs()
    if legacy:
        return legacy
    return default_base_dir()


def _legacy_base_from_configs() -> str | None:
    """База из MCP-секций установки старой версии (разовая миграция).

    После ухода от MCP эти секции удаляются install'ом; чтобы апгрейд
    не молча сбрасывал базу пользователя на дефолт, значение переносится
    сюда до удаления записей.
    """
    home = Path(os.environ.get("HOME", str(Path.home())))
    candidates = [
        (home / ".config" / "opencode" / "opencode.json", ("mcp", "memory-curator")),
        (Path.cwd() / ".mcp.json", ("mcpServers", "memory-curator")),
    ]
    for path, (section, key) in candidates:
        config, error = _read_json_config(path)
        if config is None:
            continue
        entry = (config.get(section) or {}).get(key) or {}
        env = entry.get("environment") or entry.get("env") or {}
        base = env.get("CURATOR_BASE_DIR")
        if isinstance(base, str) and base.strip():
            return base.strip()
    return None


_RETIRED_PLUGINS = ("curator-context.js", "curator-reminder.js")


def _remove_our_mcp_entry(config: dict, section: str = "mcp") -> None:
    """Удалить свою мёртвую MCP-запись (сервера больше нет).

    Чужие записи секции не трогаем.
    """
    entries = config.get(section)
    if isinstance(entries, dict) and "memory-curator" in entries:
        entries.pop("memory-curator", None)


def _remove_our_plugins(config: dict) -> None:
    """Удалить свои мёртвые plugin[]-записи (плагинов больше нет)."""
    plugins = config.get("plugin")
    if not isinstance(plugins, list):
        return
    kept = [p for p in plugins
            if not (isinstance(p, str) and any(p == n or p.endswith(f"/{n}")
                                               for n in _RETIRED_PLUGINS))]
    if kept != plugins:
        config["plugin"] = kept


def _install_footer() -> list[str]:
    return [
        "",
        "Готово. Перезапусти opencode / Claude Code — появятся команды /curator-*, "
        "скиллы и правила памяти. Фоновых процессов нет: capture — по желанию, "
        "improve — вручную (`curator improve`).",
        "База: дефолт ~/memory-curator, существующая настройка сохраняется при обновлении.",
        "Где база сейчас: curator status · смена: попроси агента «смени базу знаний на <путь>»",
    ]


def install_all(
    target: str | None = None,
    base_dir: str | None = None,
    skills_mode: str | None = None,
) -> list[str]:
    """Установка без вопросов: автодетект → ставим во всё найденное."""
    skills_mode = skills_mode or os.getenv("CURATOR_SKILLS_MODE", "preserve")
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
        steps.extend(_install_opencode_steps(base_dir, skills_mode))
    if do_claude:
        if do_opencode:
            steps.append("")
        steps.extend(_install_claude_steps(base_dir, skills_mode))

    steps.extend(_install_footer())
    return steps


def _install_opencode_steps(base_dir: str | None, skills_mode: str) -> list[str]:
    """Команды + скиллы + правила в ~/.config/opencode (без футера).

    Решение 2026-10-03 «ноль фоновых процессов»: MCP-сервер, worker и
    delivery-плагины не ставятся. База персистится в state-конфиг.
    """
    home = Path(os.environ.get("HOME", str(Path.home())))

    config_path = home / ".config" / "opencode" / "opencode.json"
    config, error = _read_json_config(config_path)
    if config is None:
        return [f"⛔ opencode: {error}"]
    base = _effective_base(base_dir)
    from curator.state import write_configured_base
    write_configured_base(base)
    # Апгрейд: свои мёртвые MCP/plugin-записи от старых версий чистим
    # (сервера и плагинов больше нет), чужие не трогаем.
    _remove_our_mcp_entry(config)
    _remove_our_plugins(config)
    commands = _commands_source()
    installed_commands = config.setdefault("command", {})
    for name in _RETIRED_COMMANDS:
        installed_commands.pop(name, None)
    if commands:
        installed_commands.update(commands)
    _write_json_config(config_path, config)
    steps = [f"✅ opencode: команды /curator-*: {config_path} (остальное не тронуто)",
             f"✅ opencode: база знаний: {base}"]
    if _ensure_default_map(base):
        steps.append("◦ opencode: дефолтная карта тем создана (настрой при желании: "
                     f"{_routes_catalog_path(base).parent / 'knowledge-map.md'})")

    skills = _install_skills(home / ".config" / "opencode" / "skills", skills_mode)
    if skills:
        steps.append(f"✅ opencode: скиллы {', '.join(s.name for s in skills)} (mode={skills_mode})")
    else:
        steps.append("⚠ скиллы не найдены в репо (wheel-установка?) — команды работают")

    agents_md = home / ".config" / "opencode" / "AGENTS.md"
    stale_removed = _remove_stale_routes_pointer(agents_md)
    if _install_global_rules(agents_md, _rules_section(base)):
        note = " (протухший routes-блок удалён)" if stale_removed else ""
        steps.append(f"✅ opencode: единая секция Memory Curator (правила + каталог маршрутов) "
                     f"в глобальном AGENTS.md{note}: {_routes_catalog_path(base)}")
    return steps


def _install_claude_steps(base_dir: str | None, skills_mode: str) -> list[str]:
    """Слэш-команды ~/.claude/commands + скиллы + правила (без футера).

    MCP-конфиг (.mcp.json) больше не пишется: решение 2026-10-03 —
    ноль фоновых процессов, вся механика в CLI.
    """
    home = Path(os.environ.get("HOME", str(Path.home())))
    base = _effective_base(base_dir)
    from curator.state import write_configured_base
    write_configured_base(base)
    steps = [f"✅ Claude Code: база знаний: {base}"]

    # Апгрейд: мёртвая MCP-запись из старой установки в проектном .mcp.json
    mcp_path = Path.cwd() / ".mcp.json"
    if mcp_path.exists():
        project_config, error = _read_json_config(mcp_path)
        if project_config is not None:
            _remove_our_mcp_entry(project_config, section="mcpServers")
            _write_json_config(mcp_path, project_config)
    if _ensure_default_map(base):
        steps.append("◦ Claude Code: дефолтная карта тем создана")

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

    skills = _install_skills(home / ".claude" / "skills", skills_mode)
    if skills:
        steps.append(f"✅ Claude Code: скиллы {', '.join(s.name for s in skills)}")
    else:
        steps.append("⚠ скиллы не найдены в репо (wheel-установка?) — команды работают")

    claude_md = home / ".claude" / "CLAUDE.md"
    stale_removed = _remove_stale_routes_pointer(claude_md)
    if _install_global_rules(claude_md, _rules_section(base)):
        note = " (протухший routes-блок удалён)" if stale_removed else ""
        steps.append(f"✅ Claude Code: единая секция Memory Curator в ~/.claude/CLAUDE.md{note}")
    return steps
