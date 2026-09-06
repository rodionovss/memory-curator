import re
from pathlib import Path


def check(d):
    kts = [p for p in Path(d).glob("*.kt")]
    if not kts:
        return False, "решение (.kt) не создано"
    text = "\n".join(p.read_text(encoding="utf-8") for p in kts)
    if "Column(" not in text:
        return False, "корневой Column отсутствует"
    if "systemBarsPadding" in text:
        return False, "systemBarsPadding применяется повторно (уже во входном modifier)"
    stripped = re.sub(r"modifier\s*=\s*", "", text)
    stripped = re.sub(r"modifier\s*:\s*Modifier\s*=\s*Modifier", "", stripped)
    n = len(re.findall(r"\bmodifier\b", stripped))
    if n > 1:
        return False, f"входной modifier передаётся детям ({n} использований значения)"
    if n == 0:
        return False, "входной modifier не применён на корне"
    return True, "modifier применён один раз на корне"
