"""Contract test CT-S2 (specs/phase-5-switcher/design.md).

"Settings selector filter: `ModelInferenceSection` still excludes non-chat
purposes (Phase 4 T2.2 not regressed)."

Phase 5 does NOT touch `components/ModelInferenceSection.tsx` (design.md
Ripple-Effect Map: CONTRACT LOCK — "Already filtered to purpose === 'chat' by
Phase 4 T2.2. Do not re-filter or duplicate the logic here."). This pins the
REAL shipped filter by reading the source file, the same technique
`test_context_pill_frozen.py` (CT-S1 / CT-I2) uses for a TS contract without
needing a Node/jsdom runtime — read-only, never modifies the component or its
own dedicated test file (`__tests__/components/ModelInferenceSection.test.tsx`,
owned elsewhere).
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent.parent
SETTINGS_PATH = ROOT / "components" / "ModelInferenceSection.tsx"


def _read_source() -> str:
    assert SETTINGS_PATH.exists(), f"expected {SETTINGS_PATH} to exist"
    return SETTINGS_PATH.read_text(encoding="utf-8")


class TestCTS2SettingsPurposeFilterNotRegressed:
    def test_chat_provider_options_filters_by_purpose(self):
        """The Brain/Tool selector source list excludes purpose != 'chat'."""
        src = _read_source()
        m = re.search(
            r"const chatProviderOptions = providers\.filter\(\s*"
            r"\(p\) => (.*?)\);",
            src,
            re.DOTALL,
        )
        assert m is not None, (
            "chatProviderOptions purpose filter not found — REQ-6 AC3 "
            "(Phase 4 T2.2) may have been regressed or renamed"
        )
        predicate = m.group(1)
        assert '!p.purpose' in predicate, "must treat undefined purpose as chat (backward-compat)"
        assert 'p.purpose === "chat"' in predicate, "must explicitly admit only purpose === 'chat'"

    def test_brain_and_tool_selectors_are_built_from_the_filtered_list(self):
        """`providerOptions` (what the selectors actually render) is derived
        FROM `chatProviderOptions`, not from the raw unfiltered `providers`
        array — otherwise the filter could exist but not actually reach the
        rendered dropdown."""
        src = _read_source()
        m = re.search(r"const providerOptions = (\w+)\.map", src)
        assert m is not None, "providerOptions derivation not found"
        assert m.group(1) == "chatProviderOptions", (
            f"providerOptions is built from {m.group(1)!r}, not the "
            "purpose-filtered chatProviderOptions — an embedding/rerank "
            "instance could reach the Brain/Tool selector"
        )
