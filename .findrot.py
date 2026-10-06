"""Throwaway: find the code that ROTATES the backend log.

The log shows thousands of
    PermissionError: [WinError 32] ... 'backend-*.log' -> 'backend-*.log.1'
so something tries to rename a log file that is still open (impossible on
Windows), repeatedly. Locate the rotator with a scoped walk rather than a
recursive shell search, which times out on this tree.
"""
from __future__ import annotations

import os
import re

SKIP = {
    ".git", "node_modules", ".next", "dist", "__pycache__", ".venv", "venv",
    ".mcm", "llama.cpp", "llama.cpp-prismml", "llama.cpp-prismml-src",
    "llama-cpp-turboquant", "screenshots", "data", ".opencode", ".iris-logs",
}
EXT = (".py", ".bat", ".cmd", ".ps1", ".json", ".toml", ".cfg", ".ini", ".yaml")
# The rotator signature only: who creates a RotatingFileHandler, and on what.
rx = re.compile(r"RotatingFileHandler|maxBytes|doRollover|backupCount")

hits = 0
for root, dirs, files in os.walk("."):
    dirs[:] = [d for d in dirs if d not in SKIP]
    for f in files:
        if not f.endswith(EXT):
            continue
        p = os.path.join(root, f)
        try:
            with open(p, encoding="utf-8", errors="replace") as fh:
                for i, ln in enumerate(fh, 1):
                    if rx.search(ln):
                        print(f"{p}:{i}: {ln.strip()[:115]}")
                        hits += 1
                        if hits > 40:
                            raise SystemExit
        except SystemExit:
            raise
        except Exception:
            pass
print("total hits:", hits)
