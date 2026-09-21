import io
import os
import re
import subprocess

PATS = [
    re.compile(r"(?i)(api[_-]?key|secret|token|password|passwd|bearer)\s*[:=]\s*[\"'][A-Za-z0-9_\-]{16,}"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"eyJ[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{20,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
]

def scan(label, paths):
    hits = 0
    for t in paths:
        if not os.path.isfile(t):
            continue
        try:
            s = io.open(t, encoding="utf-8", errors="replace").read()
        except Exception:
            continue
        for p in PATS:
            for m in p.finditer(s):
                hits += 1
                print("HIT", label, t, "->", m.group(0)[:70])
    return hits

# 1. all tracked modified files
mod = subprocess.run(
    ["git", "-c", "core.quotepath=false", "diff", "--name-only"],
    capture_output=True, text=True,
).stdout.splitlines()
mod = [m.strip() for m in mod if m.strip()]
print("modified tracked files:", len(mod))
h = scan("MOD", mod)

# 2. the new untracked spec files I authored
mine = [
    "backend/agent/goal_contract.py",
    "scripts/validate_goal_coverage.py",
    "backend/tests/unit/test_goal_contract.py",
    "backend/tests/contract/test_goal_contract_coverage.py",
    "backend/tests/behavioral/test_goal_contract_coverage.py",
]
print("authored new files:", len(mine))
h += scan("NEW", mine)

print("TOTAL_HITS", h)
