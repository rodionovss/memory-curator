import re

from common import read


def _loop_bodies(lines):
    bodies, cur, indent = [], None, None
    for l in lines:
        if cur is None:
            m = re.match(r"^(\s*)(while|for|repeat|do)\b", l)
            if m:
                cur, indent = [], len(m.group(1))
        else:
            if l.strip() and len(l) - len(l.lstrip()) <= indent:
                bodies.append(cur)
                cur, indent = None, None
                m = re.match(r"^(\s*)(while|for|repeat|do)\b", l)
                if m:
                    cur, indent = [], len(m.group(1))
                continue
            cur.append(l)
    if cur is not None:
        bodies.append(cur)
    return bodies


def check(d):
    t = read(d, "SignaturePoller.kt")
    if t is None:
        return False, "SignaturePoller.kt отсутствует"
    lines = t.split("\n")
    pat = re.compile(r"Ed25519PrivateKeyParameters\(|Ed25519Signer\(|Base64\.decode")
    for body in _loop_bodies(lines):
        for l in body:
            if pat.search(l):
                return False, "дорогая инициализация осталась в теле цикла"
    return True, "инициализация вынесена из цикла"
