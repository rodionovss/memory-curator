"""Сборка workspace-а прогона: fixture + kb + вариант routing-контекста.

Структура workspace:
  <run_dir>/ws/           — рабочие файлы задачи (копия fixtures/<T>/fix)
  <run_dir>/ws/kb/        — база знаний (факты + index.md)
  <run_dir>/ws/AGENTS.md  — routing-вариант (R1/R2/R3; R0 — файл отсутствует)
"""

import json
import shutil
from pathlib import Path

CORPUS_DIR = Path(__file__).resolve().parents[1] / "corpus"
VARIANT_FILES = {"R1": "r1.md", "R2": "r2.md", "R3": "r3.md"}


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


def build_workspace(run_dir: Path, task: dict, variant: str) -> Path:
    """Собрать workspace для одного прогона. Возвращает путь к ws."""
    ws = run_dir / "ws"
    ws.mkdir(parents=True, exist_ok=True)

    if task["fixture_dir"] is not None:
        shutil.copytree(task["fixture_dir"], ws, dirs_exist_ok=True)
    shutil.copytree(CORPUS_DIR / "kb", ws / "kb")

    if variant != "R0":
        src = CORPUS_DIR / "variants" / VARIANT_FILES[variant]
        shutil.copyfile(src, ws / "AGENTS.md")

    return ws


def task_prompt(task: dict) -> str:
    return task["task_prompt_file"].read_text(encoding="utf-8").strip()
