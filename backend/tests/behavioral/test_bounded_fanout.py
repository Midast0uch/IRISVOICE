"""
Behavioral + contract tests for bounded concurrent fan-out (REQ-6).

Drives ``_der_exec_steps_concurrent`` with more items than
``DER_MAX_CONCURRENT_STEPS`` and asserts that the in-flight count never exceeds
the bound. This is the seam bug the spec warns about: an unbounded
``asyncio.gather`` would open N parallel LLM calls for a wide split; the
semaphore must cap it.

Uses a fake executor that records concurrency via an async counter.
"""
import asyncio

import pytest

from backend.agent.der_constants import DER_MAX_CONCURRENT_STEPS


class _FakeItem:
    def __init__(self, step_id):
        self.step_id = step_id
        self.step_number = step_id


def _make_kernel():
    # Build an AgentKernel without its heavy __init__ (which needs many deps).
    # We only need _der_exec_steps_concurrent, which is self-contained.
    from backend.agent.agent_kernel import AgentKernel

    class _MinimalKernel(AgentKernel):
        def __init__(self):
            # Skip the real __init__ entirely.
            self._dummy = True

    return _MinimalKernel()


async def _run_fanout(item_count, kernel):
    _max_concurrent = {"n": 0}
    _current = {"n": 0}
    _lock = asyncio.Lock()

    async def _fake_exec(it, *a, **k):
        async with _lock:
            _current["n"] += 1
            _max_concurrent["n"] = max(_max_concurrent["n"], _current["n"])
        # Simulate an in-flight LLM call.
        await asyncio.sleep(0.01)
        async with _lock:
            _current["n"] -= 1
        return it.step_id, f"result-{it.step_id}", True

    # Patch the async executor used inside _der_exec_steps_concurrent.
    _orig = kernel._der_run_step_execution_async
    kernel._der_run_step_execution_async = _fake_exec
    try:
        _items = [_FakeItem(i) for i in range(item_count)]
        _result = await kernel._der_exec_steps_concurrent(
            _items, None, "sess", None, None
        )
    finally:
        kernel._der_run_step_execution_async = _orig
    return _result, _max_concurrent["n"]


@pytest.mark.asyncio
async def test_fanout_bounded_to_max_concurrent():
    _kernel = _make_kernel()
    # 10 items, bound is 3 → max in-flight must never exceed 3.
    _result, _max = await _run_fanout(10, _kernel)
    assert len(_result) == 10
    assert _max <= DER_MAX_CONCURRENT_STEPS
    assert _max == DER_MAX_CONCURRENT_STEPS  # actually exercised the bound


@pytest.mark.asyncio
async def test_fanout_respects_bound_exactly():
    _kernel = _make_kernel()
    _result, _max = await _run_fanout(5, _kernel)
    assert len(_result) == 5
    # With 5 items and bound 3, max in-flight should be exactly 3.
    assert _max == DER_MAX_CONCURRENT_STEPS
