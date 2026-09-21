import io
import os
import re

PATS = [
    re.compile(r"(?i)(api[_-]?key|secret|token|password|passwd|bearer)\s*[:=]\s*[\"'][A-Za-z0-9_\-]{16,}"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"eyJ[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{20,}"),
]

TARGETS = [
    "backend/agent/goal_contract.py",
    "scripts/validate_goal_coverage.py",
    "backend/tests/unit/test_goal_contract.py",
    "backend/tests/contract/test_goal_contract_coverage.py",
    "backend/tests/behavioral/test_goal_contract_coverage.py",
    "backend/tests/conftest.py",
    "backend/main.py",
    "backend/agent/permissions.py",
    "backend/agent/tool_bridge.py",
    "backend/agent/agent_kernel.py",
    "backend/agent/tool_errors.py",
    "backend/agent/nodes/runner.py",
    "backend/agent/nodes/outcome.py",
    "backend/agent/tool_envelope.py",
    "backend/agent/der_loop.py",
    "backend/agent/der_links.py",
    "backend/agent/der_constants.py",
    "components/chat/PermissionsSettingsCard.tsx",
    "__tests__/components/PermissionsSettingsCard.test.tsx",
    "backend/tests/contract/test_permission_system_contract.py",
    "backend/tests/contract/test_permission_gate_baseline.py",
    "backend/tests/contract/test_approval_classes.py",
    "backend/tests/contract/test_permission_enforcement.py",
    "backend/tests/contract/test_capability_escalation.py",
    "backend/tests/contract/test_standing_list.py",
    "specs/goal-contract-coverage/tasks.md",
]

hits = 0
for t in TARGETS:
    if not os.path.exists(t):
        print("MISSING", t)
        continue
    s = io.open(t, encoding="utf-8", errors="replace").read()
    for p in PATS:
        for m in p.finditer(s):
            hits += 1
            print("HIT", t, "->", m.group(0)[:70])
print("SCAN_DONE hits=", hits)
