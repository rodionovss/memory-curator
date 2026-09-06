from pathlib import Path


def check(d):
    kts = [p for p in Path(d).glob("*.kt")]
    if not kts:
        return False, "решение (.kt) не создано"
    text = "\n".join(p.read_text(encoding="utf-8") for p in kts)
    if "wrapContentHeight" in text:
        return False, "wrapContentHeight() в решении — лишний"
    if "Row(" not in text or text.count("Text(") < 2:
        return False, "Row/Text не перенесены"
    return True, "без wrapContentHeight"
