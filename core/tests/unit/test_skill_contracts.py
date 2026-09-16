from pathlib import Path


SKILLS = Path(__file__).parents[3] / ".agents" / "skills"


def test_curator_save_is_a_small_orchestrator():
    skill = (SKILLS / "curator-save" / "SKILL.md").read_text(encoding="utf-8")

    assert "curator_session_capture" in skill
    assert "curator_capture_approve" in skill
    assert "status=update_project_docs" in skill
    assert "next_action=curator-update-docs" in skill
    assert "question" in skill
    assert "Карту и target-документы здесь не читай" in skill


def test_curator_update_docs_preflights_before_semantic_writeback():
    skill = (SKILLS / "curator-update-docs" / "SKILL.md").read_text(encoding="utf-8")

    assert skill.index("preflight") < skill.index("Примени минимальные смысловые патчи")
    for field in ("map_path", "watch_for", "captures", "mode", "instructions"):
        assert field in skill
    assert "останови весь\n   набор без правок" in skill
    assert "curator_capture_complete" in skill
    assert "changed_files" in skill


def test_save_skill_documents_structured_russian_preview_contract():
    required = ("Type:", "Rule:", "Why:", "Evidence:", "Tags:")
    skill = (SKILLS / "curator-save" / "SKILL.md").read_text(encoding="utf-8")
    for marker in required:
        assert marker in skill, f"curator-save must document preview marker {marker}"
    assert "Evidence" in skill and "не сохраня" in skill


def test_update_docs_shows_topic_and_file_before_writeback():
    skill = (SKILLS / "curator-update-docs" / "SKILL.md").read_text(encoding="utf-8")

    assert "План размещения" in skill
    assert "Topic" in skill
    assert "File" in skill
    assert skill.index("План размещения") < skill.index("Примени минимальные смысловые патчи")
