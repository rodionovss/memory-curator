"""Выполнение детерминированного check-а на workspace-е.

Check-и переиспользуются из benchmark/application/checks (заморожены sha256
до прогонов оригинального эксперимента). Check — модуль с функцией
check(d) -> (bool, str).
"""

import importlib.util
import sys
from pathlib import Path


def run_check(check_path: Path, workspace: Path) -> tuple[bool, str]:
    sys.path.insert(0, str(check_path.parent))
    try:
        spec = importlib.util.spec_from_file_location(
            "frozen_check_" + check_path.stem, check_path
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.check(str(workspace))
    finally:
        sys.path.remove(str(check_path.parent))
