from pathlib import Path


def check(d):
    text = "\n".join(p.read_text(encoding="utf-8") for p in Path(d).glob("*.kt"))
    if "@IntoMap" not in text:
        return False, "нет @IntoMap-контрибуций"
    if "@ViewModelKey(HomeViewModel" not in text.replace(" ", ""):
        return False, "нет @ViewModelKey(HomeViewModel)"
    return True, "контрибуции в map-фабрику добавлены"
