import re

from common import read


def check(d):
    t = read(d, "DetailViewModel.kt")
    if t is None:
        return False, "DetailViewModel.kt отсутствует"
    if re.search(r"\.orEmpty\(\)|\?\:\s*\"\"", t):
        return False, "обязательное значение замаскировано заглушкой (orEmpty/?: \"\")"
    if not re.search(r"requireNotNull|checkNotNull|error\(|require\(|check\(|!!", t):
        return False, "нет явного падения при отсутствии id"
    return True, "отсутствие id падает явно"
