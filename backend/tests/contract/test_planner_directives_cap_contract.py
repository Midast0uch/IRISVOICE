"""Contract: the planner prompt's DIRECTIVES never carry the raw mycelium path.

x01/x02 planner prompts measured 24-28k tokens: PathEncoder wrote ~55 chars per
entry node (967 nodes), ContextPackage.mycelium_path held all of it, and the
1,600-char cap sat only in get_system_zone_content(). The planning prompt read
the raw field. A prompt consumer reads get_path_text() (same cap, same code).
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _kernel_source import kernel_source  # noqa: E402

from backend.agent.agent_kernel import AgentKernel  # noqa: E402
from backend.memory.mycelium.interface import (  # noqa: E402
    CONTEXT_PACKAGE_MAX_CHARS,
    ContextPackage,
)


def _package(path: str) -> ContextPackage:
    return ContextPackage(
        mycelium_path=path, topology_path="", manifest={}, tier1_directives="",
        tier2_predictions="", tier3_failures="", active_contracts="",
        gradient_warnings="", causal_context="", ambient_signals="",
        topology_position="", task_class="full",
    )


_HUGE = "[ZONE header]\nMYCELIUM: " + ",".join("0.123456789" for _ in range(4500))


def _kernel():
    return AgentKernel.__new__(AgentKernel)


def test_huge_path_is_capped_in_package_fields():
    assert len(_HUGE) > 40_000
    tier1 = _kernel()._context_package_fields(_package(_HUGE))["tier1"]
    assert len(tier1) <= CONTEXT_PACKAGE_MAX_CHARS
    assert tier1.startswith("[ZONE header]")


def test_planning_prompt_directives_stay_small():
    k = _kernel()
    tier1 = k._context_package_fields(_package(_HUGE))["tier1"]
    prompt = k._build_planning_prompt("do the task", tier1_directives=tier1)
    m = re.search(r"DIRECTIVES:\n(.*?)(?:\n\n[A-Z ]+:\n|\Z)", prompt, re.S)
    assert m and len(m.group(1)) < 3000
    assert len(prompt) < 6000


def test_standin_package_without_get_path_text_is_capped():
    class _Stand:
        mycelium_path = _HUGE

    tier1 = _kernel()._context_package_fields(_Stand())["tier1"]
    assert len(tier1) <= CONTEXT_PACKAGE_MAX_CHARS


def test_no_kernel_code_reads_mycelium_path_directly():
    # A read is `.mycelium_path` or getattr(x, "mycelium_path"); prose in a
    # docstring (``mycelium_path``) is not.
    read = re.compile(r"""(?<!`)\.mycelium_path|["']mycelium_path["']""")
    hits = [ln for ln in kernel_source("utf-8", "replace").splitlines()
            if read.search(ln)]
    assert not hits, hits
