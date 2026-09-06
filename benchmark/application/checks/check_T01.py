import re

from common import read


def check(d):
    t = read(d, "ProfileRepository.kt")
    if t is None:
        return False, "ProfileRepository.kt отсутствует"
    lines = t.split("\n")
    idx = [i for i, l in enumerate(lines) if "getProfileById" in l and "fun" in l]
    if not idx:
        return False, "метод getProfileById не добавлен"
    end = len(lines)
    for j in range(idx[0] + 1, len(lines)):
        if re.match(r"^    (suspend )?fun |^\}", lines[j]):
            end = j
            break
    body = "\n".join(lines[idx[0]:end])
    if re.search(r"withContext", body):
        return False, "новый метод обёрнут в withContext"
    return True, "suspend-вызов без withContext"
