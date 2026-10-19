"""
LiveContextPackage — C.1 Continuous Context Engineering.

Wraps a ContextPackage and refreshes its coordinate signals at each DER
cycle boundary.  This is the runtime implementation of Option C from
docs/CONTEXT_ENGINEERING.md.

Design contract:
  - refresh() must complete in < 50ms (uses cached Mycelium paths)
  - refresh() must never raise (falls back gracefully on any error)
  - The ContextPackage field is always valid even if refresh fails

Usage in _execute_plan_der():
    live = LiveContextPackage(context_package, memory_interface, session_id)
    while not queue.is_complete():
        live.refresh(item, completed_items)
        context = live.package           # use this instead of raw context_package
        ...
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any, List, Optional

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from backend.agent.der_loop import QueueItem


class LiveContextPackage:
    """
    Mutable ContextPackage wrapper that refreshes coordinate signals each
    DER cycle.

    Attributes:
        package:     The current ContextPackage (updated in-place by refresh)
        refresh_ms:  Wall-clock time of the last refresh call in milliseconds
        refresh_count: How many times refresh() has been called this loop
    """

    # Minimum interval between refreshes — avoids hammering Mycelium on
    # very fast loops (token budget exhausted in < 200ms).
    MIN_REFRESH_INTERVAL_MS: float = 200.0

    def __init__(
        self,
        initial_package: Any,
        memory_interface: Any,
        session_id: str,
    ) -> None:
        self.package = initial_package
        self._memory = memory_interface
        self._session = session_id
        self.refresh_ms: float = 0.0
        self.refresh_count: int = 0
        self._last_refresh_at: float = 0.0

    def refresh(
        self,
        current_item: "QueueItem",
        completed_items: List["QueueItem"],
    ) -> None:
        """
        Re-query Mycelium for the current coordinate position given the
        steps completed so far.  Updates gradient_warnings and
        tier2_predictions on self.package.

        Called by Director at the start of each DER cycle.
        Silently no-ops if Mycelium is unavailable or too slow.
        """
        now = time.monotonic() * 1000.0
        if now - self._last_refresh_at < self.MIN_REFRESH_INTERVAL_MS:
            return  # rate-limited — skip this cycle

        t0 = time.monotonic()
        try:
            self._do_refresh(current_item, completed_items)
        except Exception as exc:
            logger.debug("[LiveContext] refresh() suppressed error: %s", exc)
        finally:
            elapsed = (time.monotonic() - t0) * 1000.0
            self.refresh_ms = elapsed
            self.refresh_count += 1
            self._last_refresh_at = now
            if elapsed > 50.0:
                logger.warning(
                    "[LiveContext] refresh() took %.1f ms (> 50 ms SLA)", elapsed
                )

    def _do_refresh(
        self,
        current_item: "QueueItem",
        completed_items: List["QueueItem"],
    ) -> None:
        """Inner refresh — may raise; always wrapped by refresh()."""
        if self._memory is None or self.package is None:
            return

        # ── 1. Gradient warnings ──────────────────────────────────────────
        # Re-read from Mycelium based on completed tool names so far.
        # This catches cases where a completed step moved into a danger zone.
        try:
            completed_tools = [
                ci.tool for ci in completed_items if ci.tool
            ]
            if completed_tools and hasattr(self._memory, "mycelium_get_warnings"):
                new_warnings = self._memory.mycelium_get_warnings(
                    session_id=self._session,
                    tool_names=completed_tools,
                )
                if new_warnings and hasattr(self.package, "gradient_warnings"):
                    # the field is a str: one warning per line, no repeats
                    lines = [ln for ln in (self.package.gradient_warnings or "").split("\n") if ln]
                    for w in ([new_warnings] if isinstance(new_warnings, str) else new_warnings):
                        if w and str(w) not in lines:
                            lines.append(str(w))
                    self.package.gradient_warnings = "\n".join(lines)
        except Exception:
            pass

        # ── 2. BehavioralPredictor: refresh tier2_predictions ────────────
        # Ask the predictor what the next tool is likely to be.
        try:
            if hasattr(self._memory, "_mycelium") and self._memory._mycelium:
                from backend.memory.mycelium.interpreter import BehavioralPredictor
                predictor = BehavioralPredictor(self._memory._mycelium)
                completed_tool_names = [
                    ci.tool for ci in completed_items if ci.tool
                ]
                # The predictor ranks edges leaving the session's region; an
                # empty list always answers [] (it has no session history of
                # its own). settle=False: a steering read of the last settled
                # edges - a cycle boundary must not wait on the writer queue.
                predictions = predictor.predict(
                    session_id=self._session,
                    current_node_ids=sorted(
                        self._memory._mycelium._registry.get_region(self._session)
                    ),
                    task_class=getattr(self.package, "task_class", "full"),
                    completed_tools=completed_tool_names,
                    settle=False,
                )
                if predictions and hasattr(self.package, "tier2_predictions"):
                    self.package.tier2_predictions = ", ".join(predictions)
        except Exception:
            pass

        # ── 3. Active contracts: refresh from Mycelium profile ───────────
        try:
            if hasattr(self._memory, "mycelium_get_active_contracts"):
                contracts = self._memory.mycelium_get_active_contracts(self._session)
                if contracts and hasattr(self.package, "active_contracts"):
                    self.package.active_contracts = (
                        contracts if isinstance(contracts, str)
                        else "\n".join(str(c) for c in contracts)
                    )
        except Exception:
            pass
