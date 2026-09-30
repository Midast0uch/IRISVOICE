"""Brain-authored file changes — the "pen" half of the split roles.

Owner decision (execution audit, 2026-09-29): the small local tool model is the
hands (it picks the tool and the path), the Brain is the pen. Fields marked
``authored_by: "brain"`` in the tool registry (``edit_file.old/new``,
``write_file.content``) are written here by the Brain, from the step goal, the
current file and the earlier step results.

Why it exists: eval re-runs on 2026-09-29 (coding 0/3) showed the 2.6B tool
model never resolved a step like "Implement parse_duration in durations.py" to
a write tool — it cannot produce a file body, so it picked read_file and the
turn ended with a described fix and an unchanged file.

An existing file is changed through SEARCH/REPLACE blocks that are applied and
checked HERE against the current text (each must match exactly once), so the
rest of the file is preserved byte for byte and a bad quote fails before any
tool call is paid for. One block becomes ``edit_file(old, new)``; several
become one ``write_file`` with the verified result. A missing file is written
whole.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any, Callable, Optional, Tuple

logger = logging.getLogger(__name__)

AUTHORED_TOOLS = ("edit_file", "write_file")

# The Brain sees the whole file; larger files need a read with a line range
# and a narrower step, not a truncated view the Brain would edit blindly.
_MAX_FILE_CHARS = 60_000
_MAX_CONTEXT_CHARS = 24_000
_MAX_TOKENS = 8192

_BLOCK = re.compile(r"<{7} SEARCH\r?\n(.*?)\r?\n={7}\r?\n(.*?)>{7} REPLACE", re.S)
_FENCE = re.compile(r"```[^\n]*\n(.*?)```", re.S)

Generate = Callable[..., tuple]
Authored = Tuple[Optional[str], Optional[dict], str]  # (tool, params, error)


def _context(prior_results: Optional[list]) -> str:
    parts = []
    for r in prior_results or []:
        parts.append(f"[step {r.get('step')}] {r.get('description', '')}\n{r.get('result', '')}")
    text = "\n\n".join(parts)
    return text[-_MAX_CONTEXT_CHARS:] if len(text) > _MAX_CONTEXT_CHARS else text


def _ask(generate: Generate, prompt: str) -> str:
    text, _thinking, _tools = generate(
        "reasoning", [{"role": "user", "content": prompt}],
        temperature=0.0, max_tokens=_MAX_TOKENS,
    )
    return text or ""


def _apply_blocks(original: str, reply: str) -> Tuple[Optional[list], str]:
    """Parse SEARCH/REPLACE blocks and check each matches the running text once."""
    blocks = []
    for search, replace in _BLOCK.findall(reply):
        replace = replace[:-1] if replace.endswith("\n") else replace
        blocks.append((search, replace.rstrip("\r")))
    if not blocks:
        return None, "the Brain returned no SEARCH/REPLACE block"
    text = original
    for i, (search, replace) in enumerate(blocks, 1):
        if not search.strip():
            return None, f"block {i} has an empty SEARCH"
        count = text.count(search)
        if count != 1:
            return None, (f"block {i} SEARCH text matches {count} times in the file "
                          "(must be exactly once)")
        text = text.replace(search, replace, 1)
    return [blocks, text], ""


def author_step(
    bridge: Any,
    generate: Generate,
    session_id: str,
    tool: str,
    params: dict,
    goal: str,
    prior_results: Optional[list] = None,
    conv_id: str = "",
) -> Authored:
    """DER entry point: resolve the step's path the way the file tools will,
    read the current file, and have the Brain author the change."""
    from backend.tool_args import path_arg

    path = path_arg(params or {})
    if not path:
        return None, None, f"{tool} step has no file path"
    anchor = getattr(bridge, "_anchor_file_paths", None)
    if callable(anchor):
        path = anchor({"path": path}, session_id).get("path") or path
    file_text: Optional[str] = None
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8", newline="") as f:
                file_text = f.read()
        except (OSError, UnicodeDecodeError) as exc:
            return None, None, f"cannot read {path} to edit it: {exc}"
    return author_file_change(generate, tool, path, goal, file_text, prior_results, conv_id)


def author_file_change(
    generate: Generate,
    tool: str,
    path: str,
    goal: str,
    file_text: Optional[str],
    prior_results: Optional[list] = None,
    conv_id: str = "",
) -> Authored:
    """Return ``(tool, params, "")`` with Brain-written fields, or ``(None, None, reason)``.

    ``file_text`` is the current file (``None`` when it does not exist). The
    returned tool may differ from the requested one: a missing file is always a
    ``write_file``; several verified edits become one ``write_file``.
    """
    context = _context(prior_results)
    try:
        if file_text is None:
            reply = _ask(generate, (
                "You are writing a new file to complete one coding step.\n"
                f"STEP: {goal}\nFILE: {path}\n\n"
                f"EVIDENCE FROM EARLIER STEPS:\n{context or '(none)'}\n\n"
                "Return the complete file content in ONE fenced code block and nothing else."
            ))
            m = _FENCE.search(reply)
            content = m.group(1) if m else reply.strip()
            if not content.strip():
                return None, None, "the Brain returned an empty file body"
            logger.info("[BrainAuthor] conv=%s new file %s (%d chars)", conv_id, path, len(content))
            return "write_file", {"path": path, "content": content}, ""

        if len(file_text) > _MAX_FILE_CHARS:
            return None, None, (f"{path} is {len(file_text)} chars; too large to edit whole — "
                                "read the relevant line range first")
        # Match on LF text: models quote code with bare newlines.
        crlf = "\r\n" in file_text
        original = file_text.replace("\r\n", "\n") if crlf else file_text
        reply = _ask(generate, (
            "You are changing one existing file to complete one coding step.\n"
            f"STEP: {goal}\nFILE: {path}\n\n"
            f"EVIDENCE FROM EARLIER STEPS:\n{context or '(none)'}\n\n"
            f"CURRENT CONTENT OF {path}:\n<<<FILE\n{original}\nFILE>>>\n\n"
            "Return ONLY SEARCH/REPLACE blocks in exactly this format:\n"
            "<<<<<<< SEARCH\n(lines copied exactly from the current content)\n"
            "=======\n(the new lines)\n>>>>>>> REPLACE\n"
            "Each SEARCH must match the current content exactly once. Keep blocks "
            "small, change only what the step needs, and keep the file's style."
        ))
        applied, error = _apply_blocks(original, reply)
        if applied is None:
            logger.info("[BrainAuthor] conv=%s edit %s rejected: %s", conv_id, path, error)
            return None, None, error
        blocks, updated = applied
        if updated == original:
            return None, None, "the Brain's edit leaves the file unchanged"
        logger.info("[BrainAuthor] conv=%s edit %s: %d block(s)", conv_id, path, len(blocks))
        if len(blocks) == 1:
            # edit_file retries an LF quote as CRLF against a CRLF file.
            return "edit_file", {"path": path, "old": blocks[0][0], "new": blocks[0][1]}, ""
        # LF text: write_file writes in text mode, which emits the platform
        # line ending itself (converting here would double the CR).
        return "write_file", {"path": path, "content": updated}, ""
    except Exception as exc:  # noqa: BLE001 — a failed authoring is a failed step, never a crash
        logger.warning("[BrainAuthor] conv=%s %s %s failed: %s", conv_id, tool, path, exc)
        return None, None, f"Brain authoring failed: {exc}"
