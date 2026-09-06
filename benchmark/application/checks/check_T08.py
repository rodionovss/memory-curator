from common import read


def check(d):
    st = read(d, "ProfileState.kt")
    vm = read(d, "ProfileViewModel.kt")
    tr = read(d, "ProfileTransformer.kt")
    if vm is None:
        return False, "ProfileViewModel.kt отсутствует"
    if st is not None and "ErrorModel" in st:
        return False, "ErrorModel в State — State должен хранить сырую ошибку"
    if "ErrorModel" in vm:
        return False, "ErrorModel рождается в ViewModel — место в трансформере"
    if tr is None or "ErrorModel(" not in tr:
        return False, "ErrorModel не рождается в трансформере"
    if "Validation" not in tr:
        return False, "Validation не обрабатывается в трансформере"
    return True, "сырая ошибка в State, ErrorModel в трансформере"
