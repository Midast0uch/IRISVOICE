"""CT-D1: DER band freeze.

Spec: specs/phase-6-der-integrity/design.md Testing Strategy > Contract table,
row CT-D1. "0.8/0.3 and the three label strings unchanged — this phase
consumes labels, never changes how they are produced."

Phase 6 is explicitly NOT allowed to touch the verify bands
(requirements.md Non-Requirements: "Changing DER band thresholds (0.8 /
0.3). Phase 4 froze them; this phase consumes the labels they produce.").
This pins the frozen thresholds directly against the real
`AgentKernel._verify_step_result`, so a future edit to Phase 6 code that
drifted the bands would break this file first.
"""

from __future__ import annotations

import re
from unittest import mock

from backend.agent.agent_kernel import AgentKernel


def _kernel(verified_fraction_return: float):
    with mock.patch.object(AgentKernel, "__init__", return_value=None):
        k = AgentKernel.__new__(AgentKernel)
        k._STUB_RE = re.compile(r"\[step\s+\d+\s+completed\]", re.IGNORECASE)
        k._verified_fraction = mock.Mock(return_value=verified_fraction_return)
        return k


class TestCTD1BandFreeze:
    def test_verified_band_is_still_0_8(self):
        assert _kernel(0.8)._verify_step_result("g", "e", "r") == "VERIFIED"
        assert _kernel(0.79)._verify_step_result("g", "e", "r") == "UNVERIFIED"

    def test_unverified_band_is_still_0_3(self):
        assert _kernel(0.3)._verify_step_result("g", "e", "r") == "UNVERIFIED"
        assert _kernel(0.29)._verify_step_result("g", "e", "r") == "FAILED"

    def test_label_strings_are_unchanged(self):
        for frac, expected in ((0.9, "VERIFIED"), (0.5, "UNVERIFIED"), (0.0, "FAILED")):
            assert _kernel(frac)._verify_step_result("g", "e", "r") == expected

    def test_stub_and_empty_result_always_failed_regardless_of_fraction(self):
        """Frozen pre-fraction guards: even a fraction that would otherwise
        pass VERIFIED cannot rescue a bare stub or empty output."""
        k = _kernel(0.99)
        assert k._verify_step_result("g", "e", "") == "FAILED"
        assert k._verify_step_result("g", "e", "[step 1 completed]") == "FAILED"
