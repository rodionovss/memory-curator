import re
from pathlib import Path


def check(d):
    kts = [p for p in Path(d).glob("*.kt")]
    if not kts:
        return False, "решение (.kt) не создано"
    text = "\n".join(p.read_text(encoding="utf-8") for p in kts)
    if "Text(" not in text:
        return False, "Text не создан"
    if re.search(r"TextAlign\.(Start|TextStart|Left)", text) or re.search(r"textAlign\s*=", text):
        return False, "явный TextAlign.Start задан — не нужен (RTL-aware по умолчанию)"
    return True, "без явного TextAlign.Start"
