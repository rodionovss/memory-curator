"""Файловые примитивы: атомарная запись текста."""

import os
import stat
from pathlib import Path


def atomic_write_text(target: Path, content: str) -> None:
    """Атомарная запись UTF-8 текста: tmp.<pid> рядом с целью + os.replace.

    Права существующего целевого файла сохраняются; при ошибке tmp удаляется.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f"{target.name}.tmp.{os.getpid()}")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
        if target.exists():
            os.chmod(tmp, stat.S_IMODE(target.stat().st_mode))
        os.replace(tmp, target)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise
