"""What a DER step DID decides its Caducean action and balance (REQ-8, redo 2026-10-01).

Shared by the kernel's physics lane (``AgentKernel._der_physics_step``) and the
offline replay (``scripts/replay_sigma.py``), so the rule that goes live is the rule
that was replayed.

History. The live rule fed a constant: 0 for every step except run_command/git, and
the SQL EML sat at 12.51, so the balance sat at its 3.0 clamp and xi advanced by the
same amount every step - Sigma was a step counter. K4 (adbf69f8) classified steps by
their single tool and was reverted: a coding step is a NODE with no single tool, so
every step read COMPRESS (98/98 rows), rec never reached 1 and the continuation brake
never fired. Replay over 45 recorded eval sessions (native engine):

  rule        action mix        distinct xi steps   brake (final rec=1)
  current     0 x193            1                   25/45
  k4          1 x193            1                    0/45
  node calls  1 x142, 0 x51     43                  16/45

Pure logic, no imports from the kernel.
"""
from __future__ import annotations

from typing import Iterable, Optional, Tuple

EXPAND = 0
COMPRESS = 1

# A call that changed the world consolidates the work.
CONSOLIDATING = frozenset({
    "write_file", "edit_file", "create_directory", "run_command", "git_commit",
    "git_push", "create_artifact", "save_memory",
})
# A call that only looked gathers.
GATHER = frozenset({
    "crawler_query", "search", "web_search", "read_file", "list_directory",
    "get_rendered_documents", "get_system_info", "glob_files", "grep_files",
    "recall_memory", "recall_research", "vision_analyze_screen", "take_screenshot",
    "read_shell_output", "open_url", "list_conversations", "git_log", "git_status",
    "git_diff", "browser_open", "browser_observe", "browser_explore",
})

# docs/cad_v2_architecture.md S2.2: balance = clamp(EML / 2.3418, 0.1, 3.0).
EML_BALANCE_DIVISOR = 2.3418


def step_action(tool: Optional[str], success: bool,
                calls: Optional[Iterable[Tuple[str, bool]]] = None) -> int:
    """EXPAND (0) or COMPRESS (1) for one finished step.

    A failed step consolidated nothing: EXPAND. A node step (``calls`` = the
    (tool, ok) pairs it made) COMPRESSES when one successful call consolidated,
    else EXPANDS. A step with no calls: a gather tool EXPANDS; no tool
    (synthesis) or any other tool COMPRESSES.
    """
    if not success:
        return EXPAND
    calls = list(calls or [])
    if calls:
        return COMPRESS if any(t in CONSOLIDATING and ok for t, ok in calls) else EXPAND
    return EXPAND if (tool or "none") in GATHER else COMPRESS


def balance_from_eml(eml_score: float) -> float:
    """The v2 state EML scaled by the design divisor, clamped to [0.1, 3.0]."""
    return max(0.1, min(3.0, float(eml_score) / EML_BALANCE_DIVISOR))
