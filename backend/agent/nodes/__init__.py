"""DAG Node Execution Model — composable, routable node actions.

Spec: specs/dag-node-execution-model/
  - outcome.py  — NodeStatus / Reason / NodeOutcome / Artifact (REQ-1)
  - spec.py     — NodeSpec wrapping the existing ToolSpec (REQ-2)
  - runner.py   — node invocation + legacy adapter + raise conversion (REQ-1 AC2, REQ-7)
  - router.py   — reason->recovery matching, guards, bounds (REQ-4, REQ-8)

DER remains the execution loop; this package gives it the seams it lacked:
actions return routable outcomes instead of free-form results, composites
decompose into visible sub-graphs, and failure reasons route to nodes that
advertise recovery — with no branch written in the failing node's module.
"""

from .outcome import (
    Artifact,
    NodeOutcome,
    NodeStatus,
    Reason,
)
from .spec import NodeSpec
from .runner import run_node, adapt_legacy_outcome

__all__ = [
    "Artifact",
    "NodeOutcome",
    "NodeStatus",
    "Reason",
    "NodeSpec",
    "run_node",
    "adapt_legacy_outcome",
]
