"""The external/local DOMAIN classifier and the DER alignment (2026-10-08).

WHY THIS FILE EXISTS

A DER step can name a resource that does not live in the project - a GitHub repo,
a URL, a paper - while holding only local tools. Measured live (2026-10-07,
strand-7d1b7dac2c14): the step "Read the README and main files from the OpenAI
math repository" ran glob_files / grep_files INSIDE the project root for ~6
minutes and failed with "no dedicated `openai_math` repository folder exists in
the project root". The repo was on GitHub. Nothing noticed the wrong DOMAIN.

Pinned here:
  1. the shapes, including the two that must NOT fire (prose like "and/or", and a
     real project path - even when provenance is present);
  2. a bare `owner/name` slug is external only when PROVENANCE or the filesystem
     says so - the ambiguity that made the provenance fix a prerequisite;
  3. `domain_mismatch` answers the PICK question and the MENU question
     separately, because the menu normally holds BOTH families (that is what
     lets a task move local -> external -> local);
  4. the DER ALIGNMENT: this module's domain axis is orthogonal to
     `tool_envelope.tool_family` (KD-9), and the two vocabularies must not drift.
"""

from __future__ import annotations

import pytest

from backend.agent import external_reference as xr

_SOURCES = [
    "https://github.com/adalso/openai-math",
    "https://github.com/openai/ten-proofs",
]

# `exists` is injected so the cases are cwd-independent and pure.
_NO_FS = lambda _t: False          # noqa: E731
_ALL_FS = lambda _t: True          # noqa: E731


# ── 1. the shapes ────────────────────────────────────────────────────────────
@pytest.mark.parametrize("goal, sources, expected", [
    # the ACTUAL failing step, both phrasings the planner produced
    ("Read the README and main files from the OpenAI math repository", [], xr.NAMED_ARTIFACT),
    ("Explore the OpenAI repository to identify key files and content", [], xr.NAMED_ARTIFACT),
    ("read the docs for this", [], xr.NAMED_ARTIFACT),
    ("fetch https://github.com/adalso/openai-math", [], xr.URL),
    ("summarise arXiv:2609.26550", [], xr.SCHOLARLY_ID),
    ("summarise doi:10.1234/xyz", [], xr.SCHOLARLY_ID),
    ("what is on github.com", [], xr.HOST),
    # MUST NOT fire
    ("fix the off-by-one error in utils.py", [], xr.NONE),
    ("run the test suite", [], xr.NONE),
    ("thanks", [], xr.NONE),
    ("", [], xr.NONE),
    ("add and/or logic to the parser", [], xr.NONE),      # prose, not a repo
])
def test_shapes(goal, sources, expected):
    assert xr.classify(goal, sources, exists=_NO_FS) == expected


def test_prose_slash_is_not_a_slug():
    """`and/or` is the false positive that would break ordinary goals."""
    assert xr.classify("support and/or improve the parser", [], exists=_NO_FS) == xr.NONE
    assert not xr.is_external(xr.classify("support and/or improve it", [], exists=_NO_FS))


# ── 2. the slug ambiguity ────────────────────────────────────────────────────
def test_slug_needs_provenance_or_the_filesystem():
    """A bare `owner/name` is indistinguishable from a relative path."""
    # no provenance, nothing on disk -> external
    assert xr.classify("look into adalso/openai-math", [], exists=_NO_FS) == xr.REPO_SLUG
    # provenance corroborates it -> external
    assert xr.classify("look into adalso/openai-math", _SOURCES, exists=_NO_FS) == xr.REPO_SLUG
    # a REAL project path stays local, even with provenance present
    assert xr.classify("read backend/agent/agent_kernel.py", [], exists=_ALL_FS) == xr.LOCAL_PATH
    assert xr.classify(
        "read backend/agent/agent_kernel.py", _SOURCES, exists=_ALL_FS
    ) == xr.LOCAL_PATH


# ── 3. the guard's predicate ─────────────────────────────────────────────────
_LOCAL = ["read_file", "edit_file", "grep_files", "glob_files", "run_command"]
_MIXED = _LOCAL + ["search", "crawler_query", "browser_open"]


def test_mismatch_on_the_pick():
    """goal external + the PICK is local -> correct it."""
    g = "Read the README and main files from the OpenAI math repository"
    assert xr.domain_mismatch(g, ["glob_files"], []) == xr.NAMED_ARTIFACT
    assert xr.domain_mismatch(g, ["grep_files"], []) == xr.NAMED_ARTIFACT


def test_no_mismatch_on_local_goals():
    """Local work keeps its local tools - the guard must be silent."""
    for goal in ("fix the off-by-one error in utils.py",
                 "run the test suite",
                 "add and/or logic to the parser"):
        assert xr.domain_mismatch(goal, ["grep_files"], []) is None


def test_menu_vs_pick_are_different_questions():
    """A MIXED menu is NOT a mismatch (both families are legitimately offered);
    an ALL-LOCAL menu IS (the capability is absent - the web-toggle-off case)."""
    g = "Read the README from the OpenAI repository"
    assert xr.domain_mismatch(g, _MIXED, []) is None          # pick-question
    assert xr.domain_mismatch(g, _LOCAL, []) == xr.NAMED_ARTIFACT  # menu-question
    assert xr.local_tools_only(_LOCAL) is True
    assert xr.local_tools_only(_MIXED) is False
    assert xr.local_tools_only([]) is False   # no tools is a DIFFERENT problem


def test_resolving_tool_families():
    assert xr.resolving_tool(xr.NAMED_ARTIFACT) == "search"
    assert xr.resolving_tool(xr.HOST) == "search"
    assert xr.resolving_tool(xr.SCHOLARLY_ID) == "search"
    assert xr.resolving_tool(xr.REPO_SLUG) == "search"
    # a specific address is FETCHED, not researched - open_url takes {"url": ...}
    assert xr.resolving_tool(xr.URL) == "open_url"
    assert xr.resolving_tool(xr.LOCAL_PATH) is None
    assert xr.resolving_tool(xr.NONE) is None


def test_first_url_is_the_open_url_param():
    """The exact param `open_url` needs (parameters={"url": {...}})."""
    assert xr.first_url("fetch https://github.com/a/b please") == "https://github.com/a/b"
    # trailing sentence punctuation must not ride along
    assert xr.first_url("see https://example.com/x.") == "https://example.com/x"
    assert xr.first_url("(https://example.com/y)") == "https://example.com/y"
    assert xr.first_url("no url here") == ""


# ── 4. DER alignment ─────────────────────────────────────────────────────────
def test_external_tools_superset_of_der_gather_family():
    """The DER's own "go and fetch" vocabulary must be a SUBSET of what this
    module treats as external - otherwise a goal that leads the agent to
    `fetch_url` would not be recognised as external and the guard would stay
    silent. This is the direction that must hold; the reverse does NOT (see the
    next test), because the axes are orthogonal."""
    from backend.agent.tool_envelope import _GATHER_TOOLS

    missing = set(_GATHER_TOOLS) - xr.EXTERNAL_TOOLS
    assert not missing, (
        f"the DER gather family names {sorted(missing)} but this module does not "
        "treat them as external - the vocabularies have drifted"
    )


def test_der_family_gap_is_closed():
    """The KD-9 gap this module found is now CLOSED (2026-10-08).

    The open-url and browser RETRIEVAL tools are family `gather`, so they inherit
    the recovery semantics a failed fetch needs - `agent_kernel.py:6991` gates the
    VLM recovery path on `tool_family(...) == "gather"`, so while they were
    `direct` a browser step that came back with nothing was never offered
    recovery, which is the case that needs it most.

    The axes stay orthogonal: `gather` implies external, but external does not
    imply `gather` for a tool whose expectation is genuinely an action.
    """
    from backend.agent.tool_envelope import tool_family

    # every network-RETRIEVING tool is now gather, and external
    for n in ("crawler_query", "fetch_url", "search", "open_url",
              "browser_open", "browser_observe", "browser_explore"):
        assert tool_family(n) == "gather", f"{n} should be family gather"
        assert xr.is_external_tool(n), f"{n} should be external"

    # the one that ACTS on the page stays out of gather (it changes state rather
    # than retrieving), while still being external
    assert tool_family("browser_act") == "action"
    assert xr.is_external_tool("browser_act")


def test_der_family_helper_is_total():
    """`der_family` never raises, whatever it is handed."""
    for n in ("read_file", "search", "not_a_tool", ""):
        assert isinstance(xr.der_family(n), str)


def test_local_and_external_tool_sets_are_disjoint():
    assert not (xr.LOCAL_TOOLS & xr.EXTERNAL_TOOLS)


# ── 5. mode: what KIND of node runs this goal (unification) ──────────────────
@pytest.mark.parametrize("goal", [
    "what is the capital of France",
    "who wrote the Iliad",
    "how many continents are there",
])
def test_question_with_no_reference_is_direct(goal):
    assert xr.mode_for_goal(goal, exists=_NO_FS) == xr.DIRECT


@pytest.mark.parametrize("goal", [
    # a tool the text does not name - the case that made the rule conservative
    "read the config file",
    "fix the off-by-one error in utils.py",
    "create three files in the repo root",
    # an external reference
    "fetch https://github.com/adalso/openai-math",
    "look into adalso/openai-math",
    "Read the README and main files from the OpenAI math repository",
    "summarise arXiv:2609.26550",
    # not a question at all
    "thanks",
    "",
])
def test_everything_else_reacts(goal):
    assert xr.mode_for_goal(goal, exists=_NO_FS) == xr.REACT


def test_direct_is_conservative_by_construction():
    """A wrong DIRECT is a WRONG ANSWER (the node answers from the model's head
    instead of reading the file), not merely a slow one - so DIRECT requires a
    positive question signal AND no reference AND no work verb.

    This is safe to be strict about because the TURN router already sends
    trivial/conversational messages to _respond_direct; nodes only exist for
    task turns.
    """
    # a work verb beats a question form
    assert xr.mode_for_goal("how do I fix the parser", exists=_NO_FS) == xr.REACT
    # an external reference beats a question form
    assert xr.mode_for_goal("what is at github.com", exists=_NO_FS) == xr.REACT
    # a real project path beats a question form
    assert xr.mode_for_goal(
        "what does backend/agent/x.py do", exists=_ALL_FS
    ) == xr.REACT


def test_mode_reuses_the_codebase_vocabulary():
    """`_needs_work` must use semantic_gate's own verb lists, not a new one."""
    from backend.agent.semantic_gate import ACTION_VERBS, WORK_VERBS

    assert ACTION_VERBS and WORK_VERBS
    assert xr._needs_work("fix the bug") is True      # WORK_VERBS
    assert xr._needs_work("analyze the output") is True  # ACTION_VERBS
    assert xr._needs_work("what is two plus two") is False
