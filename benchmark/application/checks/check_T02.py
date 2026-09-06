import re

from common import read


def check(d):
    t = read(d, "UserApi.kt")
    if t is None:
        return False, "UserApi.kt отсутствует"
    paths = re.findall(r'@GET\("([^"]+)"\)', t)
    if not any("settings" in p for p in paths):
        return False, "метод settings не добавлен"
    for p in paths:
        if re.search(r"mobile|api", p):
            return False, f"задвоение префикса в пути: {p!r}"
    return True, "путь относительно base URL"
