"""
MCMOrchestrator — JSON-driven context lifecycle manager.

Loads all protocol JSON files via Pydantic v2, runs workflows,
dispatches to action modules.

Per JsonManagement.md:
  - JSON is the rules/protocol layer; Python is the safe execution layer.
  - Batch-load all configs at init into one MCMProtocol model.
  - Hot-reload when any JSON mtime changes.
  - Action modules are imported lazily and cached.
  - Behaviors are injected as context (MCM_MITO), not registered as tools.
"""

from __future__ import annotations

import importlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Optional

from .schemas import MCMCore, MCMProtocol, NBLSchema, RecallRules, Workflow, WorkflowStep

logger = logging.getLogger(__name__)

# Directory containing this file
_PROTOCOL_DIR = Path(__file__).parent


class MCMOrchestrator:
    """
    Single entry point for all context lifecycle management.

    Usage:
        orch = MCMOrchestrator(memory_interface, session_id, thread_id)
        messages = orch.pre_call(messages, task)
        compressed = orch.post_turn(messages, response_text, tool_name)
    """

    def __init__(
        self,
        memory_interface,
        session_id: str,
        thread_id: Optional[str] = None,
    ) -> None:
        self._mi        = memory_interface
        self.session_id = session_id
        self.thread_id  = thread_id

        self._protocol: MCMProtocol = self._load_protocol()
        self._mtime_snapshot: dict[str, float] = self._snapshot_mtimes()
        self._action_cache: dict[str, Any] = {}

    # ── Public API ────────────────────────────────────────────────────────

    def pre_call(self, messages: list[dict], task: str) -> list[dict]:
        """Run pre_call_flow workflow. Returns enriched messages."""
        ctx = self._make_ctx(messages=messages, task=task)
        result = self.run_workflow("pre_call_flow", ctx)
        return result.get("messages", messages)

    def post_turn(
        self,
        messages: list[dict],
        response_text: str = "",
        tool_name: str = "",
    ) -> bool:
        """
        Run post_turn_flow workflow.
        Returns True if MCM compression fired.
        """
        ctx = self._make_ctx(
            messages=messages,
            response_text=response_text,
            tool_name=tool_name,
        )
        result = self.run_workflow("post_turn_flow", ctx)
        # Propagate compressed messages back to caller's list
        if result.get("compressed"):
            messages[:] = result.get("messages", messages)
        return bool(result.get("compressed", False))

    def recall(self, query: str) -> list[dict]:
        """Run recall_flow. Returns list of recall result dicts."""
        ctx = self._make_ctx(task=query)
        result = self.run_workflow("recall_flow", ctx)
        return result.get("recall_results", [])

    def run_workflow(self, workflow_name: str, ctx: dict) -> dict:
        """
        Generic runner.
          1. Hot-reload protocol if any JSON mtime changed.
          2. Look up workflow by name.
          3. Execute steps in order; honour on_error: continue | abort.
        """
        self._maybe_reload()

        workflow = self._protocol.workflows.get(workflow_name)
        if workflow is None:
            logger.debug("[MCMOrchestrator] workflow '%s' not found", workflow_name)
            return ctx

        if workflow.dry_run:
            logger.info("[MCMOrchestrator] dry_run: %s — skipping", workflow_name)
            return ctx

        for step in workflow.steps:
            try:
                action_mod = self._load_action(step.action)
                ctx = action_mod.execute(ctx, step.params)
            except Exception as exc:
                logger.warning(
                    "[MCMOrchestrator] step '%s' failed: %s", step.action, exc
                )
                if step.on_error == "abort":
                    break

        return ctx

    # ── Protocol loading ──────────────────────────────────────────────────

    def _load_protocol(self) -> MCMProtocol:
        """Batch-load all JSON files and merge into MCMProtocol."""
        core_dir      = _PROTOCOL_DIR / "core"
        workflow_dir  = _PROTOCOL_DIR / "workflows"

        # Load core configs
        core_data     = self._read_json(core_dir / "mcm_core.json")
        nbl_data      = self._read_json(core_dir / "nbl_schema.json")
        recall_data   = self._read_json(core_dir / "recall_rules.json")
        collab_data   = self._read_json(core_dir / "collaboration_rules.json")

        # Load workflows
        workflows: dict[str, Workflow] = {}
        if workflow_dir.exists():
            for wf_file in workflow_dir.glob("*.json"):
                try:
                    wf_data = self._read_json(wf_file)
                    wf      = Workflow.model_validate(wf_data)
                    workflows[wf.name] = wf
                except Exception as exc:
                    logger.warning("[MCMOrchestrator] failed to load %s: %s", wf_file.name, exc)

        try:
            from .schemas import CollaborationRules
            protocol = MCMProtocol(
                core          = MCMCore.model_validate(core_data)                  if core_data   else MCMCore(),
                nbl_schema    = NBLSchema.model_validate(nbl_data)                 if nbl_data    else NBLSchema(),
                recall_rules  = RecallRules.model_validate(recall_data)            if recall_data else RecallRules(),
                collaboration = CollaborationRules.model_validate(collab_data)     if collab_data else CollaborationRules(),
                workflows     = workflows,
            )
        except Exception as exc:
            logger.warning("[MCMOrchestrator] protocol validation failed, using defaults: %s", exc)
            protocol = MCMProtocol(workflows=workflows)

        logger.debug(
            "[MCMOrchestrator] protocol loaded v%s — %d workflows",
            protocol.core.protocol_version, len(workflows),
        )
        return protocol

    def _snapshot_mtimes(self) -> dict[str, float]:
        snapshot: dict[str, float] = {}
        for json_file in _PROTOCOL_DIR.rglob("*.json"):
            try:
                snapshot[str(json_file)] = json_file.stat().st_mtime
            except OSError:
                pass
        return snapshot

    def _maybe_reload(self) -> None:
        """Hot-reload protocol if any JSON file has changed since last load."""
        try:
            current = self._snapshot_mtimes()
            if current != self._mtime_snapshot:
                logger.info("[MCMOrchestrator] JSON change detected — reloading protocol")
                self._protocol        = self._load_protocol()
                self._mtime_snapshot  = current
        except Exception:
            pass

    @staticmethod
    def _read_json(path: Path) -> dict:
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as exc:
            logger.warning("[MCMOrchestrator] could not read %s: %s", path, exc)
            return {}

    # ── Action module loading ─────────────────────────────────────────────

    def _load_action(self, name: str):
        """Import action module lazily and cache. Raises on missing module."""
        if name in self._action_cache:
            return self._action_cache[name]
        module = importlib.import_module(
            f"backend.agent.mcm_protocol.actions.{name}"
        )
        self._action_cache[name] = module
        return module

    # ── Context builder ───────────────────────────────────────────────────

    def _make_ctx(self, **kwargs) -> dict:
        """Build a fresh context dict with orchestrator-scoped defaults."""
        ctx = {
            "mi":         self._mi,
            "session_id": self.session_id,
            "thread_id":  self.thread_id,
            "protocol":   self._protocol,
            "messages":   [],
            "task":       "",
            "response_text": "",
            "tool_name":  "",
            "compressed": False,
        }
        ctx.update(kwargs)
        return ctx
