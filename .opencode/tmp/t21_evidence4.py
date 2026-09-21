"""Session-318 T21 evidence pull, part 4: s1 memory, s2 seeds, excluded flow."""
import re

LOG = ".iris-logs/backend-20260910-095723.log"
lines = open(LOG, encoding="utf-8", errors="replace").read().splitlines()

print("=== s1 step_result URLs (Source/Attempted/Dead lines, 10:31-10:33) ===")
for ln in lines:
    if ("10:32" in ln[:22] or "10:33:1" in ln[:22]) and ("--- Source" in ln or "--- Attempted" in ln or "--- Dead" in ln or "Source:" in ln):
        print(ln[:400])

print("\n=== s1/s2 plan + started urls ===")
for ln in lines:
    if "CRAWLER_STARTED" in ln or "CRAWLER_SOURCES_ADDED" in ln or ("plan.urls" in ln.lower()):
        print(ln[:400])

print("\n=== excluded anywhere in log ===")
found = False
for ln in lines:
    if "excluded" in ln.lower():
        print(ln[:300])
        found = True
if not found:
    print("(no excluded line — check params flow in code, not logs)")

print("\n=== Dead: lines ===")
for ln in lines:
    if "--- Dead:" in ln:
        print(ln[:400])

print("\n=== queue.add/failed/aborted + is_complete context ===")
for ln in lines:
    if "Aborted" in ln or "aborted" in ln or "is_complete" in ln or "queue complete" in ln.lower() or "mark_complete" in ln:
        print(ln[:280])

print("\n=== TTS worker current check via log: reaps/respawns/syntheses ===")
n_synth = sum(1 for ln in lines if "synthesize_stream ENTRY" in ln)
n_zero = sum(1 for ln in lines if "ZERO audio" in ln)
print("synth attempts:", n_synth, "| zero-audio:", n_zero)
for ln in lines:
    l = ln.lower()
    if "reap" in l or "respawn" in l or "shutdown" in l and "tts" in l:
        print(ln[:280])
