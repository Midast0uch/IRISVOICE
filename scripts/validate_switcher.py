#!/usr/bin/env python3
"""
Standing CDD harness for Phase 5 — Model Switcher + ContextPill.

Run on every build:  python scripts/validate_switcher.py
Exits non-zero if any assertion fails.

Asserts (from specs/phase-5-switcher/design.md "Standing CDD harness"):
  1. CT-S1..CT-S5 hold.
  2. No `/api/inference/state` response contains a credential or fragment.
  3. The switcher's candidate list contains no provider with `purpose != "chat"`.
  4. The switcher's candidate list contains no API provider without `has_key`
     and no local provider without `loaded`.
  5. `context:usage` from the DER path and the direct path have identical
     shape and denominator.
  6. `ContextPillProps` is unchanged.
  7. Every send-blocking condition the removed Send button carried still
     blocks a send.

Assertion 7 is the one worth running on every commit: it is the only guard
against a silent UX regression that produces no error and no user report
(design.md). Phases 1 and 2 skipped their harnesses and claimed completion
they had not earned — building them found real production bugs on first run.
This harness exists so Phase 5 does not repeat that.
"""

from __future__ import annotations

import re
import subprocess
import sys
import traceback
from pathlib import Path

# Make the backend importable when run as a standalone script.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FAILURES = []


def check(name, cond, detail=""):
    if cond:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name}  {detail}")
        FAILURES.append(name)


def main() -> int:
    from backend.agent.event_bus import get_event_bus, IRISStreamEvent
    from backend.agent.agent_kernel import AgentKernel
    from backend.agent.inference.provider import ProviderInstance, ProviderKind

    CONTEXT_PILL_PATH = ROOT / "components" / "chat" / "ContextPill.tsx"
    MODEL_SWITCHER_PATH = ROOT / "components" / "ModelSwitcher.tsx"
    AGENT_KERNEL_PATH = ROOT / "backend" / "agent" / "agent_kernel.py"

    # =====================================================================
    # Assertion 1: CT-S1..CT-S5 hold.
    # =====================================================================
    print("== Assertion 1: CT-S1..CT-S5 hold ==")
    ct_s_files = [
        "backend/tests/contract/test_ct_s1_context_pill_props_frozen.py",
        "backend/tests/contract/test_ct_s2_settings_purpose_filter.py",
        "backend/tests/contract/test_context_usage_parity.py",
        "backend/tests/contract/test_ct_s4_no_credential_in_state.py",
        "backend/tests/contract/test_ct_s5_role_binding_payload_shape.py",
    ]
    for f in ct_s_files:
        if not (ROOT / f).exists():
            check(f"{f} exists", False, "CT-S contract test file is missing")
            continue
        result = subprocess.run(
            [sys.executable, "-m", "pytest", f, "-q"],
            cwd=str(ROOT), capture_output=True, text=True,
        )
        check(f"{f} passes", result.returncode == 0,
              result.stdout[-800:] + result.stderr[-400:] if result.returncode != 0 else "")

    # =====================================================================
    # Assertion 2: no /api/inference/state response contains a credential
    # or fragment.
    # =====================================================================
    print("== Assertion 2: no credential or fragment in the provider payload ==")
    _real_key = "FAKETESTCRED-live-9f8e7d6c5b4a3210abcdef0123"
    _inst = ProviderInstance(
        id="probe-provider", label="Probe", kind=ProviderKind.API,
        model="probe-model", api_key=_real_key,
    )
    _payload = _inst.to_dict()
    _serialized = str(_payload)
    check("raw key absent from payload", _real_key not in _serialized)
    check("api_key field absent from payload", "api_key" not in _payload)
    _fragment_leaked = any(
        _real_key[i : i + 8] in _serialized for i in range(0, len(_real_key) - 8, 8)
    )
    check("no 8-char fragment of the key leaked", not _fragment_leaked)
    check("has_key crosses the boundary as a bool", isinstance(_payload.get("has_key"), bool))

    # =====================================================================
    # Assertion 3: switcher candidate list excludes purpose != "chat".
    # =====================================================================
    print("== Assertion 3: ModelSwitcher excludes purpose != 'chat' ==")
    _switcher_src = MODEL_SWITCHER_PATH.read_text(encoding="utf-8") if MODEL_SWITCHER_PATH.exists() else ""
    check("ModelSwitcher.tsx exists", bool(_switcher_src))
    _entries_match = re.search(
        r"const entries: SwitcherEntry\[\] = useMemo\(\(\) => \{\s*return providers\s*(.*?)\}, \[providers\]\)",
        _switcher_src, re.DOTALL,
    )
    check("ModelSwitcher entries filter found", _entries_match is not None)
    if _entries_match:
        _filter_body = _entries_match.group(1)
        check('entries filters purpose === "chat" (or undefined)',
              "purpose" in _filter_body and '"chat"' in _filter_body,
              _filter_body)

    # =====================================================================
    # Assertion 4: no API provider without has_key, no local provider
    # without loaded, reaches the switcher's candidate list.
    # =====================================================================
    print("== Assertion 4: ModelSwitcher requires has_key (API) / loaded (local) ==")
    if _entries_match:
        _filter_body = _entries_match.group(1)
        check("entries filter checks has_key for API providers",
              "has_key" in _filter_body, _filter_body)
        check("entries filter checks loaded for non-API providers",
              "loaded" in _filter_body, _filter_body)

    # =====================================================================
    # Assertion 5: context:usage DER vs direct-path parity.
    # =====================================================================
    print("== Assertion 5: context:usage shape+denominator parity (DER vs direct) ==")

    def _make_kernel(tokens_used: int, max_tokens: int) -> AgentKernel:
        k = AgentKernel.__new__(AgentKernel)
        k._tokens_used = tokens_used
        k.conversation_id = "conv_harness"
        k.session_id = "sess_harness"
        k._current_turn_id = "turn_harness"
        k.resolve_context_window = lambda: max_tokens
        return k

    bus = get_event_bus()
    _captured = []

    def _capture(payload):
        if payload.event == IRISStreamEvent.CONTEXT_USAGE:
            _captured.append(dict(payload.data or {}))

    bus.subscribe(IRISStreamEvent.CONTEXT_USAGE, _capture)
    try:
        _k = _make_kernel(tokens_used=7_000, max_tokens=48_000)
        _captured.clear()
        _k._emit_context_usage()  # direct-path style
        _direct = _captured[0] if _captured else {}
        _captured.clear()
        _k._emit_context_usage(step_number=1, total_steps=3)  # DER-path style
        _der = _captured[0] if _captured else {}
    finally:
        bus.unsubscribe(IRISStreamEvent.CONTEXT_USAGE, _capture)

    check("direct path emits", bool(_direct))
    check("DER path emits", bool(_der))
    check("same denominator both paths",
          _direct.get("max_tokens") == _der.get("max_tokens") == 48_000,
          f"direct={_direct.get('max_tokens')} der={_der.get('max_tokens')}")
    check("same numerator both paths",
          _direct.get("used_tokens") == _der.get("used_tokens") == 7_000,
          f"direct={_direct.get('used_tokens')} der={_der.get('used_tokens')}")

    _kernel_src = AGENT_KERNEL_PATH.read_text(encoding="utf-8")
    check("direct (non-DER) reply path calls the shared emitter",
          "self._emit_context_usage()" in _kernel_src)
    check("DER path calls the shared emitter with step metadata",
          "self._emit_context_usage(\n            step_number=len(completed_items),\n            total_steps=len(queue.items),\n        )"
          in _kernel_src)

    # =====================================================================
    # Assertion 6: ContextPillProps unchanged.
    # =====================================================================
    print("== Assertion 6: ContextPillProps unchanged ==")
    _pill_src = CONTEXT_PILL_PATH.read_text(encoding="utf-8") if CONTEXT_PILL_PATH.exists() else ""
    _props_match = re.search(r"export interface ContextPillProps \{(.*?)\}", _pill_src, re.DOTALL)
    check("ContextPillProps interface found", _props_match is not None)
    if _props_match:
        _found_props = set(re.findall(r"^\s*(\w+)\??:\s*\w", _props_match.group(1), re.MULTILINE))
        _expected_props = {"usedTokens", "maxTokens", "phase", "currentAction"}
        check("ContextPillProps is exactly the frozen 4 props",
              _found_props == _expected_props, f"found={_found_props}")

    # =====================================================================
    # Assertion 7: every send-blocking condition the removed Send button
    # carried still blocks a send from Enter.
    # =====================================================================
    print("== Assertion 7: every removed guard still blocks a send (Enter) ==")
    _input_row_test = ROOT / "__tests__" / "InputRow.test.tsx"
    if not _input_row_test.exists():
        check("__tests__/InputRow.test.tsx exists", False)
    else:
        _jest_result = subprocess.run(
            ["npx", "jest", "__tests__/InputRow.test.tsx", "--silent"],
            cwd=str(ROOT), capture_output=True, text=True, shell=True,
        )
        check("__tests__/InputRow.test.tsx passes (Send absent, Enter guarded)",
              _jest_result.returncode == 0,
              (_jest_result.stdout[-1200:] + _jest_result.stderr[-800:]))

    print()
    if FAILURES:
        print(f"HARNESS FAILED: {len(FAILURES)} assertion(s) failed:")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("HARNESS PASSED: all assertions green.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(2)
