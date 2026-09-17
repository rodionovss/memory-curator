"""Засев SQLite-базы curator-а под эксперименты 02/03 (без живых агентов).

Руки P1/P2 дают агенту curator MCP-инструменты: изолированный конфиг
получает mcp-запись с CURATOR_DB_PATH на свежесозданную базу. База
засеивается ДО запуска:

- 6 verified-фактов из corpus/kb (parse frontmatter + H1 + body);
- synthetic deprecated-факт FD1 из corpus/storage-queries.json
  (проверка status-filter: deprecated не должен попадать в выдачу).

Рука Q1 (real retriever) зовёт curator delivery.fetch_context по тексту
задачи против той же засеянной базы — до запуска агента.

sys.path: core/ добавляется лениво, только при вызове функций.
"""

import json
import re
import sys
from pathlib import Path

from workspace import curator_cards_block, knowledge_prompt

CORPUS_DIR = Path(__file__).resolve().parents[1] / "corpus"
CORE_DIR = Path(__file__).resolve().parents[3] / "core"


def _ensure_core_on_path() -> None:
    if str(CORE_DIR) not in sys.path:
        sys.path.insert(0, str(CORE_DIR))


def _import_curator():
    _ensure_core_on_path()
    from curator.models import StructuredFact
    from curator.backend.local import LocalBackend
    return LocalBackend, StructuredFact


def local_backend(db_path: Path):
    """LocalBackend на указанной базе (создаёт файл при отсутствии)."""
    LocalBackend, _ = _import_curator()
    return LocalBackend(db_path)


def parse_kb_fact(md_path: Path):
    """kb/*.md → StructuredFact (frontmatter type/tags + H1 title + body)."""
    _, StructuredFact = _import_curator()
    text = md_path.read_text(encoding="utf-8")

    fact_type = "Reference"
    tags: list[str] = []
    body = text
    if text.startswith("---\n"):
        end = text.find("\n---", 4)
        if end != -1:
            fm, body = text[4:end], text[end + 4:]
            m = re.search(r"^type:\s*(\S+)\s*$", fm, re.MULTILINE)
            if m:
                fact_type = m.group(1)
            m = re.search(r"^tags:\s*\[(.*?)\]\s*$", fm, re.MULTILINE)
            if m:
                tags = [t.strip() for t in m.group(1).split(",") if t.strip()]

    title = None
    content = body.strip()
    for i, line in enumerate(body.split("\n")):
        if line.startswith("# "):
            title = line[2:].strip()
            content = "\n".join(body.split("\n")[i + 1:]).strip()
            break
    if not title:
        raise ValueError(f"у {md_path.name} нет H1-заголовка")

    return StructuredFact(
        type=fact_type,
        title=title,
        tags=tags,
        status="verified",
        content_summary=content,
        source_file=f"kb/{md_path.name}",
    )


def seed_curator_db(db_path: Path) -> int:
    """Свежая база: 6 verified-фактов corpus/kb + deprecated FD1. → число фактов."""
    backend = local_backend(db_path)
    saved = 0
    for md in sorted((CORPUS_DIR / "kb").glob("*.md")):
        if md.name == "index.md":
            continue
        backend.store_fact(parse_kb_fact(md))
        saved += 1

    _, StructuredFact = _import_curator()
    synth = json.loads(
        (CORPUS_DIR / "storage-queries.json").read_text(encoding="utf-8")
    )["deprecated_synth_fact"]
    backend.store_fact(StructuredFact(
        type="Reference",
        title=synth["title"],
        tags=synth["tags"],
        status="deprecated",
        content_summary=synth["content"],
        source_file=None,
    ))
    return saved + 1


def fetch_context_for_task(trigger: str, db_path: Path, limit: int = 3) -> list:
    """curator delivery.fetch_context(trigger, backend, feedback=None, limit)."""
    _ensure_core_on_path()
    from curator.delivery import fetch_context
    return fetch_context(trigger, local_backend(db_path), None, limit=limit)


def proactive_delivery(task_text: str, db_path: Path) -> tuple[str, str, bool]:
    """Рука Q1: реальный retriever до запуска агента.

    → (prompt, delivery, silent_delivery):
    - карточки найдены → блок «## Знание из базы» перед задачей, delivery
      "real_retriever";
    - пусто → промпт без вставки, delivery "silent", silent_delivery=True.
    """
    cards = fetch_context_for_task(task_text, db_path, limit=3)
    if not cards:
        return task_text, "silent", True
    return knowledge_prompt(curator_cards_block(cards), task_text), "real_retriever", False
