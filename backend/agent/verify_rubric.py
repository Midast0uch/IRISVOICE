"""DER Phase 3 (D3.1): LLM rubric verification for mid-band (|u|) steps.

This is the TIER-3 (empowered) verification leg. It is invoked ONLY for steps in
the mid-|u| band (see agent_kernel._der_verify_strictness -> "rubric"), where a
purely deterministic check is insufficient and an empowered verdict is required.
Low-|u| (wide/split) and high-|u| (converged/atomic) bands do NOT call this — they
use deterministic verification only (cheap, no LLM). This keeps the rubric call
rate bounded and makes it a genuine *empowered* check, not a default.

The function returns one of: "VERIFIED", "UNVERIFIED", "FAILED".
  VERIFIED   : the step's actual result satisfies its expected_output.
  UNVERIFIED  : ambiguous / cannot confirm — caller treats as not-yet-verified
                (does NOT auto-pass; does NOT auto-fail unless policy says so).
  FAILED      : the result clearly does NOT satisfy the expected_output.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

logger = logging.getLogger(__name__)

RUBRIC_PROMPT = """You are a strict verification rubric for one agent step.
Decide whether the ACTUAL RESULT satisfies the EXPECTED OUTPUT.

EXPECTED OUTPUT:
{expected_output}

ACTUAL RESULT:
{actual_result}

TOOL USED: {tool}

Respond with STRICT JSON only:
{{"verdict": "VERIFIED"|"UNVERIFIED"|"FAILED", "reason": "<one line>"}}

Rules:
- VERIFIED only if the actual result clearly and fully satisfies the expected output.
- FAILED if the result is missing, is a stub/placeholder, or clearly does not satisfy it.
- UNVERIFIED only if genuinely ambiguous (e.g. partial, needs human judgment).
- A stub, placeholder, "[step done]", or empty result is NEVER VERIFIED.
"""


def _extract_json(text: str) -> Optional[dict]:
    try:
        m = re.search(r"\{[\s\S]+\}", text)
        if not m:
            return None
        return json.loads(m.group())
    except Exception:
        return None


def call(
    expected_output: str,
    actual_result: str,
    tool: str,
    infer,
) -> str:
    """Run the rubric. Returns "VERIFIED" | "UNVERIFIED" | "FAILED".

    On any inference/parse failure returns "UNVERIFIED" (fail-soft: never silently
    VERIFIED, never silently FAILED — the caller's policy decides the consequence).
    """
    try:
        prompt = RUBRIC_PROMPT.format(
            expected_output=expected_output or "(none specified)",
            actual_result=actual_result or "(empty)",
            tool=tool or "unknown",
        )
        resp = infer(prompt, role="VERIFICATION", max_tokens=200, temperature=0.0)
        raw = getattr(resp, "raw_text", resp) if resp is not None else ""
        data = _extract_json(raw) if isinstance(raw, str) else None
        if isinstance(data, dict):
            verdict = str(data.get("verdict", "")).upper()
            if verdict in ("VERIFIED", "UNVERIFIED", "FAILED"):
                return verdict
        return "UNVERIFIED"
    except Exception as _e:
        logger.warning("[verify_rubric] rubric call failed: %s", _e)
        return "UNVERIFIED"
