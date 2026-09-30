"""Node executor — one DER node runs as a bounded work loop (execution audit, Phase 2).

Owner decision (2026-09-29): ONE engine. The DER-DAG stays the planner and
brancher; each node runs a bounded loop through ``run_node(goal, ctx)``, in
this module and not in agent_kernel.py. The old seam — "one node = one tool
call picked by the small tool model from a goal string" — is replaced here.

Why: eval re-runs on 2026-09-29 showed the 2.6B tool model resolving
"Fix the off-by-one error in mathutils.py" to read_file six times in a row;
the same task passed only in the run where it happened to pick edit_file.

Inside a node the Brain sees the goal, the earlier node results, and its own
tool calls with their results word for word. It calls tools natively (the
Brain is the pen: it writes file bodies itself). The node ends when the Brain
answers without a tool call, or when the node's time budget runs out — a round
count never ends it. A tool exception becomes a typed tool result the Brain can
react to. The Brain closes each node with `STATUS: done` or `STATUS: failed:
<reason>`; a failing last command is always stated in the step result, so the
verifier and the final answer see it. (An earlier rule failed every node whose
last command exited non-zero; that failed "run the tests to see the errors"
steps and DER retried them four times - coding eval c11/c14, 2026-09-29.)
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# The developer tool family offered inside a node (developer mode first).
DEV_NODE_TOOLS = (
    "read_file", "edit_file", "write_file", "grep_files", "glob_files",
    "list_directory", "create_directory", "run_command", "git_status", "git_diff",
)

_SYSTEM = (
    "You are doing ONE step of a larger coding task, in the project folder "
    "{workdir}. Use the tools to do the step, then answer with a short plain "
    "summary of what you did and what the result was — with no tool call.\n"
    "Rules:\n"
    "- Paths are relative to the project folder.\n"
    "- Read a file before you change it.\n"
    "- Change an existing file with edit_file: `old` must be copied exactly from "
    "the file and match once. Use write_file only for a new file or a full rewrite.\n"
    "- When the step is about behaviour, run the tests with run_command and read "
    "the result. A non-zero exit code means it failed.\n"
    "- Do only this step. Do not ask the user questions.\n"
    "End your final answer with one line: `STATUS: done` when the step's goal is "
    "met (a step that only has to OBSERVE failing tests is met once you saw "
    "them), or `STATUS: failed: <reason>` when it is not."
)


@dataclass
class NodeContext:
    generate: Callable[..., tuple]            # router.generate(role, messages, tools=..., ...)
    execute: Callable[[str, dict], Any]       # dispatch one tool -> raw result
    format_result: Callable[[str, Any], str]  # (tool, raw) -> text for the model
    tools: List[Dict[str, Any]]               # OpenAI function schemas
    prior_results: List[Dict[str, Any]] = field(default_factory=list)
    # The user's request word for word. The step goal is the planner's
    # paraphrase and drops details (coding eval c10, 2026-09-29: the goal kept
    # "add, remove and count" but lost "qty <= 0 raises ValueError").
    task: str = ""
    workdir: str = ""
    budget_s: float = 300.0
    max_tokens: int = 8192
    result_chars: int = 8000
    conv_id: str = ""
    # Owner decision: the Oracle advises and records shadow rows in node
    # loops. Called with (tool, params) for every Brain call; must not block.
    on_call: Optional[Callable[[str, dict], None]] = None


@dataclass
class NodeResult:
    success: bool
    summary: str
    calls: List[Dict[str, Any]] = field(default_factory=list)
    error: str = ""
    last_command_failed: bool = False

    def as_step_result(self) -> str:
        lines = [self.summary.strip() or "(no summary)"]
        if self.calls:
            lines.append("\nActions:")
            lines += [f"- {c['tool']} {c['target']} -> {'ok' if c['ok'] else 'FAILED'}" for c in self.calls]
        if self.last_command_failed:
            lines.append("\nThe last command in this step exited non-zero.")
        if self.error:
            lines.append(f"\n[node error: {self.error}]")
        return "\n".join(lines)


_STATUS = re.compile(r"^\s*STATUS:\s*(done|failed)\b:?\s*(.*)$", re.I | re.M)


def _status(text: str) -> tuple:
    """(ok, reason, text without the STATUS line). No line = done."""
    matches = list(_STATUS.finditer(text or ""))
    if not matches:
        return True, "", text or ""
    m = matches[-1]
    clean = (text[:m.start()] + text[m.end():]).strip()
    return m.group(1).lower() == "done", m.group(2).strip(), clean


def _clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    head = limit * 2 // 3
    return text[:head] + f"\n... [{len(text) - limit} chars cut] ...\n" + text[-(limit - head):]


def _target(params: dict) -> str:
    for key in ("path", "file_path", "command", "pattern", "query"):
        if params.get(key):
            return str(params[key])[:80]
    return ""


def _failed(raw: Any) -> bool:
    if isinstance(raw, dict):
        if raw.get("success") is False:
            return True
        rc = raw.get("returncode")
        return rc not in (None, 0)
    return False


def _user_message(goal: str, task: str, prior: List[Dict[str, Any]], limit: int) -> str:
    parts = []
    if task.strip() and task.strip() != goal.strip():
        parts.append("THE WHOLE TASK (the user's request, word for word — every rule in it "
                     "applies to this step's work):\n" + _clip(task.strip(), limit))
    parts.append(f"STEP: {goal}")
    if prior:
        done = "\n\n".join(
            f"[step {r.get('step')}] {r.get('description', '')}\n{r.get('result', '')}" for r in prior
        )
        parts.append("RESULTS OF EARLIER STEPS:\n" + _clip(done, limit * 3))
    return "\n\n".join(parts)


def run_node(goal: str, ctx: NodeContext) -> NodeResult:
    """Run one node to completion. Never raises."""
    allowed = {t.get("function", {}).get("name") for t in ctx.tools}
    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": _SYSTEM.format(workdir=ctx.workdir or "(current folder)")},
        {"role": "user", "content": _user_message(goal, ctx.task, ctx.prior_results, ctx.result_chars)},
    ]
    calls: List[Dict[str, Any]] = []
    last_command_failed: Optional[bool] = None
    deadline = time.monotonic() + ctx.budget_s
    text = ""
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 5:
                break
            text, _think, tool_calls = ctx.generate(
                "reasoning", messages, tools=ctx.tools, max_tokens=ctx.max_tokens,
                temperature=0.2, timeout_s=min(remaining, 300.0),
            )
            if not tool_calls:
                # The Brain judges its own step (it knows whether failing tests
                # were the goal or the problem); the failing last command is
                # still stated in the step result for the verifier and the turn.
                ok, reason, summary = _status(text or "")
                logger.info("[run_node] conv=%s done: %d call(s), success=%s, last_cmd_failed=%s",
                            ctx.conv_id, len(calls), ok, bool(last_command_failed))
                return NodeResult(ok, summary, calls, reason if not ok else "",
                                  last_command_failed=bool(last_command_failed))
            messages.append({"role": "assistant", "content": text or None, "tool_calls": tool_calls})
            for tc in tool_calls:
                fn = tc.get("function") or {}
                name = fn.get("name", "")
                raw_args = fn.get("arguments") or "{}"
                try:
                    params = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
                except ValueError:
                    params = None
                if params is None:
                    raw: Any = {"success": False, "error": "arguments were not valid JSON; send a JSON object"}
                elif name not in allowed:
                    raw = {"success": False, "error": f"unknown tool {name!r}; use one of {sorted(allowed)}"}
                else:
                    if ctx.on_call is not None:
                        try:
                            ctx.on_call(name, params)
                        except Exception as exc:  # noqa: BLE001 — advisory only
                            logger.debug("[run_node] shadow hook failed: %r", exc)
                    try:
                        raw = ctx.execute(name, params)
                    except Exception as exc:  # noqa: BLE001 — typed result, the model reacts
                        raw = {"success": False, "error": f"{type(exc).__name__}: {exc}", "error_type": "exception"}
                failed = _failed(raw)
                if name == "run_command":
                    last_command_failed = failed
                calls.append({"tool": name, "target": _target(params or {}), "ok": not failed})
                logger.info("[run_node] conv=%s %s %s -> %s", ctx.conv_id, name,
                            _target(params or {}), "FAILED" if failed else "ok")
                messages.append({
                    "role": "tool", "tool_call_id": tc.get("id") or name, "name": name,
                    "content": _clip(ctx.format_result(name, raw) or "", ctx.result_chars),
                })
        # Budget spent with work still requested: ask for an honest status.
        messages.append({"role": "user", "content": (
            "The time budget for this step is used up. Say what you did and what is unfinished.")})
        text, _think, _ = ctx.generate("reasoning", messages, tools=None, max_tokens=1024,
                                       temperature=0.2, timeout_s=120.0)
        return NodeResult(False, text or "", calls, "node time budget used up")
    except Exception as exc:  # noqa: BLE001 — a broken node is a failed step, not a crashed turn
        logger.warning("[run_node] conv=%s failed: %s", ctx.conv_id, exc)
        return NodeResult(False, text or "", calls, f"{type(exc).__name__}: {exc}")
