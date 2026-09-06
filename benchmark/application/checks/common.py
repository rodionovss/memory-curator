from pathlib import Path


def read(d, name):
    p = Path(d) / name
    if not p.exists():
        return None
    return p.read_text(encoding="utf-8")
