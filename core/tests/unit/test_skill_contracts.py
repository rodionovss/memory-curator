from pathlib import Path


SKILLS = Path(__file__).parents[3] / ".agents" / "skills"


def test_curator_save_is_a_cli_fast_lane():
    """Пивот 2026-10-03: MCP-церемония заменена одним вызовом CLI."""
    skill = (SKILLS / "curator-save" / "SKILL.md").read_text(encoding="utf-8")

    assert "curator save" in skill
    assert "curator_session_capture" not in skill
    assert "curator_capture_approve" not in skill
    assert "curator-update-docs" not in skill
    # результат с маршрутами («→ файл») показывается пользователю
    assert "→" in skill


def test_save_playbook_documents_ledger_first_and_upsert_fixes():
    playbook = (SKILLS / "curator-save" / "playbook.md").read_text(encoding="utf-8")

    # кандидаты сначала из леджера задачи, контекст сессии - fallback
    assert "progress.md" in playbook
    # контент-контракт (0.5.0, русская формулировка): правило + почему + когда
    assert "правило" in playbook.lower()
    assert "Почему" in playbook
    assert "условие применения" in playbook
    # корректировка = повторный вызов с тем же title (upsert, не дубль)
    assert "upsert" in playbook.lower()
    # read-only защита
    assert "режим записи" in playbook


def test_curator_update_docs_preflights_before_semantic_writeback():
    skill = (SKILLS / "curator-update-docs" / "SKILL.md").read_text(encoding="utf-8")

    assert skill.index("preflight") < skill.index("Примени минимальные смысловые патчи")
    for field in ("map_path", "watch_for", "captures", "mode", "instructions"):
        assert field in skill
    assert "останови весь\n   набор без правок" in skill
    assert "curator_capture_complete" in skill
    assert "changed_files" in skill


def test_save_skill_documents_cli_flow_and_readonly_guard():
    skill = (SKILLS / "curator-save" / "SKILL.md").read_text(encoding="utf-8")
    playbook = (SKILLS / "curator-save" / "playbook.md").read_text(encoding="utf-8")
    # bash-флоу и защита от записи в read-only сессии
    assert "bash" in skill.lower()
    assert "не сохраняй" in playbook
    assert "evidence" in playbook.lower()


def test_save_contract_documents_source_file_and_git_commit():
    """0.4.0: source_file в кандидате (дефолт — session/*.md) +
    локальный git-коммит после записи."""
    skill = (SKILLS / "curator-save" / "SKILL.md").read_text(encoding="utf-8")
    playbook = (SKILLS / "curator-save" / "playbook.md").read_text(encoding="utf-8")

    # source_file: без него маршрут уходит в дефолт
    assert "source_file" in skill
    assert "source_file" in playbook
    assert "session/" in skill
    # git-коммит после записи — локальный, push исключён явно
    assert "git-коммит" in skill
    assert "push не выполняется" in playbook


def test_save_contract_050_two_formats_and_doc_mode():
    """0.5.0: два формата записи — карточка и файл-знание (save --doc);
    выбор по самостоятельной ценности; шаблоны; evidence убран из контракта."""
    skill = (SKILLS / "curator-save" / "SKILL.md").read_text(encoding="utf-8")
    playbook = (SKILLS / "curator-save" / "playbook.md").read_text(encoding="utf-8")

    # выбор формата + команда фиксации файла
    assert "карточка" in skill.lower()
    assert "файл-знание" in skill.lower()
    assert "save --doc" in skill
    assert "save --doc" in playbook
    # критерий и шаблоны в плейбуке
    assert "самостоятельная ценность" in playbook
    assert "Шаблон файла-темы" in playbook
    assert "Шаблон карточки" in playbook
    # поле evidence из формата кандидата убрано
    assert '"evidence"' not in playbook


def test_update_docs_shows_topic_and_file_before_writeback():
    skill = (SKILLS / "curator-update-docs" / "SKILL.md").read_text(encoding="utf-8")

    assert "План размещения" in skill
    assert "Topic" in skill
    assert "File" in skill
    assert skill.index("План размещения") < skill.index("Примени минимальные смысловые патчи")
