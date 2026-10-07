"""Intent is MODE-INDEPENDENT (owner, 2026-10-07). Renamed from
`test_developer_mode_routes_to_der.py`, which pinned the OPPOSITE rule.

The old contract (execution audit B8) was: "in developer mode every request
that is not chitchat goes to the work loop", because the shared verb list had
no fix / implement / refactor, so "fix the bug in parser.py" was answered
conversationally. That over-corrected — it made INTENT differ by mode, so a
knowledge question in developer mode ran the whole work loop, and even "no
problem" spawned a task card.

The owner's rule, now the contract:

    Personal mode is the standard and the foundation. The two modes may differ
    in HOW a turn is displayed (matrix rows vs compact cards) and in what the
    agent is ALLOWED to do (edit / read / write its own code). They may never
    differ in WHAT KIND of turn it is.

So a work request routes to the work loop in BOTH modes (the verbs now live in
the shared layer as WORK_VERBS, matched on word boundaries), and a question
routes to the direct path in BOTH modes.

WHAT THIS FILE DOES NOT CLAIM: that the modes render the same. They do not —
`isDeveloper` still selects the matrix vs the compact card, the reasoning line,
the composer affordances and the ask rows. Display divergence is pinned in the
frontend, not here.

Behavioural note, stated so nobody is surprised: "why does parse_duration
return None" used to auto-investigate in developer mode. It is now a question
and takes the direct path in both modes. The intent is expressed as work —
"investigate why parse_duration returns None" routes to the loop (verified
below) — because the direct path has no tools.
"""

from backend.agent.semantic_gate import SemanticLogicGate


def _der(text, developer):
    return SemanticLogicGate(tool_mode="auto").compile_dag(
        text, developer=developer
    ).requires_der_kernel


# ── work requests: the work loop, in BOTH modes ────────────────────────────

_WORK = [
    "fix the bug in parser.py",
    "implement a new endpoint",
    "refactor this function",
    "migrate the store to the new schema",
    "rename the variable",
    "optimize the slow query",
    "investigate why parse_duration returns None",
    "diagnose the failing test",
]


def test_work_requests_go_to_der_in_both_modes():
    for text in _WORK:
        assert _der(text, developer=False) is True, (
            f"work request answered conversationally in personal mode: {text!r}"
        )
        assert _der(text, developer=True) is True, (
            f"work request missed the loop in developer mode: {text!r}"
        )


# ── questions and chitchat: the direct path, in BOTH modes ──────────────────

_DIRECT = [
    "why does parse_duration return None for 1h30m",
    "what is two plus two",
    "what is the capital of France?",
    "explain how recursion works",
    "no problem",
    "have a nice day",
    "thanks",
]


def test_questions_and_chitchat_stay_direct_in_both_modes():
    for text in _DIRECT:
        assert _der(text, developer=False) is False, (
            f"question went to the work loop in personal mode: {text!r}"
        )
        assert _der(text, developer=True) is False, (
            f"question went to the work loop in developer mode: {text!r} "
            "(this is the B8 override; personal is the foundation)"
        )


# ── the invariant itself: one decision, two modes ───────────────────────────

def test_routing_decision_is_identical_in_both_modes():
    matrix = _WORK + _DIRECT + [
        "search the web for quantum computing",
        "yes do it",
        "run the tests",
    ]
    for text in matrix:
        assert _der(text, developer=True) is _der(text, developer=False), (
            f"routing differs by mode for {text!r} — intent must not depend on mode"
        )


# ── word boundaries: a verb is a word, not a substring ─────────────────────

def test_work_verbs_do_not_match_inside_words():
    # The substring list already caused "spec"->"specific" and "doc"->"docker";
    # the new verbs must not repeat it ("fix" in "prefix", "port" in "report").
    for text in (
        "what is the prefix operator",
        "a report about support",
        "how does dispatch work",
        "export the notes",
        "this is important",
        "a fixture file",
    ):
        assert _der(text, developer=True) is False, (
            f"a word-boundary false positive sent {text!r} to the work loop"
        )