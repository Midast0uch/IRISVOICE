"""Phase 2 — Memory-as-Execution-Substrate (A1 + A2 + A3).

A1: per-step execution injects PAST FAILURE WARNING from Mycelium.
A2: per-step hint includes the PROVEN APPROACH tool_sequence, not just summary.
A3: failed step outputs are fragmented into episodic memory for later recall.

The A1/A2 test drives the real _execute_plan_der loop (one successful step) with
a mocked kernel so the C.4 mid-loop retrieval block runs against controlled
episodic data, then asserts the item's coordinate_signal. The A3 test calls
_der_finalize_step directly with a failed step.
"""
from unittest.mock import MagicMock, patch


class _Step:
    step_id = "s1"
    step_number = 1
    description = "process a config file"
    tool = "read_file"
    params = {"path": "/x"}
    critical = True
    depends_on = []


class _Plan:
    original_task = "test task"
    plan_title = "test plan"
    strategy = "standard"
    steps = [_Step()]


def test_mid_loop_injects_failure_warning_and_proven_approach():
    """A1 + A2: coordinate_signal MUST carry failure warning + proven approach."""
    from backend.agent import agent_kernel

    with patch("backend.agent.event_bus.get_event_bus", return_value=MagicMock()), \
         patch("backend.ws_manager.get_websocket_manager", return_value=None):
        kernel = MagicMock()
        kernel.session_id = "sess"
        kernel.conversation_id = "conv"
        kernel._tool_bridge = MagicMock()
        kernel._reviewer = MagicMock()
        kernel._reviewer.review.return_value = (MagicMock(), None)
        mem = MagicMock()
        mem.episodic.retrieve_similar.return_value = [
            {
                "task_summary": "processed a config file",
                "tool_sequence": [
                    {"tool": "read_file"},
                    {"tool": "run_command"},
                    {"tool": "write_file"},
                ],
            }
        ]
        mem.episodic.retrieve_failures.return_value = []
        kernel._memory_interface = mem
        kernel.clear_turn_trust_flag = MagicMock()
        # A1: a known-bad approach for this sub-task
        kernel._get_failure_warnings.return_value = (
            "Avoid editing binary configs in-place: previous attempt "
            "corrupted the file (seen 3x)"
        )

        captured = {}

        def _fake_run(item, *a, **k):
            # C.4 has already run by the time the Explorer executes the step,
            # so coordinate_signal is fully populated here.
            captured["item"] = item
            return ("ok", True)

        kernel._der_run_step_execution = _fake_run
        kernel._der_handle_step_failure = MagicMock()
        # Step succeeds -> _der_finalize_step runs; return an int so the loop's
        # _tokens_used accounting stays numeric (unmocked MagicMock would break
        # the next while-condition comparison).
        kernel._der_finalize_step.return_value = 200

        agent_kernel.AgentKernel._execute_plan_der.__get__(
            kernel, agent_kernel.AgentKernel
        )(plan=_Plan(), context_package=None, session_id="sess", turn_id="t1")

    sig = captured["item"].coordinate_signal
    assert "PAST FAILURE WARNING:" in sig, sig
    assert "PROVEN APPROACH: read_file → run_command → write_file" in sig, sig
    assert "SUB-TASK HINT:" in sig, sig


def test_fragment_failed_output_stored():
    """A3: a failed step's output MUST be fragmented for later recall."""
    from backend.agent import agent_kernel

    kernel = MagicMock()
    kernel.conversation_id = "conv"
    kernel.resolve_context_window.return_value = 8000
    mem = MagicMock()
    kernel._memory_interface = mem

    class _Item:
        step_id = "s1"
        step_number = 1
        description = "read binary file"
        tool = "read_file"
        expected_output = None
        is_subloop = False

    agent_kernel.AgentKernel._der_finalize_step.__get__(
        kernel, agent_kernel.AgentKernel
    )(
        item=_Item(),
        step_result="[STEP ERROR: UnicodeDecodeError: 'utf-8' codec can't decode]",
        step_success=False,
        step_outputs=[],
        completed_items=[],
        _tokens_used=0,
        _token_budget=50000,
        _session="sess",
        _turn_id="t1",
        _phase=0,
        is_mature=False,
        _live_ctx=None,
        plan=None,
        context_package=None,
        queue=MagicMock(),
        verdict=MagicMock(),
    )

    frag = mem.episodic.fragment_and_store
    assert frag.called, "failed output should be fragmented"
    _call = frag.call_args
    assert _call.kwargs.get("chunk_type") == "der_failure", _call.kwargs
    assert "FAILED Step 1" in _call.args[0], _call.args[0]
