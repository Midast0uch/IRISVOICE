import io
import re

PATS = [
    r"sk-[A-Za-z0-9]{20,}",
    r"ghp_[A-Za-z0-9]{20,}",
    r"AKIA[0-9A-Z]{16}",
    r"eyJ[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{20,}",
    r"(?i)(api[_-]?key|secret|token|password|passwd)\"?\s*[:=]\s*\"[A-Za-z0-9_\-]{16,}",
    r"xoxb-[A-Za-z0-9-]{20,}",
]

files = [
    "backend/backend/sessions/session_iris/conversation.json",
]
for f in files:
    try:
        s = io.open(f, encoding="utf-8", errors="replace").read()
    except Exception as exc:
        print("ERR", f, exc)
        continue
    hits = []
    for p in PATS:
        hits += re.findall(p, s)
    print(f, "| len=", len(s), "| hits=", len(hits), hits[:3])
print("DONE")
