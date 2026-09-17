"""Сборка workspace-а прогона: fixture + kb + вариант routing-контекста.

Структура workspace:
  <run_dir>/ws/           — рабочие файлы задачи (копия fixtures/<T>/fix)
  <run_dir>/ws/kb/        — база знаний (факты + index.md)
  <run_dir>/ws/AGENTS.md  — routing-вариант (R1/R2/R3; R0 — файл отсутствует)
  <run_dir>/ws/p2-catalog.md — каталожная карта «тема → curator query» (P2)

Plus builders промптов рук доставки знания (P3/O1/Q1, эксперименты 02/03).
"""

import json
import shutil
from pathlib import Path

CORPUS_DIR = Path(__file__).resolve().parents[1] / "corpus"
VARIANT_FILES = {"R1": "r1.md", "R2": "r2.md", "R3": "r3.md"}
CATALOG_FILE = "p2-catalog.md"


def load_tasks() -> list[dict]:
    data = json.loads((CORPUS_DIR / "tasks.json").read_text(encoding="utf-8"))
    for task in data["tasks"]:
        task["fixture_dir"] = (
            (CORPUS_DIR / task["fixture_dir"]).resolve()
            if task["fixture_dir"] else None
        )
        task["task_prompt_file"] = (CORPUS_DIR / task["task_prompt_file"]).resolve()
        task["check"] = (CORPUS_DIR / task["check"]).resolve()
    return data["tasks"]


def load_models() -> dict:
    data = json.loads((CORPUS_DIR / "tasks.json").read_text(encoding="utf-8"))
    return data["models"]


def build_workspace(run_dir: Path, task: dict, variant: str, *,
                    include_kb: bool = True, catalog: bool = False) -> Path:
    """Собрать workspace для одного прогона. Возвращает путь к ws.

    include_kb=False — не класть kb/ в workspace (P3: факт уже в контексте).
    catalog=True — добавить p2-catalog.md (P2: карта «тема → curator query»).
    """
    ws = run_dir / "ws"
    ws.mkdir(parents=True, exist_ok=True)

    if task["fixture_dir"] is not None:
        shutil.copytree(task["fixture_dir"], ws, dirs_exist_ok=True)
    if include_kb:
        shutil.copytree(CORPUS_DIR / "kb", ws / "kb")

    if variant != "R0":
        src = CORPUS_DIR / "variants" / VARIANT_FILES[variant]
        shutil.copyfile(src, ws / "AGENTS.md")

    if catalog:
        shutil.copyfile(CORPUS_DIR / "variants" / CATALOG_FILE, ws / CATALOG_FILE)

    return ws


def task_prompt(task: dict) -> str:
    return task["task_prompt_file"].read_text(encoding="utf-8").strip()


KNOWLEDGE_HEADER = "## Знание из базы"


def knowledge_prompt(content: str, task_text: str) -> str:
    """Промпт рук доставки: знание блоком перед текстом задачи.

    Формат: «## Знание из базы\\n<content>\\n---\\n<task>».
    """
    return f"{KNOWLEDGE_HEADER}\n\n{content}\n\n---\n\n{task_text}"


def oracle_fact_content(task: dict) -> str:
    """Полный текст kb/<expected_fact>.md для oracle-рук (P3/O1)."""
    if not task["expected_kb_file"]:
        raise ValueError(f"у задачи {task['task_id']} нет expected_kb_file")
    return (CORPUS_DIR / task["expected_kb_file"]).read_text(encoding="utf-8").strip()


def curator_cards_block(cards: list) -> str:
    """Суммарный текст карточек curator delivery (title/summary/source/score/reason)."""
    blocks = []
    for card in cards:
        meta = []
        if card.source_file:
            meta.append(f"источник: {card.source_file}")
        meta.append(f"релевантность: {card.score}")
        if card.reason:
            meta.append(card.reason)
        blocks.append(
            f"### {card.title}\n\n{card.summary}\n\n({'; '.join(meta)})"
        )
    return "\n\n".join(blocks)
