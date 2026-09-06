from pathlib import Path


def check(d):
    files = [p for p in Path(d).glob("*.kt")]
    if not files:
        return False, "решение не создано"
    text = "\n".join(p.read_text(encoding="utf-8") for p in files)
    ok = "sealed interface UiState" in text and all(
        w in text for w in ("Loading", "Content", "Error")
    )
    if ok:
        return True, "тривиальная задача решена"
    return False, "структура UiState неполная"
