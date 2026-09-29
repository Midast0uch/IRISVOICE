"""Regression (execution audit B4/B5, 2026-09-29): a command's exit code and
output must survive into DER step verification and later steps.

Before: run_command's dict fell to compact JSON (output escaped, exit code
buried), a step with a tool that reported success was VERIFIED even when the
command exited 1, and later steps saw 400 characters of it. Each test below
fails on that code.
"""

from backend.agent.agent_kernel import AgentKernel

FAILING_RUN = {
    "success": True,
    "stdout": "collected 7 items\n\ntest_calc.py ..F.FF.\n\nFAILED test_calc.py::test_sub - assert 8 == 2\n3 failed, 4 passed",
    "stderr": "",
    "returncode": 1,
}


def _kernel():
    return AgentKernel.__new__(AgentKernel)


def test_shell_result_is_readable_with_exit_code_first():
    text = AgentKernel._format_tool_result_for_step(FAILING_RUN, tool="run_command")
    assert text.startswith("[exit code 1]")
    assert "FAILED test_calc.py::test_sub - assert 8 == 2" in text  # real newlines, not escaped JSON


def test_non_zero_exit_is_not_verified():
    text = AgentKernel._format_tool_result_for_step(FAILING_RUN, tool="run_command")
    verdict = _kernel()._verify_step_result("run the tests", None, text, tool="run_command", success=True)
    assert verdict != "VERIFIED"


def test_zero_exit_still_verifies():
    ok = dict(FAILING_RUN, stdout="7 passed", returncode=0)
    text = AgentKernel._format_tool_result_for_step(ok, tool="run_command")
    verdict = _kernel()._verify_step_result("run the tests", None, text, tool="run_command", success=True)
    assert verdict == "VERIFIED"


def test_command_output_gets_a_real_evidence_window():
    assert AgentKernel._der_evidence_cap("run_command") >= 4000
    assert AgentKernel._der_evidence_cap("git_diff") >= 4000
