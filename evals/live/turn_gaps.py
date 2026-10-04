"""Uncovered stretches of a turn: time with NO model call and NO tool call in
flight, longer than a threshold, with the log lines on both sides."""
import datetime
import re
import sys

import json


def parse(p):
    out = []
    for line in open(p, encoding="utf-8", errors="replace"):
        try:
            d = json.loads(line)
        except Exception:
            continue
        out.append((datetime.datetime.fromisoformat(d["timestamp"][:26]), d["message"]))
    return out

NOISE = ("heartbeat", "system_status", "AudioPipeline", "ping", "pong", "vision-timing",
         "tts-worker", "TTSManager", "crawl-ui", "SpeechLane", "sched_reserve")

path, thr = sys.argv[1], float(sys.argv[2]) if len(sys.argv) > 2 else 2.0
rows = parse(path)
start = end = None
for t, m in rows:
    if start is None and re.search(r"Processing message type: (dev_cli|text_message)", m):
        start = t
    if start and re.search(r"\[LAYERS\] turn=", m):
        end = t
busy = []
for t, m in rows:
    c = re.search(r"\[InferenceRouter\] call done role=\w+ model=\S+ ([\d.]+)s", m)
    if c:
        busy.append((t - datetime.timedelta(seconds=float(c.group(1))), t))
    d = re.search(r"\[TOOL_DISPATCH\] kind=tool .*duration_ms=(\d+)", m)
    if d:
        busy.append((t - datetime.timedelta(milliseconds=int(d.group(1))), t))
busy.sort()
gaps, cur = [], start
for s, e in busy:
    if e < start or s > end:
        continue
    if s > cur:
        gaps.append((cur, s))
    cur = max(cur, e)
if end > cur:
    gaps.append((cur, end))
tot = 0.0
for s, e in gaps:
    dur = (e - s).total_seconds()
    if dur < thr:
        continue
    tot += dur
    inside = [m for t, m in rows if s <= t <= e and not any(k in m for k in NOISE)]
    print(f"--- {dur:5.1f}s idle {s.strftime('%H:%M:%S')}-{e.strftime('%H:%M:%S')} ({len(inside)} lines)")
    for m in inside[:3] + (["..."] if len(inside) > 6 else []) + inside[-3:] if len(inside) > 6 else inside:
        print("     ", m[:150])
print(f"total idle in gaps >= {thr}s: {tot:.1f}s")
