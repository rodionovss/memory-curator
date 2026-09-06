import re

from common import read


def check(d):
    t = read(d, "SettingsReader.kt")
    if t is None:
        return False, "SettingsReader.kt отсутствует"
    if "readTheme" not in t:
        return False, "метод readTheme не добавлен"
    n = len(re.findall(r"withContext\(", t))
    if n < 2:
        return False, "blocking-чтение без withContext(IO) — ложное применение правила"
    return True, "blocking-чтение корректно обёрнуто"
