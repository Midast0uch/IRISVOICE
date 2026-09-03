"""
Shell Records — shell→agent context injection (Gate 3 T4, REQ-2).

Every completed user `>` command is queued as a structured record; the
AgentKernel drains the queue at turn assembly (design Key Decision 2) so the
next turn builds on real shell state (D1 — automatic, no opt-in).

Two lifetimes, one store:
  - DELIVERY is ephemeral. The drained block is assembled into the turn's
    outgoing context list and is never written to conversation memory, so it
    is paid for once, on the turn that has shell activity, and never occupies
    a dialogue-history slot afterwards.
  - RETENTION outlives delivery. Drained records stay in a bounded per-session
    history, and every retained record that is no longer carried verbatim gets
    a one-line index entry in the block. The index is always present, so the
    agent always knows the exact output exists and reads it with
    `read_shell_output(ref=...)` instead of reconstructing it from memory.
    This is the whole point: an agent that cannot read an earlier command's
    output will invent it.

Bounds (REQ-12 AC2 / REQ-2 AC4-AC5):
  - single record: 8 KB budget → head+tail with an elided marker
  - aggregate per turn: 24 KB → oldest evicted first, one elided-count marker
  - redaction BEFORE truncation, against the REQ-2 AC4 pattern set
  - deny-listed targets (.env*, *.pem, *.key, *_rsa, id_*, keyring) are never
    injected — a suppression notice is surfaced instead

Quality-check gates applied:
  - per-session deques, lock-guarded; bounded (max 50 queued records)
  - pure sync, no I/O on the hot path beyond regex work on bounded text
"""
from __future__ import annotations

import fnmatch
import re
import threading
import time
from collections import deque
from typing import Optional

# REQ-12 AC2 budgets
SINGLE_RECORD_BUDGET = 8 * 1024
AGGREGATE_TURN_BUDGET = 24 * 1024
MAX_QUEUED_RECORDS = 50

# Retention (T4b): a drained record is NOT discarded. It moves to a bounded
# per-session history so `read_shell_output` can return the EXACT bytes on a
# later turn. Without this the backend keeps no copy at all once the record
# leaves the turn context (the terminal scrollback lives in the browser), and
# a follow-up question about an earlier command has no ground truth to read --
# the agent would answer from the summary it half-remembers. Bounded: 20
# records/session x 8 KB cap = 160 KB worst case, 32 sessions = ~5 MB ceiling.
MAX_HISTORY_RECORDS = 20
MAX_HISTORY_SESSIONS = 32
# How many retained records get an index line in the injected block. The index
# is what makes retrieval non-opt-in: the agent always SEES that the output
# exists, so it reads instead of guessing. ~15 tokens per line.
MAX_INDEX_LINES = 10

# REQ-2 AC4 pattern set — verbatim from the requirement.
_REDACTION_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("AWS", re.compile(r"AWS[A-Z0-9]{16,}")),
    ("github", re.compile(r"gh[pousr]_[A-Za-z0-9]{16,}")),
    ("api-key", re.compile(r"sk-[A-Za-z0-9]{20,}")),
    ("private-key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    # long base64-ish run only when preceded by a secret assignment
    ("secret", re.compile(
        r"(?i)(?:key|token|secret|password)\s*[=:]\s*['\"]?"
        r"[A-Za-z0-9+/]{40,}={0,2}")),
]

# REQ-2 AC4 deny-list: output from these commands renders in the panel only.
# fnmatch's * crosses path separators, so "*.env" matches "C:\proj\.env"
# while "environment.ts" matches nothing here.
_DENY_GLOBS = (".env*", "*.env", "*.env.*", "*.pem", "*.key", "*_rsa",
               "id_*", "*keyring*")


def redact(text: str) -> str:
    """Replace secret-shaped matches with [REDACTED:<kind>] before injection."""
    for kind, pattern in _REDACTION_PATTERNS:
        text = pattern.sub(f"[REDACTED:{kind}]", text)
    return text


def is_denied_target(command: str) -> bool:
    """True if the command targets a deny-listed secret source."""
    lowered = command.lower()
    return any(fnmatch.fnmatch(tok, glob.lower())
               for tok in lowered.split()
               for glob in _DENY_GLOBS)


class ShellRecord:
    __slots__ = ("command", "exit_code", "head", "tail", "elided_bytes",
                 "workdir", "ts", "ref")

    def __init__(self, command: str, exit_code: Optional[int], output: str,
                 workdir: str, ts: float, ref: str = "") -> None:
        self.command = command
        self.exit_code = exit_code
        self.workdir = workdir
        self.ts = ts
        self.ref = ref
        output = redact(output)
        if len(output.encode("utf-8", errors="replace")) > SINGLE_RECORD_BUDGET:
            head = output[: SINGLE_RECORD_BUDGET // 2]
            tail = output[-(SINGLE_RECORD_BUDGET // 2):]
            elided = len(output.encode("utf-8", errors="replace")) - \
                len(head.encode("utf-8", errors="replace")) - \
                len(tail.encode("utf-8", errors="replace"))
            self.head = head
            self.tail = tail
            self.elided_bytes = max(elided, 0)
        else:
            self.head = output
            self.tail = ""
            self.elided_bytes = 0

    def retained_bytes(self) -> int:
        """Bytes this record can hand back on a read -- head+tail only. The
        elided middle is gone at record time and is never recoverable here."""
        head = len(self.head.encode("utf-8", errors="replace"))
        tail = len(self.tail.encode("utf-8", errors="replace"))
        return head + tail

    def index_line(self) -> str:
        """One compact line naming an EARLIER command whose output is retained.

        This line is what the agent reads to learn that exact output exists and
        how to ask for it. It carries no output bytes."""
        return (f"  $ {self.command}  exit={self.exit_code}  "
                f"[ref={self.ref}, {self.retained_bytes()} bytes retained]")

    def render(self) -> str:
        parts = [f"$ {self.command}", f"  exit={self.exit_code}"]
        if self.head:
            parts.append(self.head)
        if self.elided_bytes:
            parts.append(f"  …<{self.elided_bytes} bytes elided; full output in terminal panel>")
        if self.tail:
            parts.append(self.tail)
        return "\n".join(parts)


class ShellRecordQueue:
    """Per-session queue of completed shell commands awaiting injection, plus
    the bounded retention history that outlives the injection.

    Two lifetimes, deliberately:
      - the QUEUE holds records until the next boundary, then empties;
      - the HISTORY keeps the drained records so a later turn can read the
        exact bytes back by ref, instead of the agent guessing what a command
        printed. Nothing here is written to disk.
    """

    def __init__(self) -> None:
        self._queues: dict[str, deque] = {}
        self._history: dict[str, deque] = {}
        self._seq: dict[str, int] = {}
        self._suppressed: set[str] = set()
        # RLock: drain() holds the lock while updating suppression state.
        self._lock = threading.RLock()

    def record(self, session_id: str, command: str, exit_code: Optional[int],
               output: str, workdir: str) -> None:
        with self._lock:
            n = self._seq.get(session_id, 0) + 1
            self._seq[session_id] = n
        rec = ShellRecord(command, exit_code, output or "", workdir,
                          time.time(), ref=f"s{n}")
        with self._lock:
            q = self._queues.setdefault(session_id, deque(maxlen=MAX_QUEUED_RECORDS))
            q.append(rec)

    def mark_suppressed(self, session_id: str, command: str = "") -> None:
        with self._lock:
            self._suppressed.add(session_id)

    def clear_suppressed(self, session_id: str) -> None:
        with self._lock:
            self._suppressed.discard(session_id)

    def _retain(self, session_id: str, records: list) -> None:
        """Move drained records into the bounded history. Caller holds no lock."""
        if not records:
            return
        with self._lock:
            hist = self._history.get(session_id)
            if hist is None:
                # Bound the session count as well as the per-session depth:
                # a long-lived process must not accumulate one deque per
                # conversation forever.
                while len(self._history) >= MAX_HISTORY_SESSIONS:
                    self._history.pop(next(iter(self._history)))
                hist = deque(maxlen=MAX_HISTORY_RECORDS)
                self._history[session_id] = hist
            hist.extend(records)

    def known_sessions(self) -> tuple:
        """Session ids that currently hold queued or retained records.

        Diagnostic only. The queue and the drain are keyed by session_id on
        opposite sides of the process; a key mismatch produces an empty block
        and no error, so the keys have to be observable."""
        with self._lock:
            return tuple(sorted(set(self._queues) | set(self._history)))

    def get_output(self, session_id: str, ref: str) -> Optional[str]:
        """Exact retained output for one earlier command, or None.

        This is the ONLY path back to bytes that already left the turn context.
        It returns the same redacted, budget-capped text that was injected --
        never the raw stream -- so a read can not leak what an injection would
        not have shown.
        """
        ref = (ref or "").strip()
        if not ref:
            return None
        with self._lock:
            hist = list(self._history.get(session_id) or ())
        for rec in reversed(hist):
            if rec.ref == ref:
                return rec.render()
        return None

    def index_lines(self, session_id: str, exclude: frozenset = frozenset()) -> list:
        """Index lines for retained commands, newest first, capped."""
        with self._lock:
            hist = list(self._history.get(session_id) or ())
        out = []
        for rec in reversed(hist):
            if rec.ref in exclude:
                continue
            out.append(rec.index_line())
            if len(out) >= MAX_INDEX_LINES:
                break
        return out

    def drain(self, session_id: str) -> tuple[str, int]:
        """Return (injection_block, suppressed_count) and empty the queue.

        Aggregate budget enforced oldest-first eviction (REQ-2 AC5): newest
        records survive; one 'N earlier commands elided' marker covers the rest.
        Every drained record -- kept OR evicted -- is retained, and everything
        not carried verbatim in this block gets an index line so the agent can
        read it back exactly rather than reconstruct it from memory.
        """
        with self._lock:
            q = self._queues.pop(session_id, None)
            suppressed = session_id in self._suppressed
            self.clear_suppressed(session_id)

        records = list(q or [])
        self._retain(session_id, records)

        kept: list[ShellRecord] = []
        budget = AGGREGATE_TURN_BUDGET
        for rec in reversed(records):          # newest first
            size = len(rec.render().encode("utf-8", errors="replace"))
            if size > budget:
                break
            kept.insert(0, rec)
            budget -= size
        evicted = len(records) - len(kept)

        index = self.index_lines(session_id,
                                 exclude=frozenset(r.ref for r in kept))
        if not records and not suppressed and not index:
            return "", 0

        lines: list[str] = []
        if evicted:
            lines.append(f"[{evicted} earlier commands elided]")
        if kept:
            lines.append("[shell activity since last turn]")
            lines.extend(rec.render() for rec in kept)
        if index:
            lines.append(
                "[earlier shell output is retained verbatim -- call "
                "read_shell_output(ref=...) for the exact bytes; do NOT "
                "recall it from memory]"
            )
            lines.extend(index)
        if suppressed:
            lines.append("[injection suppressed for a secret-targeting command "
                         "(deny-list); output is in the terminal panel only]")
        return "\n".join(lines), (1 if suppressed else 0)

    def clear_session(self, session_id: str) -> None:
        """Drop every trace of one session -- queue, history, ref counter."""
        with self._lock:
            self._queues.pop(session_id, None)
            self._history.pop(session_id, None)
            self._seq.pop(session_id, None)
            self._suppressed.discard(session_id)


_queue: Optional[ShellRecordQueue] = None


def get_shell_record_queue() -> ShellRecordQueue:
    global _queue
    if _queue is None:
        _queue = ShellRecordQueue()
    return _queue
