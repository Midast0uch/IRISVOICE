"""Throwaway: tally the exception landscape in the tail of a huge log.

WHY: .logtail.py showed 21,629 "Traceback" lines in the last 80 MB of one
backend log. Reading them one by one is not possible, and the exception TYPE plus
its message is what identifies the defect. Count them instead.

Usage: python .exsummary.py <path> [mb]
"""
from __future__ import annotations

import collections
import re
import sys

path = sys.argv[1]
mb = float(sys.argv[2]) if len(sys.argv) > 2 else 80.0

with open(path, "rb") as fh:
    fh.seek(0, 2)
    size = fh.tell()
    fh.seek(max(0, size - int(mb * 1024 * 1024)))
    fh.readline()
    data = fh.read().decode("utf-8", "replace")

lines = data.splitlines()

# Final line of a traceback: "SomeError: message" (optionally indented).
rx_exc = re.compile(
    r"^\s*([A-Za-z_][A-Za-z0-9_.]*(?:Error|Exception|Timeout|Refused|Interrupt))"
    r"[:\s](.{0,110})"
)
counts: collections.Counter = collections.Counter()
for ln in lines:
    m = rx_exc.match(ln)
    if m:
        counts[f"{m.group(1)}: {m.group(2).strip()}"[:130]] += 1

# WARNING/ERROR log lines, deduplicated by their message shape.
rx_log = re.compile(r"\[(WARNING|ERROR)\]\s*(\S+):\s*(.{0,110})")
logcounts: collections.Counter = collections.Counter()
for ln in lines:
    m = rx_log.search(ln)
    if m:
        logcounts[f"{m.group(1)} {m.group(2)}: {m.group(3).strip()}"[:130]] += 1

print(f"scanned last {mb:.0f}MB of a {size/1048576:.0f}MB log "
      f"({len(lines)} lines)\n")
print("=== exception types ===")
for k, v in counts.most_common(20):
    print(f"{v:>7}  {k}")
print("\n=== WARNING/ERROR lines ===")
for k, v in logcounts.most_common(20):
    print(f"{v:>7}  {k}")
