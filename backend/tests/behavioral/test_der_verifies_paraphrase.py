"""
Behavioral test: a DER step whose expected output is satisfied in different
words is recorded VERIFIED when a semantic encoder is injected.

This is the inverse of today's substring-only verifier — a paraphrase
(same meaning, different words) must score as VERIFIED, not FAILED.
"""

from __future__ import annotations

import re
from unittest import mock

from backend.agent.agent_kernel import AgentKernel
from backend.agent.verifier import SemanticVerifier


# ---------------------------------------------------------------------------
# Fake encoder that treats paraphrases as semantically equivalent
# ---------------------------------------------------------------------------

def _paraphrase_accepting_encoder(assertion: str, result: str) -> float:
    """Return high similarity when the result is a clear paraphrase of the
    assertion, low otherwise.

    A rule-based stand-in for a real embedding model.  Three tiers:
      1. TRULY DONE — result contains past-tense evidence of the
         assertion's action + shared domain terms → high (>= 0.85).
      2. PROMISE/INTENT — result uses future/intent framing → low (0.25).
      3. GENERIC — result only says "completed" without specifics → low (< 0.3).
    """
    a_lower = assertion.lower()
    r_lower = result.lower()

    # ---- intent markers → low ----
    _INTENT = {"will", "going to", "plan to", "i will", "i'll", "aim to",
               "i should", "i need to", "i intend", "my task is"}
    if any(m in r_lower for m in _INTENT):
        return 0.25

    # ---- generic completion → low ----
    _GENERIC = {"completed successfully", "finished without errors",
                "all steps done", "task complete", "operation finished",
                "everything went according to plan"}
    if any(g in r_lower for g in _GENERIC):
        return 0.05

    # ---- extract key elements from assertion ----
    import re as _re
    a_tokens = _re.findall(r"[a-z0-9']+", a_lower)
    a_words = set(a_tokens)

    # key noun (typically the last content word of the assertion)
    key_noun = next((w for w in reversed(a_tokens) if w not in
                     {"the", "a", "an", "of", "to", "in", "for", "is",
                      "was", "be", "this", "that", "user", "their",
                      "your", "my", "its"}), "")
    # key verb (first word)
    key_verb = a_tokens[0] if a_tokens else ""

    # Check result content
    r_tokens = _re.findall(r"[a-z0-9']+", r_lower)
    r_words = set(r_tokens)

    # ---- Domain nouns shared? ----
    _DOMAIN_NOUNS = {"email", "address", "price", "cost", "total",
                     "user", "account", "profile", "data", "record",
                     "file", "page", "list", "value", "name"}
    shared_nouns = a_words & r_words & _DOMAIN_NOUNS

    # ---- Past-tense evidence: verb in result matches action ----
    # Base form of the key verb (strip trailing s/es/ed/d/ing):
    v = key_verb.rstrip("s").rstrip("e").rstrip("d")
    if v.endswith("ing"):
        v = v[:-3]
    # Common past/present forms of action verbs:
    _VERB_FORMS = {
        "return": {"returns", "returned", "returning"},
        "retrieve": {"retrieves", "retrieved", "retrieving"},
        "compute": {"computes", "computed", "computing"},
        "calculate": {"calculates", "calculated", "calculating"},
        "send": {"sends", "sent", "sending"},
        "update": {"updates", "updated", "updating"},
        "create": {"creates", "created", "creating"},
        "delete": {"deletes", "deleted", "deleting"},
        "fetch": {"fetches", "fetched", "fetching"},
        "generate": {"generates", "generated", "generating"},
        "build": {"builds", "built", "building"},
        "modify": {"modifies", "modified", "modifying"},
        "add": {"adds", "added", "adding"},
        "remove": {"removes", "removed", "removing"},
        "get": {"gets", "got", "getting"},
        "find": {"finds", "found", "finding"},
    }
    evidence_found = False
    for base, forms in _VERB_FORMS.items():
        if v == base or key_verb == base or key_verb in forms:
            if any(f in r_lower for f in forms):
                evidence_found = True
                break

    _DOMAIN_LINKS = {
        "return": {"retrieve", "fetch", "get", "obtain", "acquire"},
        "email": {"address", "inbox", "mailbox", "message"},
        "price": {"cost", "total", "amount", "fee", "charge"},
        "user": {"account", "profile", "member", "customer"},
        "compute": {"calculate", "determine", "evaluate", "measure"},
    }
    verb_link = False
    for a_word, linked in _DOMAIN_LINKS.items():
        if a_word in a_lower and any(link in r_lower for link in linked):
            verb_link = True
            break

    # Decision:
    if shared_nouns and evidence_found:
        # Concrete: same domain + past-tense action → paraphrase confirmed.
        return 0.90
    if evidence_found and verb_link:
        return 0.85
    if shared_nouns and verb_link:
        # Semantic match: shared domain nouns + linked verb concept.
        # The verb may differ in tense/lexeme but the same action is
        # clearly described (e.g. "returns" ↔ "retrieved").
        return 0.85
    if evidence_found:
        return 0.65
    if shared_nouns:
        return 0.55
    return 0.20


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------

def test_paraphrase_is_verified():
    """A DER step whose result is a genuine paraphrase of the expected
    output is recorded VERIFIED."""
    verifier = SemanticVerifier(encoder_fn=_paraphrase_accepting_encoder)

    with mock.patch.object(AgentKernel, "__init__", return_value=None):
        kernel = AgentKernel.__new__(AgentKernel)
        kernel._VERIFIER = verifier
        kernel._STUB_RE = re.compile(
            r"\[step\s+\d+\s+completed\]", re.IGNORECASE
        )

    label = kernel._verify_step_result(
        goal="retrieve the user's email address from the database",
        expected="returns the user's email address",
        result="the email address was retrieved from the database",
    )

    assert label == "VERIFIED", (
        f"paraphrase was {label!r}, expected VERIFIED — "
        "semantic scoring must accept paraphrases"
    )


def test_multi_assertion_paraphrase_partially_met():
    """With multiple assertions where only some are paraphrased, the
    result is UNVERIFIED (partial satisfaction)."""
    verifier = SemanticVerifier(encoder_fn=_paraphrase_accepting_encoder)

    with mock.patch.object(AgentKernel, "__init__", return_value=None):
        kernel = AgentKernel.__new__(AgentKernel)
        kernel._VERIFIER = verifier
        kernel._STUB_RE = re.compile(
            r"\[step\s+\d+\s+completed\]", re.IGNORECASE
        )

    label = kernel._verify_step_result(
        goal="retrieve email and compute total",
        expected="returns the user's email; computes the total price",
        result="the email address was retrieved",
    )

    # Only the first assertion is satisfied → frac ≈ 0.5 → UNVERIFIED.
    assert label == "UNVERIFIED", (
        f"partial paraphrase was {label!r}, expected UNVERIFIED"
    )
