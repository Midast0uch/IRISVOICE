"""The direct path's tool_choice shadow row is written again (2026-11-11).

`_respond_direct` read `_offered` (the menu the Brain was offered) but only
the DER node path defined it, so the shadow row raised NameError, the broad
except swallowed it at debug level, and every direct-path tool call since
tc-frame-v10 (2026-11-04) lost its row - a silent fallback on a path that
should never fall back (CLAUDE.md, hidden failures rule 4). Found live:
"[RespondDirect] shadow tool-choice row failed: NameError("name '_offered' is
not defined")".

Fails on the old kernel: `_offered` is read there before any assignment.
"""
from __future__ import annotations

import inspect

from backend.agent.agent_kernel import AgentKernel


def test_the_offered_menu_is_defined_before_the_row_reads_it():
    src = inspect.getsource(AgentKernel._respond_direct)
    read = src.index("for n in _offered")
    assigned = src.find("_offered = [")
    assert 0 <= assigned < read, "_offered is read before it is defined"
