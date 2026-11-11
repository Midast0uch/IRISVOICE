"""The input identity shared by every Oracle shadow row.

This module held the surface consumers (`needs_action`, `depth_met`, and
before them `has_gaps` and `escalate_incomplete`) and the shadow/sampled
scoring helpers they used. All of them are RETIRED (the last two on
2026-11-10, owner: "remove the technical debt"; see
decision_engine.CONSUMERS). Their incumbents decide alone. What remains is
the one hash every other consumer's rows use to dedupe on what was ASKED.
"""

from __future__ import annotations

import hashlib
import json
from typing import Optional


def input_key(consumer_id: str, statement: str,
              frame: Optional[dict] = None) -> str:
    """A stable identity for the INPUT a row was scored on (2026-10-20).

    The ledger's dedupe key is (consumer, engine, confidence, chosen,
    reference, correct) and confidence jitters on every rescore, so the same
    goal rescored counted as NEW evidence (measured: needs_action 226
    "distinct" rows, 17 collapsed, after two passes over one 101-task set).
    This key pins the row to what was ASKED, not to how confidently it was
    answered. The report prefers it when present; rows without it keep the
    legacy key.
    """
    payload = json.dumps(
        {"c": consumer_id, "s": statement, "f": frame or None},
        sort_keys=True, ensure_ascii=False, default=str,
    )
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]
