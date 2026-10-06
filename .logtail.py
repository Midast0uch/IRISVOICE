"""Throwaway: grep the TAIL of a huge log file quickly.

WHY: .iris-logs/backend-*.log reached 489 MB in about an hour, so Select-String
over the whole file times out and the log becomes un-greppable - the very
instrument the project relies on for "what did IRIS say". Seek to a byte offset
near the end and scan forward instead of reading hundreds of megabytes.

Usage:  python .logtail.py <path> <pattern> [mb]
        python .logtail.py <path> <pattern> 60 30      # last 30 MB
"""
from __future__ import annotations

import re
import sys

path = sys.argv[1]
pattern = sys.argv[2]
mb = float(sys.argv[3]) if len(sys.argv) > 3 else 40.0

tail_bytes = int(mb * 1024 * 1024)
rx = re.compile(pattern, re.IGNORECASE)

with open(path, "rb") as fh:
    fh.seek(0, 2)
    size = fh.tell()
    fh.seek(max(0, size - tail_bytes))
    fh.readline()  # drop the partial first line
    data = fh.read().decode("utf-8", "replace")

lines = data.splitlines()
hits = [ln for ln in lines if rx.search(ln)]
print(f"file={size/1048576:.0f}MB  scanned last {mb:.0f}MB "
      f"({len(lines)} lines)  matches={len(hits)}")
for ln in hits[-40:]:
    print(ln[:200])
