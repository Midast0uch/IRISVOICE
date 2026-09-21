"""Session-318 T21 evidence pull (conv-103, fresh backend log)."""
import re
from collections import Counter

LOG = ".iris-logs/backend-20260910-095723.log"
lines = open(LOG, encoding="utf-8", errors="replace").read().splitlines()
print("total lines:", len(lines))

print("\n=== DISPATCHES + ENVELOPES + GATES (conv-103) ===")
for ln in lines:
    if "conv-103" in ln and ("TOOL_DISPATCH" in ln or "[envelope]" in ln or "gather gate" in ln or "run grade" in ln or "DER:recovery" in ln or "content-hash" in ln or "exclusion filtered" in ln or "DER:guard" in ln or "streak" in ln.lower()):
        print(ln[:320])

print("\n=== 404 URL frequency (conv-103 window, from 10:31) ===")
c404 = Counter()
for ln in lines:
    if "10:3" in ln[:22] or "10:4" in ln[:22]:
        if "404" in ln:
            for u in re.findall(r"https?://[^\s\"')\]]+", ln):
                c404[u[:120]] += 1
for u, n in c404.most_common(15):
    print(n, u)

print("\n=== approval / permission / run_command lines ===")
for ln in lines:
    l = ln.lower()
    if "approval" in l or "permission" in l or "run_command" in l:
        print(ln[:300])

print("\n=== TTS worker lines (spawn/synth/reap) ===")
for ln in lines:
    l = ln.lower()
    if "tts" in l and ("spawn" in l or "reap" in l or "shutdown" in l or "unload" in l or "synth" in l or "worker" in l):
        print(ln[:280])
