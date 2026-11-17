"""Workbench ground: what is in the current folder, as one short bounded text.

Pure and stdlib only (the worker package stays importable stand-alone). A model that
starts a coding step with no listing spends its first scripts on `os.listdir`; the
ground text gives it the folder up front: numbered runs collapsed (`svc-01.txt ..
svc-14.txt`), sizes, and the first lines of a few text files. Bounded in time (50 ms),
entries (2,000), depth (3) and size (1,200 chars). Never raises: an error -> "" and
one counted failure.

`profile=True` (code nodes, not the planner) replaces the 2 head lines of the files NAMED in
the task with a profile: a small file whole, a big CSV/TSV as header + 2 rows + row count,
any other text file as a line count and its top line SHAPES (digit runs and hex ids -> "#"),
so a severity field, an error-code pattern or a short rule file shows without a "look at
the data" script. Bounded: 256 KB read per file, 150 ms in all, the same max_chars.
"""
import logging
import os
import re
import time
from collections import deque
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

HEADER = "PROJECT FILES (the current folder; already listed - do not list it again):"
SKIP_DIRS = frozenset({".git", "__pycache__", "node_modules", ".venv", "venv", ".mypy_cache",
                       ".pytest_cache", ".iris-worktree"})
TEXT_EXT = frozenset({".txt", ".csv", ".tsv", ".log", ".json", ".yaml", ".yml", ".ini", ".cfg",
                      ".toml", ".md", ".py", ".sql"})
HEAD_FILES = 6               # files that get head lines
HEAD_LINES = 2               # head lines per file
HEAD_LINE_CHARS = 160
HEAD_READ_BYTES = 2048       # never read more than this of a file
RUN_MIN = 3                  # a numbered run collapses from this many files
FOLDER_NAMES_MAX = 12        # single files listed per folder before "+N more"
LINE_MAX = 300
FILES_MAX = 200              # ground_files
PROFILE_FILES = 6            # files profiled (profile=True)
PROFILE_WHOLE_BYTES = 2000   # a file this small is shown whole
PROFILE_READ_BYTES = 256 * 1024
PROFILE_BUDGET_MS = 150
PROFILE_SHAPES = 6
PROFILE_SHAPE_TOKENS = 5
PROFILE_CUT_NOTE = "(profile cut)"
CUT_NOTE = "(listing cut)"
MORE_NOTE = "(more files not shown)"

_DIGITS = re.compile(r"\d+")
_HEXID = re.compile(r"\b(?=[0-9a-fA-F]*\d)[0-9a-fA-F]{8,}\b")
_failures = 0                # ground / ground_files calls that raised (counted, never raised)


def failures() -> int:
    return _failures


def _fail(what: str, workdir: str, exc: BaseException) -> None:
    global _failures
    _failures += 1
    logger.warning("[Workbench][ground] %s failed for %r: %r", what, workdir, exc)


def _size(n: int) -> str:
    if n < 100:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / (1024 * 1024):.1f} MB"


def _natural(name: str):
    return [int(p) if p.isdigit() else p.lower() for p in re.split(r"(\d+)", name)]


class _Folder:
    __slots__ = ("rel", "files", "dirs")

    def __init__(self, rel: str):
        self.rel, self.files, self.dirs = rel, [], []     # files: [(name, size)]


def _walk(workdir: str, budget_ms: int, max_entries: int, max_depth: int) -> Tuple[List[_Folder], bool]:
    """Breadth first. -> (folders in visit order, cut): `cut` is True when the time budget
    or the entry cap stopped the walk."""
    t_end = time.perf_counter() + budget_ms / 1000.0
    folders: List[_Folder] = []
    todo = deque([(workdir, "", 0)])
    entries, cut = 0, False
    while todo:
        if time.perf_counter() > t_end:
            return folders, True
        path, rel, depth = todo.popleft()
        folder = _Folder(rel)
        try:
            with os.scandir(path) as it:
                for ent in it:
                    entries += 1
                    if entries > max_entries or (entries & 255 == 0 and time.perf_counter() > t_end):
                        cut = True
                        break
                    try:
                        is_dir = ent.is_dir(follow_symlinks=False)
                    except OSError:
                        continue
                    if is_dir:
                        if ent.name in SKIP_DIRS or ent.name.startswith("."):
                            continue
                        folder.dirs.append(ent.name)
                    else:
                        try:
                            size = ent.stat(follow_symlinks=False).st_size
                        except OSError:
                            size = 0
                        folder.files.append((ent.name, size))
        except OSError:
            continue                                  # unreadable folder: not listed
        folder.files.sort(key=lambda f: _natural(f[0]))
        folder.dirs.sort(key=_natural)
        folders.append(folder)
        if cut:
            return folders, True
        if depth < max_depth:
            for d in folder.dirs:
                todo.append((os.path.join(path, d), f"{rel}{d}/", depth + 1))
    return folders, cut


def _runs(files: List[Tuple[str, int]]) -> Tuple[List[List[Tuple[str, int]]], List[Tuple[str, int]]]:
    """Split a folder's files into numbered runs (>= RUN_MIN names equal but for digits) and the rest."""
    groups: Dict[str, List[Tuple[str, int]]] = {}
    for f in files:
        if _DIGITS.search(f[0]):
            groups.setdefault(_DIGITS.sub("#", f[0]), []).append(f)
    runs = [g for g in groups.values() if len(g) >= RUN_MIN]
    in_run = {f[0] for g in runs for f in g}
    return runs, [f for f in files if f[0] not in in_run]


def _run_text(run: List[Tuple[str, int]]) -> str:
    lo, hi = min(s for _, s in run), max(s for _, s in run)
    a, b = _size(lo), _size(hi)
    if a == b:
        span = a
    elif a.split()[1] == b.split()[1]:
        span = f"{a.split()[0]}-{b}"                 # 7.3-7.8 KB
    else:
        span = f"{a}-{b}"
    return f"{len(run)} files  {run[0][0]} .. {run[-1][0]}  {span} each"


def _head(path: str) -> List[str]:
    """The first HEAD_LINES non-empty lines of a text file (<= 2 KB read), or [] for a binary
    or undecodable one."""
    try:
        with open(path, "rb") as fh:
            raw = fh.read(HEAD_READ_BYTES)
    except OSError:
        return []
    if b"\x00" in raw:
        return []
    text = None
    for cut in range(0, 4):                            # a multi-byte char cut at the 2 KB edge
        try:
            text = raw[:len(raw) - cut].decode("utf-8")
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        return []
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()][:HEAD_LINES]
    return [ln if len(ln) <= HEAD_LINE_CHARS else ln[:HEAD_LINE_CHARS - 3] + "..." for ln in lines]


def _clip(ln: str, n: int) -> str:
    return ln if len(ln) <= n else ln[:n - 3] + "..."


def _shape(line: str) -> str:
    """A line with hex-like ids and digit runs -> "#"; only the first tokens, then "..."."""
    toks = _DIGITS.sub("#", _HEXID.sub("#", line)).split()
    out = " ".join(toks[:PROFILE_SHAPE_TOKENS])
    return out + " ..." if len(toks) > PROFILE_SHAPE_TOKENS else out


def _profile(path: str, name: str, size: int, t_end: float) -> Optional[List[str]]:
    """The profile lines of one text file (see the module doc), or None for a binary or
    unreadable one. Reads at most PROFILE_READ_BYTES."""
    try:
        with open(path, "rb") as fh:
            raw = fh.read(PROFILE_READ_BYTES)
    except OSError:
        return None
    if b"\x00" in raw:
        return None
    partial = size > len(raw)
    text = raw.decode("utf-8", errors="replace")
    lines = text.splitlines()
    if partial and lines:
        lines.pop()                                     # the last line is cut at the read edge
    if size <= PROFILE_WHOLE_BYTES:
        return [f"  {name} (whole file):"] + ["    " + _clip(ln, LINE_MAX) for ln in lines]
    est = len(lines) if not partial else int(len(lines) * size / max(len(raw), 1))
    n = f"~{est}" if partial else str(est)
    if os.path.splitext(name)[1].lower() in (".csv", ".tsv"):
        rows = [ln for ln in lines if ln.strip()]
        shown = [f"    {_clip(ln, HEAD_LINE_CHARS)}" for ln in rows[:3]]
        total = max(len(rows) - 1, 0) if not partial else max(int(len(rows) * size / max(len(raw), 1)) - 1, 0)
        return [f"  {name} ({'~' if partial else ''}{total} rows):"] + shown
    counts: Dict[str, int] = {}
    example: Dict[str, str] = {}
    for i, ln in enumerate(lines):
        if i & 1023 == 1023 and time.perf_counter() > t_end:
            break
        if not ln.strip():
            continue
        sh = _shape(ln)
        counts[sh] = counts.get(sh, 0) + 1
        example.setdefault(sh, ln.strip())
    top = sorted(counts, key=lambda k: -counts[k])[:PROFILE_SHAPES]    # stable: ties keep file order
    out = [f"  {name} ({n} lines):"]
    for sh in top:
        out.append(f"    {counts[sh]}x  {sh} e.g. {_clip(example[sh], HEAD_LINE_CHARS)}")
    return out


def _is_text(name: str) -> bool:
    return os.path.splitext(name)[1].lower() in TEXT_EXT


def _named_in(text: str, rel: str, name: str) -> bool:
    low = text.lower()
    return name.lower() in low or (rel + name).lower() in low


def _head_choice(folders: List[_Folder], text: str, profile: bool = False) -> List[Tuple[int, str]]:
    """Which files get head lines: named in `text` first, then the first file of each
    collapsed run, then the other text files in listing order; at most HEAD_FILES."""
    named, firsts, rest = [], [], []
    for i, f in enumerate(folders):
        runs, singles = _runs(f.files)
        first_of_run = {g[0][0] for g in runs}
        in_run = {n for g in runs for n, _ in g}
        for name, _ in f.files:
            if not _is_text(name):
                continue
            key = (i, name)
            if text and _named_in(text, f.rel, name):
                named.append(key)
            elif name in first_of_run:
                firsts.append(key)
            elif name not in in_run:
                rest.append(key)
    if profile and named:
        return named[:PROFILE_FILES]
    return (named + firsts + rest)[:PROFILE_FILES if profile else HEAD_FILES]


def ground(workdir: str, text: str = "", budget_ms: int = 50, max_entries: int = 2000,
           max_depth: int = 3, max_chars: int = 1200, profile: bool = False) -> str:
    """The folder as bounded text (see the module doc). `text` = the task and goal: a text
    file named in it gets its head lines first. Returns "" for an empty or missing folder,
    and on any error (counted: failures())."""
    try:
        t_end = time.perf_counter() + budget_ms / 1000.0
        folders, cut = _walk(workdir, budget_ms, max_entries, max_depth)
        if not any(f.files or f.dirs for f in folders):
            return ""
        chosen = _head_choice(folders, text or "", profile)
        heads: Dict[Tuple[int, str], List[str]] = {}
        profiles: Dict[Tuple[int, str], List[str]] = {}
        profile_cut = False
        p_end = time.perf_counter() + PROFILE_BUDGET_MS / 1000.0
        for key in chosen:
            if profile:
                if time.perf_counter() > p_end:
                    profile_cut = True
                    break
                f = folders[key[0]]
                size = next((s for n, s in f.files if n == key[1]), 0)
                got = _profile(os.path.join(workdir, f.rel, key[1]), f"{f.rel}{key[1]}", size, p_end)
                if got:
                    profiles[key] = got
                continue
            if time.perf_counter() > t_end:
                cut = True
                break
            heads[key] = _head(os.path.join(workdir, folders[key[0]].rel, key[1]))
        body: List[str] = []
        for i, f in enumerate(folders):
            runs, singles = _runs(f.files)
            parts = [_run_text(g) for g in runs]
            parts += [f"{n} {_size(s)}" for n, s in singles[:FOLDER_NAMES_MAX]]
            if len(singles) > FOLDER_NAMES_MAX:
                parts.append(f"+{len(singles) - FOLDER_NAMES_MAX} more")
            if not parts:
                if f.dirs or not f.rel:
                    continue                           # only subfolders: they list themselves
                parts = ["(empty)"]
            label = f.rel or "./"
            if len(runs) == 1 and not singles:
                line = f"{label}  {parts[0]}"
            else:
                line = f"{label}  " + " | ".join(parts)
            body.append(line if len(line) <= LINE_MAX else line[:LINE_MAX - 3] + "...")
            for name, _ in f.files:
                for ln in heads.get((i, name), ()):
                    body.append(f"  {name} starts: {ln}")
                body.extend(profiles.get((i, name), ()))
        tail = [CUT_NOTE] if cut else []
        if profile_cut:
            tail.append(PROFILE_CUT_NOTE)
        lines = [HEADER] + body + tail
        if sum(len(x) + 1 for x in lines) - 1 > max_chars:
            keep, used = [HEADER], len(HEADER)
            reserve = len(MORE_NOTE) + 1 + sum(len(t) + 1 for t in tail)
            for x in body:
                if used + 1 + len(x) + reserve > max_chars:
                    break
                keep.append(x)
                used += 1 + len(x)
            lines = keep + [MORE_NOTE] + tail
        return "\n".join(lines)[:max(max_chars, 0)]
    except Exception as exc:  # noqa: BLE001 - ground never raises
        _fail("ground", workdir, exc)
        return ""


def ground_files(workdir: str, budget_ms: int = 50, max_entries: int = 2000,
                 max_depth: int = 3) -> List[str]:
    """Relative forward-slash paths of the listed files, at most FILES_MAX, in listing
    order: the value of the namespace variable `files`. [] on any error (counted)."""
    try:
        out: List[str] = []
        folders, _ = _walk(workdir, budget_ms, max_entries, max_depth)
        for f in folders:
            for name, _ in f.files:
                out.append(f"{f.rel}{name}")
                if len(out) >= FILES_MAX:
                    return out
        return out
    except Exception as exc:  # noqa: BLE001
        _fail("ground_files", workdir, exc)
        return []
