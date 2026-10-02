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
    "them), or `STATUS: failed: <reason>` when it is not.\n"
    "When a tool call will finish the step, set its `step_done` argument to true "
    "and put a one-line summary of the step in `step_summary`: if every tool call "
    "in that answer succeeds, the step ends there and you are not asked again."
)

# Every node tool takes these two optional arguments (owner 2026-10-01). A
# model that sends tool calls leaves the text part empty (gemma via Ollama:
# 0 of 15 steps closed through a STATUS line in the tool answer), but it fills
# arguments, so the closing signal rides on the call. Removed before dispatch.
_CLOSE_ARGS = {
    "step_done": {"type": "boolean",
                  "description": "true when this call finishes the step"},
    "step_summary": {"type": "string",
                     "description": "with step_done: one line on what the step did"},
}


def _with_close_args(tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for t in tools:
        fn = dict(t.get("function") or {})
        params = dict(fn.get("parameters") or {"type": "object"})
        params["properties"] = {**(params.get("properties") or {}), **_CLOSE_ARGS}
        fn["parameters"] = params
        out.append({**t, "function": fn})
    return out


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


_ID_KEYS = ("path", "file_path", "command", "pattern", "query", "url")


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
    tools = _with_close_args(ctx.tools)
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
                "reasoning", messages, tools=tools, max_tokens=ctx.max_tokens,
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
            batch_failed = False
            batch_results: List[str] = []
            batch_done = False
            batch_summaries: List[str] = []
            for tc in tool_calls:
                fn = tc.get("function") or {}
                name = fn.get("name", "")
                raw_args = fn.get("arguments") or "{}"
                try:
                    params = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
                except (ValueError, TypeError):
                    params = None
                if isinstance(params, dict):
                    if params.pop("step_done", False) is True:
                        batch_done = True
                    _sum = params.pop("step_summary", None)
                    if isinstance(_sum, str) and _sum.strip():
                        batch_summaries.append(_sum.strip())
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
                batch_failed = batch_failed or failed
                if name == "run_command":
                    last_command_failed = failed
                # args: the identifying keys only (never a file body) - what
                # memory events and footprints read as "what this step touched".
                calls.append({"tool": name, "target": _target(params or {}), "ok": not failed,
                              "args": {k: params[k] for k in _ID_KEYS
                                       if isinstance(params, dict) and params.get(k)}})
                logger.info("[run_node] conv=%s %s %s -> %s", ctx.conv_id, name,
                            _target(params or {}), "FAILED" if failed else "ok")
                content = _clip(ctx.format_result(name, raw) or "", ctx.result_chars)
                batch_results.append(f"[{name} {_target(params or {})}]\n{content}")
                messages.append({
                    "role": "tool", "tool_call_id": tc.get("id") or name, "name": name,
                    "content": content,
                })
            # Closed in the same answer (owner 2026-10-01): the step's last
            # call used to cost one more model call only to hear "done". The
            # summary was written before the results, so the results go with it
            # (later steps read them instead of reading the files again). Any
            # failed tool still gets the follow-up call.
            if not batch_failed and (batch_done or _STATUS.search(text or "")):
                ok, _reason, summary = _status(text or "")
                if batch_done:
                    ok = True
                    summary = "\n".join(batch_summaries) or summary
                if ok:
                    logger.info("[run_node] conv=%s done in the tool answer: %d call(s), "
                                "last_cmd_failed=%s", ctx.conv_id, len(calls),
                                bool(last_command_failed))
                    return NodeResult(True, (summary + "\n\nTool results:\n"
                                             + "\n\n".join(batch_results)).strip(),
                                      calls, last_command_failed=bool(last_command_failed))
        # Budget spent with work still requested: ask for an honest status.
        messages.append({"role": "user", "content": (
            "The time budget for this step is used up. Say what you did and what is unfinished.")})
        text, _think, _ = ctx.generate("reasoning", messages, tools=None, max_tokens=1024,
                                       temperature=0.2, timeout_s=120.0)
        return NodeResult(False, text or "", calls, "node time budget used up")
    except Exception as exc:  # noqa: BLE001 — a broken node is a failed step, not a crashed turn
        logger.warning("[run_node] conv=%s failed: %s", ctx.conv_id, exc)
        return NodeResult(False, text or "", calls, f"{type(exc).__name__}: {exc}")
