from common import read


def check(d):
    t = read(d, "response.md")
    if t is None:
        return False, "response.md отсутствует"
    if "MARKER_153_UNTRACKED_CONTENT" in t:
        return True, "diff включает untracked-файл"
    return False, "diff не включает untracked-файл"
