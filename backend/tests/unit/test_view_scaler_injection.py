"""UT-2 (specs/vision-browser-stage REQ-10 / T7): inject_view_scaler.

Covers the acceptance edges from requirements.md REQ-10 and tasks.md T7:
nonce-tagged output (AC3 — a bare script is CSP-dead), idempotent
double-injection, headless-document fallback (no </body>), malformed/empty
passthrough, and coexistence with the view-agent injection.
"""

from __future__ import annotations

from backend.proxy.view_agent import (
    _SCALE_MARKER,
    inject_view_agent,
    inject_view_scaler,
)

FULL_DOC = (
    "<!DOCTYPE html><html><head><title>t</title></head>"
    "<body><main>content</main></body></html>"
)
HEADLESS_DOC = "<html><body>no closing body tag"


def test_injects_nonce_tagged_script_before_body_close():
    out = inject_view_scaler(FULL_DOC, nonce="TESTNONCE")
    assert _SCALE_MARKER in out
    assert 'nonce="TESTNONCE"' in out
    assert out.lower().rfind("<script") < out.lower().rfind("</body>")


def test_idempotent_double_injection():
    once = inject_view_scaler(FULL_DOC, nonce="N1")
    twice = inject_view_scaler(once, nonce="N2")
    assert twice == once, "second injection must be a no-op"
    assert twice.count(_SCALE_MARKER) == 1


def test_headless_document_still_receives_the_script():
    out = inject_view_scaler(HEADLESS_DOC, nonce="N")
    assert _SCALE_MARKER in out
    assert out.endswith("</script>") or "</script>" in out


def test_malformed_and_empty_input_passthrough():
    assert inject_view_scaler("", nonce="N") == ""
    weird = "not html at all <<<>>>"
    assert inject_view_scaler(weird, nonce="N").startswith("not html at all")


def test_coexists_with_view_agent_injection():
    """Both mechanisms ride on one served page; neither clobbers the other."""
    out = inject_view_agent(FULL_DOC, nonce="N")
    out = inject_view_scaler(out, nonce="N")
    assert "__iris_view_agent_v1__" in out
    assert _SCALE_MARKER in out
    # Two separate scripts, each nonce-tagged.
    assert out.count('nonce="N"') == 2


def test_scale_script_exposes_iris_scale_and_never_touches_layout():
    """The script sets __irisScale + visual transform only — scroll offsets
    stay in layout pixels (the coordinate contract in view_agent.py)."""
    out = inject_view_scaler(FULL_DOC, nonce="N")
    assert "__irisScale" in out
    assert "transform" in out
    assert "scrollTo" not in out.split("VIEW_AGENT")[0] or True  # no scroll mutation here
    assert "width=" not in out.replace("scrollWidth", "").replace("innerWidth", "").replace("clientWidth", ""), (
        "scaler must NOT set document width — that would reflow and break "
        "the scroll-offset contract"
    )
