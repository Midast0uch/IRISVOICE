"""Probe: _gc_result_is_error classifies error envelopes vs real output."""
import sys
sys.path.insert(0, r"C:\dev\IRISVOICE")
from backend.agent.agent_kernel import AgentKernel as K


class Dummy:
    pass


f = K._gc_result_is_error
d = Dummy()

cases = [
    ("json error str (wc not recognized)",
     '{"success": true, "stdout": "wc : The term \'wc\' is not recognized"}', True),
    ("plain real output", "The answer is 51.", False),
    ("success dict with output", {"success": True, "stdout": "found 42 files"}, False),
    ("failed dict", {"success": False, "error": "boom"}, True),
    ("nonzero returncode", {"success": True, "returncode": 1, "stdout": "x"}, True),
    ("error key present", {"error": "permission denied"}, True),
    ("command not found", {"success": True, "stdout": "zsh: command not found: foo"}, True),
    ("empty", "", False),
    ("none", None, False),
]
ok = True
for name, val, want in cases:
    got = f(d, val)
    flag = "OK " if got == want else "BAD"
    if got != want:
        ok = False
    print(f"  [{flag}] {name:38} -> {got} (want {want})")
print("ALL_OK" if ok else "FAILURES")
