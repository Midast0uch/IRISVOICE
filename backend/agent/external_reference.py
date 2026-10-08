"""Classify a step's reference as EXTERNAL or LOCAL (2026-10-08).

WHY THIS EXISTS

A DER step can name a resource that does not live in the project - a GitHub repo,
a URL, a paper - while holding only local tools. Measured live (2026-10-07,
strand-7d1b7dac2c14): the plan step "Read the README and main files from the
OpenAI math repository" ran glob_files / grep_files INSIDE the project root for
~6 minutes and failed with "no dedicated `openai_math` repository folder exists in
the project root". The agent was searching the wrong DOMAIN and nothing noticed -
the existing pivot machinery (_der_maybe_open_recovery, the VISITED ledger's
"known-only discovery = pivot") only fires on FETCH failures, never on a local
search that missed.

This module is a DOMAIN COMPARISON, deliberately NOT a keyword list of web
phrasings. It answers two questions and nothing else:

  * does this reference point OUTSIDE the project?  -> ``is_external``
  * which tool family resolves it?                  -> ``resolving_tool``

so the caller can refuse a local dispatch and give the agent somewhere to go
instead. It does not dispatch anything, does not touch the network, and has no
state.

THE SHAPE DECIDES THE TOOL. A reference is not a string:

  url             https://github.com/adalso/openai-math  -> fetch
  repo_slug       adalso/openai-math                     -> AMBIGUOUS with a
                                                            local path; needs a
                                                            HOST. Disambiguated
                                                            by PROVENANCE (a URL
                                                            a previous turn
                                                            fetched).
  scholarly_id    arXiv:2609.26550 / 10.1234/xyz         -> search, then fetch
  host            github.com                             -> not a document;
                                                            search
  named_artifact  "the OpenAI math repo"                 -> search
  local_path      ./utils.py, backend/agent              -> local (proceed)
  none            no reference at all                    -> local (proceed)

``classify`` takes ``sources`` - the URLs earlier turns fetched - because a bare
``owner/name`` token is genuinely ambiguous without them. That is exactly why the
provenance fix had to land before this one: without a URL, ``adalso/openai-math``
is indistinguishable from a relative directory.
"""

from __future__ import annotations

import os
import re
from typing import Callable, Iterable, Optional, Sequence

# ── the shapes ───────────────────────────────────────────────────────────────
URL = "url"
REPO_SLUG = "repo_slug"
SCHOLARLY_ID = "scholarly_id"
HOST = "host"
NAMED_ARTIFACT = "named_artifact"
LOCAL_PATH = "local_path"
NONE = "none"

EXTERNAL_SHAPES = frozenset({URL, REPO_SLUG, SCHOLARLY_ID, HOST, NAMED_ARTIFACT})
LOCAL_SHAPES = frozenset({LOCAL_PATH, NONE})

# The tool families. `local` is the set whose every member reads or writes THIS
# machine's project - a step holding only these cannot reach an external
# resource, which is the mismatch this module exists to catch.
LOCAL_TOOLS = frozenset({
    "read_file", "edit_file", "write_file", "grep_files", "glob_files",
    "list_directory", "create_directory", "run_command", "git_status",
    "git_diff", "read_command_output", "stop_command",
})
# The tools that reach OUTSIDE the project. Deliberately a SUPERSET of the DER's
# own "go and fetch" vocabulary (`tool_envelope._GATHER_TOOLS`, KD-9) plus the
# browser / open-url family. The DER taxonomy leaves `open_url`, `browser_open`,
# `browser_observe`, `browser_act` and `browser_explore` as family `direct` even
# though they reach the network - a gap in KD-9, recorded here rather than
# silently inherited. tests/unit/test_external_reference.py pins the superset so
# the two vocabularies cannot drift apart.
EXTERNAL_TOOLS = frozenset({
    # the DER's own gather family (KD-9)
    "web_search", "websearch", "crawler_query", "search_discovery",
    "get_rendered_documents", "fetch_url", "crawl",
    # the search / open-url / browser family
    "search", "open_url",
    "browser_open", "browser_observe", "browser_act", "browser_explore",
})


def der_family(name: str) -> str:
    """The DER's expectation family for a tool (KD-9, ``tool_envelope.tool_family``).

    ORTHOGONAL to this module's domain axis, deliberately:

      * ``tool_family`` answers "what KIND of expectation does this tool set?"
        (gather / read / synthesis / action / direct) - the DER's KD-9 axis;
      * this module answers "which DOMAIN does it reach?" (project | network).

    Related but NOT interchangeable: a family-``gather`` tool is not automatically
    external, and ``run_command`` is family ``action`` yet reaches the network via
    curl. So ``EXTERNAL_TOOLS`` is authoritative for the DOMAIN question, and the
    family is used only to cross-check that the two vocabularies have not drifted
    (pinned in tests/unit/test_external_reference.py). Imported lazily so this
    module carries no import-time dependency.
    """
    try:
        from backend.agent.tool_envelope import tool_family

        return tool_family(name)
    except Exception:  # noqa: BLE001 — the domain answer never depends on it
        return ""


def is_external_tool(name: str) -> bool:
    """True when a tool can reach OUTSIDE the project."""
    return str(name or "") in EXTERNAL_TOOLS

# ── recognisers ──────────────────────────────────────────────────────────────
_URL_RE = re.compile(r"https?://[^\s<>\"')]+", re.IGNORECASE)
_SCHOLARLY_RE = re.compile(
    r"(?:\barxiv:\s*\d{4}\.\d{4,5}|\bdoi:\s*10\.\d{4,}/\S+|(?<![\d.])10\.\d{4,}/\S+)",
    re.IGNORECASE,
)
_HOST_RE = re.compile(
    r"\b(?:[a-z0-9-]+\.)+(?:com|org|net|io|ai|dev|gov|edu|co|gg)\b", re.IGNORECASE
)
# `owner/name` - a repo slug AND the shape a relative directory takes.
# Multi-segment so a real project path (`backend/agent/x.py`) is recognised too.
_SLUG_RE = re.compile(r"(?<![\w./-])([A-Za-z0-9][\w.-]*(?:/[\w.-]+)+)")
# "the OpenAI math repo", "that paper", "the docs" - a resource named by KIND,
# which needs a SEARCH because there is no address to fetch.
_NAMED_ARTIFACT_RE = re.compile(
    r"\b(?:repo(?:sitory)?|project|paper|article|preprint|publication|docs|"
    r"documentation|blog|post|thread|issue|release|website|site)\b",
    re.IGNORECASE,
)


def _hosts_in(text: str) -> list[str]:
    return [m.group(0).lower() for m in _HOST_RE.finditer(text or "")]


def _source_tokens(sources: Iterable[str]) -> set[str]:
    """``owner/name`` tokens carried by the URLs earlier turns fetched.

    A source ``https://github.com/adalso/openai-math`` yields
    ``{"adalso/openai-math"}`` - the corroboration that turns an ambiguous slug
    into an EXTERNAL one.
    """
    out: set[str] = set()
    for raw in sources or ():
        try:
            tail = str(raw).split("://", 1)[-1]
            parts = [p for p in tail.split("/") if p]
        except Exception:  # noqa: BLE001 — a malformed source is skipped
            continue
        if len(parts) >= 3:                       # host/owner/name[...]
            out.add(f"{parts[1]}/{parts[2]}".lower())
        if len(parts) >= 2:                       # host/owner
            out.add(f"{parts[0]}/{parts[1]}".lower())
    return out


def classify(
    goal: str,
    sources: Sequence[str] = (),
    *,
    exists: Optional[Callable[[str], bool]] = None,
) -> str:
    """The shape of the reference in ``goal``. See the module docstring.

    ``exists`` is injected (defaults to ``os.path.exists``) so the decision stays
    pure and testable, and so a caller can supply a project-relative resolver.
    """
    text = goal or ""
    if not text.strip():
        return NONE

    if _URL_RE.search(text):
        return URL
    if _SCHOLARLY_RE.search(text):
        return SCHOLARLY_ID

    _exists = exists or os.path.exists
    known = _source_tokens(sources)

    # `owner/name` - external only when the PROVENANCE or the filesystem says so.
    # A slug that is really a path in the project stays local; a slug a previous
    # turn fetched as a URL is external even though it looks identical.
    for m in _SLUG_RE.finditer(text):
        tok = m.group(1)
        if tok.lower() in known:
            return REPO_SLUG
    _saw_project_path = False
    for m in _SLUG_RE.finditer(text):
        tok = m.group(1)
        try:
            if _exists(tok):
                _saw_project_path = True
                continue
        except Exception:  # noqa: BLE001 — an unreadable path is not evidence
            continue
        # `and/or` is not a repo. Require the token to LOOK like a slug or a
        # path - a dot, dash or underscore - so ordinary prose cannot fire this.
        if not any(ch in tok for ch in ".-_"):
            continue
        return REPO_SLUG
    if _saw_project_path:
        return LOCAL_PATH

    # A bare host only counts when it is not the tail of a path we just cleared.
    if _hosts_in(text):
        return HOST

    if _NAMED_ARTIFACT_RE.search(text):
        return NAMED_ARTIFACT

    # An explicit local path is a reference too - and it is NOT external.
    if re.search(r"(?:^|\s)(?:\.{1,2}/|/)", text):
        return LOCAL_PATH

    return NONE


def first_url(text: str) -> str:
    """The first http(s) URL in the text, or "" - the exact param `open_url`
    takes (``parameters={"url": {...}}``). Trailing sentence punctuation is
    stripped so a URL ending a clause still resolves."""
    m = _URL_RE.search(text or "")
    return m.group(0).rstrip(".,;:!?)\"'") if m else ""


def is_external(shape: str) -> bool:
    """True when the shape points outside the project."""
    return shape in EXTERNAL_SHAPES


def resolving_tool(shape: str) -> Optional[str]:
    """The tool family that resolves this shape, or None when it is local.

    ``search`` when there is no address to fetch (a slug with no provenance, a
    host, a named artifact); ``crawler_query`` when the goal carries something
    fetchable. Returning a name rather than dispatching keeps this pure - the
    caller decides whether it may actually run.
    """
    if shape == URL:
        # A specific address: fetch THAT, rather than running a broad research
        # crawl. `open_url` takes {"url": ...} - see `first_url`.
        return "open_url"
    if shape == REPO_SLUG:
        # The slug itself is not fetchable without a host; resolve by search
        # unless the caller has the URL (it then classifies as URL above).
        return "search"
    if shape in (SCHOLARLY_ID, HOST, NAMED_ARTIFACT):
        return "search"
    return None


def local_tools_only(tool_names: Iterable[str]) -> bool:
    """True when EVERY named tool is local - i.e. the step cannot reach outside.

    An empty set is False: a step with no tools at all is a different problem
    (nothing was offered) and must not be read as a domain mismatch.
    """
    names = {str(n) for n in (tool_names or ()) if n}
    if not names:
        return False
    return names <= LOCAL_TOOLS


def domain_mismatch(
    goal: str,
    tool_names: Iterable[str],
    sources: Sequence[str] = (),
    *,
    exists: Optional[Callable[[str], bool]] = None,
) -> Optional[str]:
    """The shape when a goal names an EXTERNAL resource while the tools IN PLAY
    are all local - the mismatch worth correcting. None when there is nothing to
    correct.

    ``tool_names`` is the tool or tools about to be used: pass the step's PICK
    (``[name]``) to ask "is this pick the wrong domain?", or the whole offered
    menu to ask "can this step reach outside at all?" (the web-toggle-off case).
    The two are different questions and this function answers whichever set it
    is handed.

    Note the menu normally holds BOTH families - that is what lets a task move
    local -> external -> local freely - so a mismatch on the MENU means the
    capability is absent, while a mismatch on the PICK means the capability was
    available and the wrong one was chosen.
    """
    shape = classify(goal, sources, exists=exists)
    if not is_external(shape):
        return None
    if not local_tools_only(tool_names):
        return None
    return shape


# ── mode: what KIND of node runs this goal (2026-10-08, unification) ─────────
#
# THE STRUCTURAL SIGNAL - deliberately NOT the `mode` decision-engine consumer.
# That consumer cannot be calibrated: its label is agreement with
# `mode_detector._infer_mode`, a SUBSTRING keyword scorer whose default is
# IMPLEMENT/0.3, so there is no learnable signal in the target (measured
# 2026-10-08: AUROC 0.4906, ECE 0.2313 against a 0.05 bound). Deriving the mode
# from the GOAL instead is the same shape as the domain guard above: no model
# call, no keyword phrasing table, nothing to calibrate.
#
# A "direct" node answers the goal from the model's own knowledge. A "react"
# node runs the planned tool loop. The rule is CONSERVATIVE BY CONSTRUCTION:
# only a goal with no reference AND no work requirement is direct, so a miss
# costs a plan that was not needed - never a step that could not reach a tool it
# required.
DIRECT = "direct"
REACT = "react"


# A goal is DIRECT only when it reads as a QUESTION. This is the conservative
# half of the rule, and it matters because a wrong DIRECT produces a WRONG
# ANSWER (the node answers from the model's head instead of reading the file),
# not merely a slow one. Measured against the rule without it: "read the config
# file" has no reference shape and no verb in ACTION_VERBS/WORK_VERBS, so it was
# classified direct - and it plainly needs read_file.
#
# It is safe to be this strict because the TURN router already sends trivial and
# conversational messages to _respond_direct: nodes only exist for task turns,
# so a node whose goal is a plain question is the rare case this optimises.
_QUESTION_RE = re.compile(
    r"^\s*(?:what|who|when|where|why|which|whose|how|"
    r"is|are|was|were|do|does|did|can|could|should|would|will|"
    r"explain|define|describe|compare|summari[sz]e|tell)\b",
    re.IGNORECASE,
)


def _needs_work(goal: str) -> bool:
    """Does the goal ask for work, rather than for an answer?

    Uses the codebase's OWN routing vocabulary (`semantic_gate.ACTION_VERBS` /
    `WORK_VERBS`) rather than a new list, matched on WORD BOUNDARIES because
    `ACTION_VERBS` matches substrings ("fix" would fire inside "prefix").

    Fails SAFE: if the vocabulary cannot be read, this reports True so the node
    is planned - a needless plan is cheap, a step without the tool it needed is
    not.
    """
    t = (goal or "").lower()
    if not t.strip():
        return False
    try:
        from backend.agent.semantic_gate import ACTION_VERBS, WORK_VERBS

        words = set(re.findall(r"[a-z_]+", t))
        verbs = set(ACTION_VERBS) | set(WORK_VERBS)
        return bool(words & verbs)
    except Exception:  # noqa: BLE001 — unknown means "plan it"
        return True


def mode_for_goal(
    goal: str,
    sources: Sequence[str] = (),
    *,
    exists: Optional[Callable[[str], bool]] = None,
) -> str:
    """``DIRECT`` or ``REACT`` for a node's goal.

    Chosen ONCE, at node entry - the mode is an execution detail, never switched
    mid-step and never surfaced in the card.

    A goal needs the tool loop (REACT) when it names anything the model cannot
    answer from its own knowledge:

      * an EXTERNAL reference  (url / repo_slug / scholarly_id / host /
        named_artifact) - there is something to go and fetch;
      * a LOCAL path that exists - there is something to read;
      * an action/work verb - there is something to do.

    Otherwise the goal is a question about the world the model already holds, so
    the node answers it directly.
    """
    shape = classify(goal, sources, exists=exists)
    if is_external(shape):
        return REACT
    if shape == LOCAL_PATH:
        return REACT
    if _needs_work(goal):
        return REACT
    # No reference and no work verb - but only a QUESTION is safe to answer from
    # the model's own knowledge. Anything else might still need a tool the text
    # does not name ("read the config file"), and a wrong DIRECT is a wrong
    # answer rather than a slow one.
    if not _QUESTION_RE.match(goal or ""):
        return REACT
    return DIRECT
