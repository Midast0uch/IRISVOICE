"""
Slash-command backends for /review and /debt (Gate 3 T8a/T8b, REQ-10/REQ-11).

/review — delete-list contract: the diff is computed HERE so an empty diff
short-circuits without an agent call (REQ-10 AC3); a non-empty diff is
delegated to the agent under a contract that permits ONLY a delete-list
(REQ-10 AC1), scoped to a path argument when given (AC2).

/debt — marker scan into task cards: scans the active workdir for deferred
markers and persists each as a deterministic-id card (upsert ⇒ dedupe by
file:line across runs, REQ-11 AC2). No new ledger store (design D8/8).

Quality gates: bounded scan (depth, file count, binary skip); git diff via
bounded subprocess; card writes never raise into the command path.
"""
from __future__ import annotations

import hashlib
import logging
import os
import subprocess
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)

SCAN_SKIP_DIRS = {
    "node_modules", ".git", ".next", "dist", "build", "venv", ".venv",
    "__pycache__", "llama.cpp", "target", ".iris-worktree", "vendor",
    "src-tauri/target",
}
BINARY_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".zip", ".gz", ".exe",
    ".dll", ".so", ".dylib", ".bin", ".woff", ".woff2", ".ttf", ".mp3", ".mp4",
    ".gguf", ".safetensors", ".pth", ".pt", ".ppn",
}
MAX_SCAN_FILES = 2000
MAX_SCAN_DEPTH = 6
MAX_FILE_BYTES = 512 * 1024

MARKERS = ("ponytail:", "TODO(deferred):", "IRIS-DEBT:")

REVIEW_CONTRACT = """You are performing a DELETE-LIST code review of the diff below.

CONTRACT (absolute):
- Output ONLY a delete-list: what to remove or simplify, and why.
- NEVER output replacement code, rewrites, or new implementations.
- One entry per finding, in this exact shape:
  DELETE: <path>:<approx lines> — <what to remove/simplify> — <why>
- If nothing warrants deletion, output exactly: NO DELETE FINDINGS.
- Do not praise, summarize, or narrate outside the entries.

DIFF:
```diff
{diff}
```"""


# ── /review ─────────────────────────────────────────────────────────────────

def get_diff(workdir: str, scope: Optional[str] = None) -> Optional[str]:
    """Working-tree diff for workdir (optionally scoped to one path).

    Returns None when git is unavailable / not a repo; '' when the diff is
    empty (the short-circuit case).
    """
    cmd = ["git", "diff", "HEAD"]
    if scope:
        cmd.extend(["--", scope])
    try:
        result = subprocess.run(
            cmd, cwd=workdir, capture_output=True, text=True,
            timeout=30, encoding="utf-8", errors="replace",
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("[slash] git diff failed in %s: %s", workdir, exc)
        return None
    if result.returncode not in (0, 1):
        return None  # not a repo, or git broken — explicit error upstream
    return result.stdout


def build_review_prompt(diff: str) -> str:
    return REVIEW_CONTRACT.format(diff=diff[:64_000])


# ── /debt ───────────────────────────────────────────────────────────────────

def scan_debt_markers(workdir: str) -> list[dict[str, Any]]:
    """Scan for deferred markers; returns [{file, line, text}] deduped."""
    findings: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    scanned = 0
    root_depth = os.path.normpath(workdir).count(os.sep)

    for dirpath, dirnames, filenames in os.walk(workdir):
        rel_dir = os.path.relpath(dirpath, workdir)
        parts = set(rel_dir.split(os.sep))
        if parts & {d.rstrip("/\\") for d in SCAN_SKIP_DIRS}:
            dirnames[:] = []
            continue
        if os.path.normpath(dirpath).count(os.sep) - root_depth >= MAX_SCAN_DEPTH:
            dirnames[:] = []
            continue
        dirnames[:] = [d for d in dirnames if d not in SCAN_SKIP_DIRS]
        for name in filenames:
            if scanned >= MAX_SCAN_FILES:
                return findings
            ext = os.path.splitext(name)[1].lower()
            if ext in BINARY_EXTENSIONS:
                continue
            path = os.path.join(dirpath, name)
            try:
                if os.path.getsize(path) > MAX_FILE_BYTES:
                    continue
                with open(path, "r", encoding="utf-8", errors="replace") as fh:
                    for lineno, line in enumerate(fh, 1):
                        for marker in MARKERS:
                            idx = line.find(marker)
                            if idx != -1:
                                key = (os.path.relpath(path, workdir), lineno)
                                if key not in seen:
                                    seen.add(key)
                                    findings.append({
                                        "file": key[0],
                                        "line": lineno,
                                        "marker": marker,
                                        "text": line.strip()[:200],
                                    })
                                break
                scanned += 1
            except OSError:
                continue
    return findings


def save_debt_cards(conversation_id: str,
                    markers: list[dict[str, Any]]) -> tuple[int, int]:
    """Persist markers as debt-tagged cards; deterministic ids ⇒ dedupe.

    Returns (new_cards, duplicates_skipped).
    """
    if not markers:
        return 0, 0
    from backend.agent.conversation_context_store import (
        CardState, CardStepSnapshot, get_context_store,
    )

    store = get_context_store()
    existing = {
        c.card_id for c in store.get_cards_for_conversation(conversation_id)
        if getattr(c, "mode", "") == "debt"
    }
    new_count = dup_count = 0
    now = time.time()
    for m in markers:
        key = f"{m['file']}:{m['line']}"
        card_id = "debt-" + hashlib.md5(  # noqa: S324 — non-crypto dedupe key
            key.encode()).hexdigest()[:12]
        if card_id in existing:
            dup_count += 1
            continue
        step = CardStepSnapshot(
            id=f"debt-{len(key)}-{abs(hash(key)) % 100000}",
            description=f"{m['file']}:{m['line']} — {m['text']}",
            status="pending",
            tool_name=None,
            result_summary=f"[debt] {m['marker']} {key}",
        )
        card = CardState(
            card_id=card_id,
            conversation_id=conversation_id,
            card_relation="new",
            plan_title=f"[debt] {m['file']}:{m['line']}",
            mode="debt",
            steps=[step],
            current_step=0,
            total_steps=1,
            terminal_state="running",
            created_at=now,
            updated_at=now,
        )
        if store.save_card(card):
            new_count += 1
        else:
            dup_count += 1
    return new_count, dup_count
