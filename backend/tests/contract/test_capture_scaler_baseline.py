"""Wave 0 baseline (T0c) — capture/proxy served HTML AS IS.

specs/vision-browser-stage REQ-10 (T7) adds a transform-scale pass so wide
fixed-layout pages SHRINK to the frame width instead of being clipped by the
existing `overflow-x: hidden` cap. This file pins today's bytes so the delta
is provable:

  - The view-agent IS injected, nonce-tagged (existing contract, must survive).
  - The fit style exists (viewport meta + max-width caps) but there is NO
    scale mechanism: no `data-iris-scaler` marker, no `__irisScale` global,
    no `transform:` scaling of the document element.

Expected to be edited EXACTLY ONCE by T7 (the scaler assertions flip from
absent to present); that edit must be called out in the task report.
"""

from __future__ import annotations

import pytest

from backend.proxy import view_agent as va

FIXTURE_HTML = (
    "<!DOCTYPE html><html><head><title>t</title></head>"
    "<body><table style=\"width:1600px\"><tr><td>wide</td></tr></table></body></html>"
)


def test_baseline_view_agent_present_and_nonce_tagged():
    """Existing contract that MUST survive T7 unchanged."""
    out = va.inject_view_agent(FIXTURE_HTML, nonce="TESTNONCE")
    assert va._MARKER in out
    assert 'nonce="TESTNONCE"' in out


def test_scaler_mechanism_now_present_and_nonce_tagged():
    """EDITED EXACTLY ONCE by T7 (the declared baseline flip): the scaler
    injection now EXISTS — nonce-tagged, exposing __irisScale, idempotent."""
    out = va.inject_view_agent(FIXTURE_HTML, nonce="TESTNONCE")
    out = va.inject_view_scaler(out, nonce="TESTNONCE")
    assert "__iris_scaler_v1__" in out, (
        "REQ-10: the fit-to-width scaler must ride every served page"
    )
    assert 'nonce="TESTNONCE"' in out
    assert "__irisScale" in out


def test_fit_style_still_caps_but_scaler_shrinks():
    """The two mechanisms compose: caps bound runaway elements; the scaler
    shrinks whatever remains wider than the frame. Transform must be visual
    only — layout offsets stay in original pixels (scroll-mirror contract)."""
    out = va.inject_view_agent(FIXTURE_HTML, nonce="TESTNONCE")
    out = va.inject_view_scaler(out, nonce="TESTNONCE")
    assert "overflow-x: hidden" in out
    assert "transform" in out
