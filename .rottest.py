"""Throwaway: prove ShareableRotatingFileHandler survives the exact fault.

Simulates the real condition: a SECOND handle holds the same log file open (in
production that is the process manager's stdout redirect / the twin rotating
handler), then forces a rollover. Before the fix this raised
PermissionError [WinError 32] every time and wrote the error into the file it
could not rotate. After the fix it must skip the rollover and keep writing.
"""
from __future__ import annotations

import logging
import os

from backend.monitoring.structured_logger import ShareableRotatingFileHandler as H

p = ".iris-logs/_rot_selftest.log"
for f in (p, p + ".1"):
    try:
        os.remove(f)
    except OSError:
        pass

handler = H(p, maxBytes=200, backupCount=1, encoding="utf-8")
log = logging.getLogger("rot_selftest")
log.handlers = [handler]
log.setLevel(logging.INFO)
log.propagate = False

# The handle that made rotation impossible: opened independently of the handler.
blocker = open(p, "a", encoding="utf-8")

for i in range(25):
    log.info("line %d %s", i, "x" * 40)

blocker.write("the blocking handle still works\n")
blocker.flush()
blocker.close()

size = os.path.getsize(p)
print(f"SURVIVED: no PermissionError escaped; the log kept being written "
      f"(size={size} bytes)")
print(f"rolled-over file present: {os.path.exists(p + '.1')}")
