import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

BASE = Path(__file__).parent.parent
TASKS = ["T01", "T02", "T03", "T04", "T05", "T06", "T07", "T08", "T09", "T10", "K1", "K2"]
ARMS = ["arm_a", "arm_b", "arm_c"]

results = {}
print("| Задача | A (голый) | B (статика) | C (куратор) |")
print("|--------|-----------|-------------|--------------|")
for t in TASKS:
    mod = importlib.import_module(f"check_{t}")
    row = []
    for a in ARMS:
        try:
            ok, reason = mod.check(BASE / t / a)
        except Exception as e:
            ok, reason = False, f"CHECK-ERROR: {e}"
        row.append("PASS" if ok else "FAIL")
        results[(t, a)] = (ok, reason)
    print(f"| {t} | {row[0]} | {row[1]} | {row[2]} |")

print()
for t in TASKS:
    for a in ARMS:
        ok, reason = results[(t, a)]
        if not ok:
            print(f"{t}/{a}: {reason}")

pass_a = sum(results[(t, "arm_a")][0] for t in TASKS if not t.startswith("K"))
pass_b = sum(results[(t, "arm_b")][0] for t in TASKS if not t.startswith("K"))
pass_c = sum(results[(t, "arm_c")][0] for t in TASKS if not t.startswith("K"))
print(f"\nИтог (10 задач): A={pass_a}/10  B={pass_b}/10  C={pass_c}/10")
for arm in ARMS:
    k = [results[(t, arm)] for t in TASKS if t.startswith("K")]
    print(f"Контроли {arm}: {[x[0] for x in k]}")
