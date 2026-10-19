"""Calibrated decision engine — ORACLE (Jev/RLCD pattern reproduction).

Spec: specs/tool-decision-engine-improvements (REQ-21, REQ-22, REQ-25, REQ-26);
specs/phonon2-d1-model-swap (Wave 3/5 — the d1 backend).

NAME vs KEY (read this before renaming anything). ``Oracle`` is the engine's
DISPLAY name — what a human reads in logs, telemetry and the UI. The technical
keys stay exactly as they are, because they carry meaning that a rename would
destroy:
  * the config block id ``oracle`` (agent_config.yaml) is what
    ``load_engine_config`` looks up; and
  * the ACTIVE backend identity ``d1-3b-ad-q4_k_m`` KEYS THE CALIBRATED
    THRESHOLD (``backend_thresholds``, REQ-22 AC22.1 / REQ-25 AC25.8). Renaming
    that key marks every measured curve unaddressable and enforcement
    fail-closes — a rename there is a configuration migration, not a label
    change. (The retired ``gliner25-decide-onnx-int8`` entry stays as history:
    its rows are other_backend evidence, oracle.md §16.)

One resident decision backend, BORROW-ONLY: d1-3B (a JEV-style System One
decision model) served by the shared llama-server :8082 — the same server
vision uses (backend/agent/decision_backend_d1.py; the GLiNER ONNX backend it
replaced is deleted, Wave 5). It never writes to memory, never emits events,
never spawns a process. Its only job: score a caller-provided option set
against a caller-provided feature frame and return a probability distribution,
one question per run, read from the logits at the single answer slot.
Consumers: `tool_choice` (Wave 2), `presentation` and `narration` (Wave 4).

Two primitives, both return DecisionScore/ArgsResult or None (None = degrade
to legacy path):
  - decide(consumer_id, options, frame)      — Jev "Choice" (schema scoring)
  - generate_args(consumer_id, option, schema, frame) — constrained args JSON

The d1 backend scores options; it does not generate arguments (D12 stands), so
``generate_args`` has no generative backend in production and degrades to
``ArgsResult(args=None)`` — the box then escalates to the legacy ladder, where
the Brain does schema-constrained generation via function-calling (AC2.4).
The generative path stays behind the ``llama_factory`` test seam so the args
stage stays testable.

Everything here is single-writer-of-nothing: read set is the args passed in;
write set is the return value, counters, and log lines. CT-DE-5 enforces it.
"""

from __future__ import annotations

import contextvars
import json
import logging
import os
import re
import sys
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Sequence, Tuple

logger = logging.getLogger("decision_engine")

# The engine's DISPLAY name. Logs, telemetry and the UI read THIS; the config
# block id and the backend identity stay untouched (see the module docstring:
# the backend identity keys the calibrated threshold).
ENGINE_NAME = "Oracle"

# ---------------------------------------------------------------------------
# Data model (CT-DE-1 pins this shape)
# ---------------------------------------------------------------------------

CONSUMERS: Tuple[str, ...] = (
    "tool_choice",
    "presentation",
    "narration",
    # REQ-11 AC11.3 (T15): the graft-recovery triage consumer. Consulted BEFORE
    # Brain planning spend — the Brain plans only on DELEGATE / below threshold.
    # REQ-13 AC13.1 (T17): the per-step Reviewer verdict consumer, SHADOW only
    # (the Brain verdict still decides until AC13.3's measured bar is met).
    # NOTE: this grows the pinned consumer set; the two CT-DE-7 enumerations
    # were updated as a STALE-BY-SPEC change (the spec mandates the consumers).
    "recovery_strategy",
    "review_verdict",
    # REQ-14 AC14.1 (T18): the three loop-monitor bool consumers, answered with
    # a `Noul` (P(statement true)) rather than a two-option Choice (AC14.6).
    "sufficient",
    "done",
    # `on_track` REMOVED 2026-10-05 (owner, Oracle Stage B): no production caller
    # since 2026-10-02 - a consumer nothing consults is a calibration line that
    # can never move. `has_gaps` removed with it (below).
    # REQ-15 AC15.1 (T19): web_intent shadows the duplicated web-trigger lists.
    # `mode` REMOVED 2026-10-10 (owner): its incumbent is a FREE deterministic
    # keyword rule, so enforcing it could never pay (a 0 ms rule swapped for a
    # ~100-300 ms model call), and its reference IS the keyword list - the bar
    # could only ever prove agreement with a list the system already trusts
    # more than the model. Its AUROC also fell below the bar at volume (0.591
    # at 77 rows; the 0.677 that once justified keeping it was small-n). The
    # keyword classifier itself is UNTOUCHED (mode_detector._infer_mode); only
    # the Oracle shadow measurement is gone. The pinned enumerations are
    # updated in the SAME change, so the declared set is never left
    # half-changed. The ledger's historical mode rows stay (retired, never
    # blended back).
    "web_intent",
    # `retry_same` REMOVED as a declared consumer (Wave 4 T4.5,
    # specs/phonon2-d1-model-swap REQ-12 AC12.2 / oracle.md §11.5): it never
    # had a row of its own — its data rides `recovery_strategy` as the
    # `retry_same_offered` field, so the declaration was a consumer that
    # could never move. The MENU option and the field stay (AC12.3); only
    # the consumer entry is gone. The pinned enumerations are updated in
    # the SAME change, so the declared set is never left half-changed.
    # REQ-29 (T46–T49): the remaining decision surface — choice-shaped Brain
    # decisions scored in shadow. `has_gaps` REMOVED 2026-10-05 (owner): its only
    # producer (trailing_director.py) was deleted 2026-08-06, so it had no live
    # site. `tier0_classify` is a recorded NON-FIT and is deliberately absent
    # (AC29.5).
    "escalate_incomplete",
    "needs_action",
    # Session 364 (owner request): the DEPTH question, asked against the task's
    # SUCCESS CRITERIA rather than against coverage alone. The complaint it
    # exists to measure and then fix: the Brain "settles for half work" - the
    # loop declares a task complete while required facts are still open, or the
    # result is only superficially complete. `sufficient` and `done` ask whether
    # the objective is COVERED; this asks whether it is done to the DEPTH the
    # criteria demand. Shape: a Noul (a calibrated probability), like the other
    # monitors (AC14.6). Reference: the loop's OWN run grade, so the parity row
    # measures exactly how often a "complete" verdict failed the depth bar.
    # NOTE: this grows the pinned consumer set; the CT-DE-7 enumerations and the
    # surface-observer tests are updated in the SAME change.
    "depth_met",
    # REQ-4/T1.9 (specs/oracle-native-decision-surface): `depth_route` HAS live
    # call sites (`_der_note_depth_route` at five kernel sites plus the writer in
    # tool_decision.depth_route) but was NOT in CONSUMERS, so its rows were never
    # reported and it could never be calibrated. It is producing data nobody
    # counts. Registered here as a declared consumer (AC9.1 sanctioned exception
    # 2); the CT-DE-7 enumerations are updated in the same change.
    "depth_route",
    # REQ-10/T1.10: `call_closing` - "is this the closing call of this step?".
    # It does NOT reuse `done` (which asks whether the TASK is finished at the
    # turn layer). The name is a SAFETY REQUIREMENT: never a loop-control verb,
    # never `step_satisfied`, never `done_at_call`. It is MEASUREMENT-ONLY
    # permanently (AC10.0) - see REFUSED_CONSUMERS below.
    "call_closing",
    # tool_approval (2026-10-18, owner: "address tool_approval pre-call guard
    # so it can be flipped"): earned the hardened bar on the v6 cohort (433
    # distinct rows, oof AUROC 0.7313, ECE 0.0398, precision@t 0.9034) and
    # given its live decision - the PRE-CALL GUARD in node_executor (a
    # confident "it will fail" asks the model to correct the call before it
    # runs). Membership lets the owner switch it on with IRIS_DECISION_ENFORCE.
    "tool_approval",
)


# ---------------------------------------------------------------------------
# Oracle JOBS (2026-10-01, owner). A job is the KIND of question: it fixes what
# the model reads (which frame fields, in which order) and how much of it (a
# text budget in token ids). Every consumer belongs to one job; the engine - not
# the call site - builds the input, so a new consumer cannot be slow or blind by
# accident. Measured why (coding eval 2026-10-01): inputs ranged 30-400 words
# because each site built its own, latency follows length (30 words 150 ms,
# 400 words 2.3 s), and only frame["goal"] ever reached the model - depth_route's
# coverage/open facts and depth_met's evidence were built and never read.
# Reference fields (incumbent_route, brain_*) are NEVER listed: a row whose
# input carries the answer measures nothing. docs/architecture/oracle.md S19.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OracleJob:
    name: str
    question: str                 # the kind of question (documentation)
    fields: Tuple[str, ...]       # frame fields read, in order ("goal" = the text)
    budget_ids: int               # text token budget (label structure is extra)
    # REQ-5 AC5.1: the frame keys holding IMAGE BYTES this job's consumers may
    # read. Empty = a text-only job; a frame can carry an image for another
    # reason and a text consumer still never receives one.
    image_fields: Tuple[str, ...] = ()


@dataclass(frozen=True)
class OracleState:
    """The ONE structured input a job builds and the backend reads whole
    (REQ-3: `job_input()` returns this; the backend stops reading a goal
    string out of a raw frame - AC3.1/AC3.2).

    It is structured rather than a string because the field-presence contract
    (AC3.5) must assert which DECLARED fields the state carries, a row needs
    to know which fields were present, and an image must reach only the jobs
    that declare it (AC5.1). The budget still travels with the text and is
    applied by the BACKEND, logged when it trims (AC3.4).
    """

    job: str                     # the job that built it
    fields: Tuple[str, ...]      # the job's DECLARED fields, in order
    text: str                    # the rendered field text
    budget_ids: int              # the job's text budget
    images: Tuple[bytes, ...] = ()  # declared images only (REQ-5 AC5.1)
    # DYNAMIC-MENU CRITERIA (2026-10-10): a choice consumer whose option set
    # varies per turn (tool_choice) cannot declare its option descriptions in
    # the static declaration table, so the call site supplies them per
    # consult via the frame key `option_criteria` and they travel here —
    # rendered into the OPTION LINES by the backend, never into the state
    # text (the reference puts the description beside the code: "A Read a
    # file's contents"). Measured live: descriptions in the option lines
    # answer 5/5 varied tool questions where bare names answer 5/6.
    option_criteria: Tuple[Tuple[str, str], ...] = ()


ORACLE_JOBS: Dict[str, OracleJob] = {j.name: j for j in (
    OracleJob("interpret", "what does the user's message mean?",
              ("goal",), 64),
    # web_intent gets its OWN job (2026-10-18): the interpret job's 64-id
    # budget (256 chars) cut 6 of 14 live goals - and the goals START with an
    # ~80-char Windows path ("The project is in C:\...\<task>. <instruction>"),
    # so the cap left d1 reading a path instead of the request. 128 ids
    # (512 chars) covers the longest measured goal (347). user_feedback keeps
    # `interpret` (isolation, the judge_review precedent). Replay on real
    # pairs: capped 0.8864 vs uncapped 0.9318.
    OracleJob("interpret_web", "what does the user's message mean?",
              ("goal",), 128),
    OracleJob("route", "which of these next actions? (the menu carries the content)",
              # `last_result` (2026-10-10): the previous step's result snippet.
              # MEASURED ROOT CAUSE of tool_choice's 45% parity accuracy: the
              # shadow frame carried ONLY a 200-char goal, while the Brain picks
              # with the full conversation, the tool schemas and - most
              # predictive of all - what the last call returned. A ReAct loop's
              # next tool is largely a function of the last result (just read a
              # file -> edit it; tests failed -> fix the file). Without it d1
              # answers a strictly harder question blind, and the disagreement
              # measured the INFORMATION GAP, not the engine's judgment.
              # Budget 64 -> 256 (1024 chars rendered): goal[:200] plus a
              # ~600-char result snippet must both fit; at 64 the goal alone
              # nearly filled the cap. The budget is a CAP, not a floor, so the
              # other route consumers (depth_route, recovery_strategy) are
              # unaffected beyond headroom.
              # FRAME/JOB MISMATCH FIX (2026-10-10): the route consumers'
              # frames carry evidence the job never declared, so the renderer
              # dropped it: tool_choice's resolve frame carries task_class,
              # previous_chosen/outcome, step_index and the vision fields;
              # recovery_strategy's carries ruled_out and error_snippet (the
              # single most predictive signal for a recovery choice);
              # depth_route's carries pushes_used. The fields are now the
              # UNION; absent keys render as nothing, so each consumer renders
              # what its frame carries. Budget 256 still caps the render
              # (goal 200 + last_result 600 chars fit).
              # `incumbent_route` is deliberately NOT declared: it is
              # depth_route's REFERENCE, and a row whose input carries its
              # own answer measures nothing (test_reference_fields_never_
              # reach_the_model, oracle.md S19).
              # tc-frame-v5 (2026-10-11): `done_when` (the step's own criterion)
              # and `calls_this_step` (the calls the step already made, ok or
              # FAILED). MEASURED CAUSE: every call of a step gave d1 the SAME
              # frame (the previous STEP's result, computed once per node) while
              # the model's answer moved read -> edit -> run: 50.9% parity on
              # 395 rows, top-4 coverage 85%. Placed BEFORE last_result so the
              # cap trims the long result snippet, never the history.
              # Budget 256 -> 384: goal 200 + done_when 200 + calls_this_step
              # 400 + last_result 600 chars do not fit 1024; 384 ids (1536
              # chars) does, the same width `approve` measured. 512 stays the
              # ceiling (S19.3).
              # tc-frame-v7 (2026-10-11): `step_facts` - for each file the
              # step names, whether it exists and whether this step already
              # read/changed it, plus the last command's result: the facts
              # that decide read vs edit vs write vs run (node_executor.
              # step_facts). Before last_result, so the cap never cuts them.
              ("coverage", "open_facts", "depth_met", "grade", "goal",
               "done_when", "calls_this_step", "step_facts",
               "last_result", "task_class", "previous_chosen",
               "previous_outcome", "step_index", "needs_vision",
               "vision_candidates", "ruled_out", "error_snippet",
               "pushes_used"), 384),
    # tool_approval (2026-10-10, pin_1fb3ce63bb3b): the binary
    # outcome-referenced approval question. A NEW job, not an extension of
    # `route` — route's cohorts must not re-stamp. The state carries the
    # PRE-CALL evidence only: the goal, the previous result, the proposed tool,
    # its description, the call's ARGUMENTS and the offered tool list. The
    # call's own result is NEVER a field (it is the label — a row whose input
    # carries its answer measures nothing).
    # v2 (2026-10-10, owner-directed iteration): `args` + `offered_tools` were
    # MISSING at v1, and v1's AUROC read 0.4953 at n=104 — for a tool like
    # run_command the ARGUMENTS are the strongest approval signal, and the
    # model could not see what else was offered. Budget 256 -> 384 for the
    # physical reason: goal[:200] + last_result[:400] + description[:200] +
    # args[:400] + offered names[:200] must all fit, and at 256 (1024 chars)
    # the cap cut the args — the very evidence v2 exists to deliver. 512 stays
    # the absolute ceiling (S19.3).
    # v3 (2026-10-11): `calls_this_step` - the same once-per-node frame defect
    # as tool_choice (last_result was the previous STEP's result, the step's
    # own calls were invisible). Budget stays 384 (1536 chars): the call site
    # caps calls_this_step and last_result at 300 and description/offered at
    # 150 so goal 200 + 300 + 300 + 150 + args 400 + 150 + labels fit with
    # args intact (the cap trims from the END; offered names go first).
    OracleJob("approve", "is this the right tool for this goal?",
              ("goal", "calls_this_step", "last_result", "proposed_tool",
               "tool_description", "args", "offered_tools"), 384),
    OracleJob("guard", "is this action safe to take without asking?",
              # REQ-5 AC5.2 (AC9.1 sanctioned exception 4): `guard` is the
              # first IMAGE job - click_safety's question is visual by
              # construction and its frame carries the session-scoped
              # screenshot under "screenshot" (AC5.3).
              # Budget 64 -> 128 (2026-10-11): click_safety's statement is
              # "action | task: goal[:300]" (~400 chars); at 64 ids (256 chars)
              # the cap cut the task and, before v2's action-first order, the
              # action itself. The cap is a ceiling for the other guard
              # consumer (needs_action), not a floor.
              ("goal",), 128, image_fields=("screenshot",)),
    OracleJob("judge_step", "did this step do its part?",
              ("goal",), 96),
    # review_verdict gets its OWN job (2026-10-16). It shared `judge_step` with
    # the ENFORCED `escalate_incomplete`, and `judge_step`'s 96-id budget is 384
    # chars — but review_verdict's frame (der_loop._shadow_review_verdict) is
    # STEP[:300] + OBJECTIVE[:200] + "RECENT RESULTS: <3 x result[:120]>", which
    # its call site caps at 800. The backend cap trims from the END, so RECENT
    # RESULTS — the completed steps' own results, the evidence the question
    # ("did this step do its part?") is about — were cut on every row.
    # A SEPARATE job rather than a raise of `judge_step`: the budget is not part
    # of the identity hash, but escalate_incomplete ACTS on its threshold and
    # must keep its own input untouched. The job IS part of the identity, so the
    # new cohort separates from the old judge_step rows.
    # Budget 288 = 1152 chars (2026-10-17, v3 frame): the v3 evidence is 3
    # envelope lines (each head+tail capped at 200 — the outcome of a tool run
    # lives at the TAIL of its output, so a head-only cut throws the signal
    # away; measured: raw result[:120] evidence -> constant verdict, oof AUROC
    # 0.5113; envelope evidence -> replay AUROC 1.0000). 3 x 200 + STEP[:300] +
    # TOOL + OBJECTIVE[:200] is ~1150 chars; at the old 200-id/800-char budget
    # the cap cut the OBJECTIVE — the bar the review rubric judges against.
    # 384 ids stays the owner ceiling (test_oracle_jobs_contract).
    OracleJob("judge_review", "did this step do its part?",
              ("goal",), 288),
    OracleJob("judge_goal", "is the objective met, deep and sufficient?",
              ("goal", "open_facts", "evidence"), 128),
    # depth_met gets its OWN job (2026-10-17, oracle.md 7.5: "Give the
    # judge_goal frame the evidence first and the coverage number, and keep
    # grade out"). It shared `judge_goal` with `done`/`sufficient`, whose
    # frames differ; judge_goal's 128-id budget (512 chars) cut depth_met's
    # EVIDENCE - the work product the depth question is about - to almost
    # nothing, and its field order rendered the criteria first. The v3 frame
    # (agent_kernel's grade block) is evidence[:1000] + coverage + open_facts
    # + goal(criteria) ~= 1500 chars = 384 ids, the owner ceiling; the field
    # order IS the render order (job_input), so evidence renders first and
    # only a max-length frame can clip the criteria. `grade` is deliberately
    # NOT a field: it is the incumbent reference and must stay out of the
    # input. A separate job rather than a judge_goal change: done/sufficient
    # keep their own input, and the job IS part of the identity, so the
    # depth_met/v3 cohort separates from the v2 rows.
    OracleJob("judge_depth", "is the objective met, deep and sufficient?",
              ("evidence", "coverage", "open_facts", "goal"), 384),
    # FRAME/JOB MISMATCH FIX (2026-10-10): the shape job declared ONLY `goal`,
    # but its consumers' frames carry OTHER keys — the renderer drops every
    # undeclared key, so `presentation` (whose frame has NO goal at all)
    # rendered an EMPTY state: d1 answered with zero evidence (measured 0/5
    # parity). `narration`'s frame carried beats_authored/beats_admitted — the
    # numbers that literally determine its reference (speak_all iff beats) —
    # and d1 never saw them. The job's fields are now the UNION of what its
    # consumers' frames carry; the renderer skips absent keys, so each consumer
    # renders what it has (a frame holding only goal renders as before).
    # Budget 96 -> 128: narration renders goal[:300] plus four short fields.
    OracleJob("shape", "how should this answer be delivered?",
              ("goal", "content_chars", "has_structure",
               "card_already_rendered", "zone", "mode",
               "steps", "beats_authored", "beats_admitted", "multi_segment"),
              128),
    OracleJob("classify_event", "which event family/type is this?",
              ("goal",), 64),
    # REQ-10 (AC10.3/AC10.7): `call_closing`'s own job. The state carries the
    # GOAL, the CALL and the CALL'S RESULT - the three things the closing
    # question is about. It is a new job rather than a reuse of `judge_step`
    # because the fields differ; AC9.1's exception list did not name this
    # addition (the spec text and AC10.7 disagree) and the wave notes record it.
    OracleJob("judge_call", "was this call the closing call of the step?",
              ("goal", "call", "result"), 96),
    OracleJob("general", "a consumer not yet assigned to a job",
              ("goal",), 128),
)}

CONSUMER_JOBS: Dict[str, str] = {
    # `mode` REMOVED 2026-10-10 (owner): see the CONSUMERS tuple.
    "web_intent": "interpret_web", "user_feedback": "interpret",
    "tool_choice": "route", "recovery_strategy": "route",
    # tool_approval (2026-10-10): its own job — the pre-call approval question.
    "tool_approval": "approve",
    # T1.8 (AC9.1 sanctioned exception 1): `browser_next` and `web_depth` had job
    # assignments and NO call site anywhere in the backend - the same class as
    # `on_track` and `retry_same`, both deleted for exactly that reason. 19 -> 17.
    "depth_route": "route",
    # browser_next RETURNS (2026-10-11) with a real call site: the node loop's
    # browser_act hook (browser_next_shadow). Same route fields: goal,
    # done_when, calls_this_step and the page head as last_result; the element
    # labels ride the option lines.
    "browser_next": "route",
    "click_safety": "guard", "needs_action": "guard",
    "review_verdict": "judge_review",
    "escalate_incomplete": "judge_step",
    # REQ-10: the per-call closing question has its own job (AC10.7).
    "call_closing": "judge_call",
    "done": "judge_goal", "depth_met": "judge_depth", "sufficient": "judge_goal",
    "presentation": "shape", "narration": "shape",
    "event_family": "classify_event",
}


def oracle_job(consumer_id: str) -> OracleJob:
    """The job of a consumer (``event_type:<family>`` -> classify_event)."""
    name = CONSUMER_JOBS.get(consumer_id)
    if name is None and str(consumer_id).startswith("event_type:"):
        name = "classify_event"
    return ORACLE_JOBS[name or "general"]


# ── Consumer criteria (REQ-19) ─────────────────────────────────────────────
# Wave 5 (specs/phonon2-d1-model-swap T5.3): this machinery MOVED here from
# decision_backend_onnx.py, which is deleted with the rest of the GLiNER
# backend. The registry is backend-agnostic — the d1 backend reads the
# registered instruction (the Decision Index `instructions` field), and
# every consumer site registers through it. One home, one import.

_TOOL_TASK_INSTRUCTION = "Which tool should handle this request?"

# ── REQ-4: the DECLARED decision type (AC4.1/AC4.2/AC4.4) ───────────────────
# d1's native API answers TYPED questions, and the shapes have different
# readouts: `noul` (P(statement true)), `choice` (pick one of the named
# options), `score` (an ordered level). The type is therefore a property of the
# DECISION POINT and is DECLARED, never inferred - `len(options) == 2`
# misreads a genuine two-option choice, and a generic fallback is exactly how
# `review_verdict` ended up asking an under-specified question the incumbent
# passed 96% of the time.
DECISION_TYPES: Tuple[str, ...] = ("noul", "choice", "score")


@dataclass(frozen=True)
class ConsumerDeclaration:
    """One consumer's declared shape: its decision type and its criteria.

    `criteria` by type (AC4.2):
      * `noul`   - a mapping naming each side, e.g. ``{"true": ..., "false": ...}``
      * `choice` - ``name -> description`` for every option
      * `score`  - an ordered tuple of level descriptions, lowest first
    """

    decision_type: str                      # one of DECISION_TYPES
    criteria: Any = None


# THE declaration table: one entry per fixed consumer, the single source of
# truth for "what shape is this decision point". Register sites supply only
# their own instruction and label set (`register_declared`). A consumer absent
# from this table registers UNDECLARED and the engine REFUSES to score it
# (AC1.6) - it does not inherit another consumer's shape and it does not get a
# generic fallback.
CONSUMER_DECLARATIONS: Dict[str, ConsumerDeclaration] = {
    # ── choice over a caller-supplied menu ──────────────────────────────────
    # The names come from the menu built upstream (the tool schemas); there is
    # no static name set to describe, so the mapping is empty by design.
    "tool_choice": ConsumerDeclaration("choice", {}),
    # Descriptions (2026-10-11): the reference renders "A {description}"; bare
    # names like `decompose` carry little meaning to the model.
    "recovery_strategy": ConsumerDeclaration("choice", {
        "retry_same": "Run the same tool call again (a transient error)",
        "retry_different_tool": "Reach the same goal with a different tool",
        "decompose": "Split the failed step into smaller steps",
        "escalate": "Give up on this approach and make a new plan",
        "DELEGATE": "Not sure - let the planner decide",
    }),
    "presentation": ConsumerDeclaration("choice", {
        "plain_text": "Answer in prose only, with no rendered card",
        "prism_card": "Render a prism card carrying the structured result",
        "card_plus_summary": "Render a card and a short prose summary beside it",
    }),
    "narration": ConsumerDeclaration("choice", {
        "speak_all": "Speak every beat of the plan aloud",
        "speak_first_only": "Speak only the first beat, then stay quiet",
        "stay_silent": "Speak nothing for this plan",
    }),
    # REQ-13/T4.3 (B3): the QUALITY bar must be in the descriptions, or the
    # incumbent passes everything (it said pass 96% of the time). `refine` has
    # to be reachable on vague / incomplete / wrong-tool steps, not only on
    # outright conflicts.
    "review_verdict": ConsumerDeclaration("choice", {
        "pass": "The step did its part: the change is present, correct and testable",
        "refine": ("The step is vague, incomplete or uses the wrong tool - it "
                   "needs another pass before it is trusted"),
        "veto": "The step must not run: it is unsafe, off-goal or harmful",
    }),
    # `mode` REMOVED 2026-10-10 (owner): see the CONSUMERS tuple. A consumer
    # absent from this table registers UNDECLARED and the engine REFUSES to
    # score it (AC1.6) - the removal is fail-closed by construction.
    "depth_route": ConsumerDeclaration("choice", {
        "cover_open_fact": "Cover a required fact that is still open",
        "bonus_ceiling": "Run the bounded bonus pass over the ceiling facts",
        "deepen": "Push for more depth - the work is only superficially complete",
        "next_step": "Pursue the next step the Brain named",
        "finalize": "Finalize and answer",
        "DELEGATE": "Below the Oracle's pay grade - hand back to the incumbent",
    }),
    # ── noul: a statement answered with P(true) ─────────────────────────────
    # `sufficient`/`done`/`depth_met` are documented noul (oracle.md AC14.6),
    # and d1 was TRAINED on yes/no questions in this shape (V1 probe:
    # 98.8%/96.5% polarity-correct).
    "done": ConsumerDeclaration("noul", {
        "true": "The task is finished: every required fact is covered",
        "false": "The task still needs work",
    }),
    "sufficient": ConsumerDeclaration("noul", {
        "true": "The objective is covered by the work done so far",
        "false": "The objective is not yet covered",
    }),
    "depth_met": ConsumerDeclaration("noul", {
        "true": "Done to the depth the success criteria require",
        "false": "Only superficially complete",
    }),
    "escalate_incomplete": ConsumerDeclaration("noul", {
        "true": "Too incomplete to proceed without more work",
        "false": "Complete enough to proceed",
    }),
    # 2026-10-13 replay on real d1, 16 hand-labelled step goals: "requires
    # calling a tool" 11/16 (it said NO to opening a URL, editing a file,
    # listing a folder, saving a file); naming the tools 16/16.
    "needs_action": ConsumerDeclaration("noul", {
        "true": "Yes: it needs the browser, a file, a search or a command",
        "false": "No: it only writes or reasons about information that is already available",
    }),
    "web_intent": ConsumerDeclaration("noul", {
        "true": "This request requires fetching information from the web",
        "false": "This request does not require the web",
    }),
    # tool_approval (2026-10-10, pin_1fb3ce63bb3b): the binary
    # outcome-referenced approval consumer. The reference is the call's OUTCOME
    # (brain_bool = success), so the label is GROUND TRUTH, not parity — the
    # fix for tool_choice's parity-label noise. The true/false lines render as
    # the reference's Yes:/No: criteria lines.
    "tool_approval": ConsumerDeclaration("noul", {
        "true": "This tool is the right next tool for the goal, given the last result",
        "false": "This tool is not the right next tool for the goal",
    }),
    # NOTE (declared from the CODE, not the spec's prose): click_safety's real
    # label set is ("safe", "unsafe", "unsure") - three options, so it is a
    # CHOICE. REQ-5 describes the question as a "yes/no safety question about
    # one named action", but the consumer as wired passes three labels; a noul
    # declaration would misread its own readout. Its rules -> judge ->
    # escalation ladder is untouched (AC5.2). Recorded in the Wave 1 notes.
    "click_safety": ConsumerDeclaration("choice", {
        "safe": "Safe to take without asking the user",
        "unsafe": "Unsafe - the user must approve first",
        "unsure": "Cannot tell - ask the user",
    }),
    # REQ-10 (AC10.1): the per-call closing question. A statement, so a noul.
    "call_closing": ConsumerDeclaration("noul", {
        "true": "This call was the step's closing call",
        "false": "This call was not the step's closing call",
    }),
    # ── choice over a family's own labels ───────────────────────────────────
    "user_feedback": ConsumerDeclaration("choice", {}),
    # The options are the page's element ids; their labels arrive per consult
    # as dynamic criteria (the menu changes with every page).
    "browser_next": ConsumerDeclaration("choice", {}),
    "event_family": ConsumerDeclaration("choice", {}),
}


def _declaration(consumer_id: str) -> Optional[ConsumerDeclaration]:
    """The declaration for *consumer_id*, with the family-inheritance rule.

    AC13.5: a dynamically created `event_type:<family>` consumer INHERITS its
    family's declaration (`event_family`), never a generic fallback. An unknown
    family therefore has no declaration and creates no scorable consumer.
    """
    decl = CONSUMER_DECLARATIONS.get(consumer_id)
    if decl is None and str(consumer_id).startswith("event_type:"):
        decl = CONSUMER_DECLARATIONS.get("event_family")
    return decl


def declared_type(consumer_id: str) -> str:
    """The DECLARED decision type, or "" when the consumer is undeclared."""
    decl = _declaration(consumer_id)
    return decl.decision_type if decl is not None else ""


def declared_criteria(consumer_id: str) -> Any:
    """The declared criteria block, or None when the consumer is undeclared."""
    decl = _declaration(consumer_id)
    return decl.criteria if decl is not None else None


def is_declared(consumer_id: str) -> bool:
    """True when the consumer declares a usable decision type (AC1.6)."""
    return declared_type(consumer_id) in DECISION_TYPES


def needs_upgrade(spec: Optional["ConsumerSpec"]) -> bool:
    """True when *spec* is absent or predates REQ-4 (AC13.4).

    The register functions are IDEMPOTENT, so an already-registered consumer
    would otherwise keep its pre-REQ-4 shape forever: the change would appear to
    work in tests (fresh registry) and never take effect in production (warm
    registry). Every register site checks this instead of ``is None``.
    """
    return spec is None or not getattr(spec, "decision_type", "")


@dataclass(frozen=True)
class ConsumerSpec:
    """One consumer's own scoring criteria (REQ-19 AC19.1, REQ-4).

    ``labels`` empty means the caller supplies the option set (menu-shaped
    consumers such as ``tool_choice``); a non-empty tuple is a FIXED label set
    (the bool consumers).

    ``decision_type`` is REQUIRED for scoring: "" means UNDECLARED, and the
    engine refuses to score such a consumer rather than borrowing another
    consumer's head or a generic shape (REQ-4 AC4.1, AC1.6).

    ``criteria`` carries the typed criteria block (REQ-4 AC4.2). It used to be
    a ``bool`` flag - a flag is not a criteria, and that was the structural
    reason the named-criteria shape was unreachable: there was nowhere to put a
    description.
    """

    consumer_id: str
    task_name: str
    instruction: str
    decision_type: str = ""                 # "" = undeclared -> refused (AC1.6)
    exclusive: bool = True
    labels: Tuple[str, ...] = ()
    criteria: Any = None                    # typed by decision_type (AC4.2)


CONSUMER_TASKS: Dict[str, ConsumerSpec] = {
    # Pinned to the measured bench shape (AC22.1 / AC19.4) - do not edit.
    # REQ-4: typed as a choice; the names come from the menu built upstream.
    "tool_choice": ConsumerSpec(
        consumer_id="tool_choice",
        task_name="tool",
        instruction=_TOOL_TASK_INSTRUCTION,
        decision_type="choice",
        exclusive=True,
        criteria=CONSUMER_DECLARATIONS["tool_choice"].criteria,
    ),
}


# The question used for a consumer that registers ITSELF (2026-09-27). A new
# decision point that never declared its question can still be MEASURED this
# way; the bar then decides whether it deserves a better question. Deliberately
# generic: an honest vague question beats no measurement, and an uncalibrated
# consumer can never enforce.
AUTO_INSTRUCTION = (
    "Choose the single best option for the goal below. The options are the "
    "candidate answers to one question about the current step."
)


def ensure_consumer_spec(
    consumer_id: str,
    options: Sequence[str],
    instruction: Optional[str] = None,
) -> Optional[ConsumerSpec]:
    """Return *consumer_id*'s criteria, REGISTERING them on first sight.

    WHY (2026-09-27): a new decision point could not be measured at all until
    someone hand-wrote a ``ConsumerSpec``, and ``DecisionEngine.decide`` refused
    any id outside the frozen CONSUMERS tuple - so the application could not
    evolve with use, and every new consumer needed manual creation. Measured
    consequence: `recovery_strategy` scored nothing for its whole life, and
    `narration` produced no row until a registration block was written by hand.

    The caller already passes the option set on EVERY call, so the labels need no
    declaration. ``instruction`` is taken from the caller when given (the best
    question), else a generic one is used so the consumer is still measured.

    SAFETY: REGISTERING IS NOT ENFORCING. An uncalibrated consumer has no
    threshold for the active backend, so it cannot steer anything. The report
    shows it fail-closed ("no threshold for the active backend") until a
    threshold is calibrated for it, and the bar still requires 100 rows,
    precision >= 0.90 and ECE <= 0.05 before a flip.

    REQ-4 (AC1.6): a consumer with NO declared decision type is registered
    UNDECLARED and the engine REFUSES to score it. It does not inherit another
    consumer's shape and it does not borrow a generic one - a generic fallback
    is how `review_verdict` ended up asking an under-specified question the
    incumbent passed 96% of the time.
    """
    spec = CONSUMER_TASKS.get(consumer_id)
    if spec is not None and not needs_upgrade(spec):
        return spec
    decl = _declaration(consumer_id)
    if decl is not None:
        return register_declared(
            consumer_id, instruction or AUTO_INSTRUCTION,
        )
    labels = tuple(o for o in options if isinstance(o, str) and o)
    if not labels:
        return None
    logger.info(
        "decision_engine: auto-registered consumer=%s labels=%d "
        "(UNDECLARED - no decision type, so it scores nothing; AC1.6)",
        consumer_id,
        len(labels),
    )
    return register_consumer_spec(ConsumerSpec(
        consumer_id=consumer_id,
        task_name=consumer_id,
        instruction=instruction or AUTO_INSTRUCTION,
        # UNDECLARED. The labels are recorded for observability only; the
        # engine refuses to score this consumer until a type is declared.
        decision_type="",
        labels=(),
    ))


def register_declared(
    consumer_id: str,
    instruction: str,
    labels: Sequence[str] = (),
    criteria: Any = None,
) -> ConsumerSpec:
    """Register a consumer with its DECLARED type and criteria (REQ-4).

    The declaration table is the single source of truth for the type, so a
    register site supplies only its own instruction and label set. A consumer
    with no declaration registers UNDECLARED and is refused by the engine
    (AC1.6). Every register site uses this instead of constructing a bare
    ``ConsumerSpec`` so the type can never drift from the declaration.

    ``criteria`` overrides the table's block only where the criteria are
    DATA-driven rather than static - the one case today is an
    ``event_type:<family>`` consumer, whose criteria describe its family's
    labels (AC13.5).
    """
    decl = _declaration(consumer_id)
    if criteria is None and decl is not None:
        criteria = decl.criteria
    return register_consumer_spec(ConsumerSpec(
        consumer_id=consumer_id,
        task_name=consumer_id,
        instruction=instruction,
        decision_type=decl.decision_type if decl is not None else "",
        criteria=criteria,
        labels=tuple(labels),
    ))


def register_consumer_spec(spec: ConsumerSpec) -> ConsumerSpec:
    """Register (or replace) a consumer's criteria (REQ-19 AC19.3)."""
    CONSUMER_TASKS[spec.consumer_id] = spec
    return spec


def get_consumer_spec(consumer_id: str) -> Optional[ConsumerSpec]:
    """The registered criteria for *consumer_id*, or None."""
    return CONSUMER_TASKS.get(consumer_id)


# Off-path threads: the ordered lanes ("iris-<lane>") and the shadow scorers'
# own threads. A decision on any other thread is one a caller waits for. Counted
# per consumer (no I/O here; a report joins the counts with the enforced set: an
# unenforced consumer with inline counts is a measurement the reply waited for).
_OFF_PATH_THREAD_PREFIXES = ("iris-", "shadow-")
INLINE_DECISION_COUNTS: Dict[str, int] = {}
_INLINE_COUNT_LOCK = threading.Lock()


def _note_inline_shadow(consumer_id: str) -> None:
    """Count a decision scored on a non-lane thread. Never raises."""
    try:
        if threading.current_thread().name.startswith(_OFF_PATH_THREAD_PREFIXES):
            return
        with _INLINE_COUNT_LOCK:
            INLINE_DECISION_COUNTS[consumer_id] = INLINE_DECISION_COUNTS.get(consumer_id, 0) + 1
            total = sum(INLINE_DECISION_COUNTS.values())
            snapshot = dict(INLINE_DECISION_COUNTS) if total % 100 == 0 else None
        if snapshot is not None:
            # The reader: one line per 100 inline decisions. A consumer listed
            # here that is not enforced is a measurement the reply waited for.
            logger.info("%s inline decisions (process total %d): %s",
                        ENGINE_NAME, total, snapshot)
    except Exception:  # noqa: BLE001 - an observer never blocks a decision
        pass


def _fmt_field(value: Any) -> str:
    if isinstance(value, (list, tuple)):
        return "; ".join(str(v) for v in value[:6])
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def job_input(consumer_id: str, frame: Dict[str, Any]) -> OracleState:
    """The structured state the backend scores (REQ-3 AC3.1): the job's
    declared fields rendered in order into the text, the job's text budget,
    and the job's DECLARED images only (AC5.1 - a text consumer never receives
    an image, whatever else the frame carries; a frame holding only ``goal``
    renders to the same text as before, so text consumers keep their
    calibrated input, except where the budget cuts a longer text)."""
    job = oracle_job(consumer_id)
    parts = []
    for f in job.fields:
        v = (frame or {}).get(f)
        if v is None or v == "" or v == [] or v == ():
            continue
        parts.append(str(v) if f == "goal" else f"{f}: {_fmt_field(v)}")
    images = tuple(
        bytes(v) for f in job.image_fields
        for v in [(frame or {}).get(f)]
        if isinstance(v, (bytes, bytearray)) and v
    )
    # DYNAMIC-MENU CRITERIA: passed through untouched — never a state field
    # (it is not in any job's declared fields, so it never renders into the
    # text), never dropped (the backend renders it into the option lines).
    _oc = (frame or {}).get("option_criteria")
    option_criteria = tuple(
        (str(k), str(v)) for k, v in dict(_oc or {}).items()) if _oc else ()
    return OracleState(
        job=job.name, fields=tuple(job.fields), text="\n".join(parts),
        budget_ids=job.budget_ids, images=images,
        option_criteria=option_criteria,
    )


@dataclass(frozen=True)
class CandidateScore:
    name: str        # option name (tool name, surface name, or DELEGATE/NONE)
    logprob: float   # raw label logit under the schema prompt (ONNX backend)
    prob: float      # softmax-normalized probability


@dataclass(frozen=True)
class DecisionScore:
    consumer_id: str
    chosen: str
    confidence: float                 # = P(chosen)
    distribution: Tuple[CandidateScore, ...]
    engine_latency_ms: int
    retried: bool = False
    # REQ-17 hierarchical detail: stage scores when a two-stage tree was used.
    # The tree is retired (REQ-22 AC22.3 — flat scoring is the only path), so
    # this is always None today; the field stays because the envelope shape is
    # pinned unchanged (AC21.2).
    stage_detail: Optional[Dict[str, Any]] = None

    def confident(self, threshold: float) -> bool:
        """True when the calibrated probability clears the threshold."""
        return self.confidence >= threshold


@dataclass(frozen=True)
class Noul:
    """REQ-14 AC14.6 (T18): a single calibrated probability of TRUTH.

    Deliberately NOT a two-option ``DecisionScore``. JEV's ``Noul`` returns
    P(statement true) with no separate confidence field, and REQ-14 AC14.4's
    fail-closed advisory gate depends on that probability meaning exactly what
    it claims: "is the statement true", not "which of two labels won".

    The measurement may be a two-label softmax (the schema backend scores
    ``yes``/``no`` and we take P(yes)) — the ENVELOPE is what changes: one
    probability, no winner, no confidence, so a caller cannot mistake a
    2-way choice for a calibrated belief.
    """

    consumer_id: str
    probability: float                # P(statement is true), in [0, 1]
    engine_latency_ms: int

    def true(self, threshold: float = 0.5) -> bool:
        """The boolean judgment at *threshold*."""
        return self.probability >= threshold

    def confident(self, threshold: float) -> bool:
        """True when the belief is decisively on ONE side of the flip point.

        ``threshold`` is a probability margin, and the test is TWO-SIDED:
        ``p >= threshold`` (confidently true) or ``p <= 1 - threshold``
        (confidently false). A one-sided ``p >= threshold`` would let the
        engine assert "true" but never "false" — an asymmetry that would leave
        a fail-closed gate permanently open.
        """
        return self.probability >= threshold or self.probability <= (1.0 - threshold)


@dataclass(frozen=True)
class ArgsResult:
    args: Optional[Dict[str, Any]]    # None = invalid/empty after retry
    retried: bool
    # REQ-10 AC10.3 (T13): which deterministic pattern filled the args, when a
    # fast path was taken ("" = the LLM/generation path). ADDITIVE field — the
    # envelope shape is otherwise unchanged (AC21.2). It is the calibration
    # join key, so a pattern id is a STABLE name, never a re-worded one.
    fast_path: str = ""


@dataclass
class EngineCounters:
    decisions: int = 0
    escalations: int = 0              # filled in by the box (kept here for one read site)
    memory_fallbacks: int = 0
    retries: int = 0
    unavailable_events: int = 0
    load_failures: int = 0
    lock_timeouts: int = 0
    # REQ-13 AC13.3: per-consumer accounting so calibration reads them apart.
    by_consumer: Dict[str, int] = field(default_factory=dict)

    def bump_consumer(self, consumer_id: str) -> None:
        self.by_consumer[consumer_id] = self.by_consumer.get(consumer_id, 0) + 1


# ENFORCEMENT (2026-10-05, Oracle Stage B): ONE chokepoint, `decides()` below.
# Every site that lets the Oracle's verdict replace a rule or the Brain asks it;
# nothing reads IRIS_DECISION_ENFORCE, the bar record or a threshold on its own.
# ── REQ-2: the DECISION IDENTITY (AC2.1) ────────────────────────────────────
# Today the identity is the served GGUF filename variant alone
# (`_current_backend_identity()`), and it is too small: the probe showed the
# READOUT changes the model's behaviour more than any instruction does, and
# oracle.md §19.3.6 already says a changed INPUT is a new identity. The readout
# is the largest such input, and the criteria are the second.
#
#     identity = f"{model_id}|{readout_mode}|{criteria_hash}"
#
# A calibrated threshold cannot survive a change of readout or of criteria: the
# curve was measured on ONE input shape, so re-using it under another is the
# silent-flip mistake this key exists to prevent.
# "letters" (2026-10-10): the REFERENCE readout restored — d1's trained shape
# (LiquidAI/d1-3B prompt.py: coded options, letter-token readout, manual
# im_start prompt over /completion). Measured live against our own server:
# confidence spreads 0.47-0.99 with the case, where the retired "native"
# name-token readout sat flat at 0.90-0.96 (OOF AUROC 0.476). Keep in sync
# with decision_backend_d1._READOUT_TAG.
CURRENT_READOUT_MODE = "letters"
# The RETIRED letter mode, recorded so historical rows address a real, nameable
# identity rather than silently matching the current one (T3.1). The Wave-2
# "native" name-token era needs no constant: its rows carry the bare model id
# (no readout tag) and separate through the engine field by construction.
LEGACY_READOUT_MODE = "legacy_letters"
# AC13.3: the candidate cap changes the RENDERED criteria block, so it belongs
# inside the hash - tuning the cap re-identifies every choice consumer exactly
# as editing its criteria text does.
#
# RAISED 6 -> 11 (2026-10-09, measured live against data/memory.db). At 6 the
# menu reserved two slots for DELEGATE/NONE and passed only FOUR real tools to
# the model, so 224 of 225 d1 tool_choice rows scored the SAME six names
# [read_file, edit_file, grep_files, run_command, DELEGATE, NONE] and
# `write_file` - a PRIMARY tool in a coding agent - was structurally
# UNREACHABLE. 53 of 225 rows (24%) recorded a reference the model was never
# offered (list_directory x31, write_file x21, search x1); those rows are now
# counted as unscoreable rather than scored wrong, but counting them is not a
# substitute for being able to score them. 11 covers `_DEV_MENU_ORDER`'s nine
# tools plus the two control labels, so every developer tool is reachable and
# the truncation that produced the defect cannot recur at this width.
#
# The consequence is BY DESIGN (AC13.3): this changes criteria_hash, so every
# choice consumer is re-identified and its threshold stops resolving. No
# consumer is enforced today, so nothing flips - but any threshold fitted
# under the cap of 6 is now correctly stale.
#
# 11 -> 32 (2026-10-11): 11 still truncated in REGISTRY order outside developer
# mode - the nine file tools came first and every browser tool fell off the
# menu (browser tasks: d1 agreed 0% on browser_open/observe/act; it could never
# pick them). 32 covers every NODE_TOOLS entry (24) + the screen tools + the two
# control labels. Re-identifies the choice consumers again (AC13.3) - no
# threshold exists yet, so nothing goes stale that was in use.
CANDIDATE_CAP_DEFAULT = 32

# The general bound on ANY consumer's options: the reference code pool
# (A..Z then 00..99). `candidate_cap` is only the tool menu's width.
OPTION_CEILING = 120


def criteria_hash(consumer_id: str,
                  candidate_cap: int = CANDIDATE_CAP_DEFAULT) -> str:
    """A stable digest of *consumer_id*'s DECLARED criteria block (AC2.1).

    Editing a consumer's criteria - or the candidate cap that bounds its
    rendered option list (AC13.3) - changes this digest, so the consumer is
    re-identified and its threshold stops resolving. That is oracle.md §19.3.6's
    existing rule, now actually enforceable because the criteria are
    addressable.
    """
    try:
        import hashlib

        decl = _declaration(consumer_id)
        payload = {
            "type": decl.decision_type if decl is not None else "",
            "criteria": decl.criteria if decl is not None else None,
            "cap": int(candidate_cap),
        }
        blob = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
        return hashlib.sha1(blob).hexdigest()[:12]
    except Exception:  # noqa: BLE001 - an unhashable criteria is its own answer
        return "unhashed"


def decision_identity(model_id: str, readout_mode: str,
                      consumer_id: Optional[str] = None,
                      candidate_cap: int = CANDIDATE_CAP_DEFAULT) -> str:
    """Build an identity for ANY (model, readout, consumer) triple (AC2.1).

    Used by the live path through `_current_backend_identity`, and to NAME a
    retired configuration: `decision_identity("d1-3b-ad-q4_k_m",
    LEGACY_READOUT_MODE, "tool_choice")` addresses the letter-era rows' identity
    instead of letting them silently match the native one (T3.1).
    """
    parts = [str(model_id), str(readout_mode)]
    if consumer_id:
        parts.append(criteria_hash(consumer_id, candidate_cap))
    return "|".join(parts)


def _current_backend_identity(
    consumer_id: Optional[str] = None,
    candidate_cap: int = CANDIDATE_CAP_DEFAULT,
) -> str:
    """The ACTIVE engine's identity, resolved the way the report resolves it.

    Without a consumer this is the BACKEND identity `model|readout_mode`; with
    one it is the full decision identity `model|readout_mode|criteria_hash`
    (AC2.1), because the criteria belong to the decision point rather than to
    the model.

    The loaded engine knows its own id; this process usually has not loaded one,
    so the DECLARED backend's variant is the fallback (constructing the backend
    does not load its weights). "" when neither is available - and an unknown
    identity must never unlock an enforcement (AC2.2).
    """
    model = ""
    try:
        model = str(getattr(get_decision_engine(), "model_id", "") or "")
    except Exception:  # noqa: BLE001 — identity is best-effort, never fatal
        model = ""
    if not model:
        try:
            # Wave 3 (specs/phonon2-d1-model-swap): the declared backend is d1;
            # the identity is variant-derived from the served GGUF filename, and
            # constructing the backend does NOT load anything or touch the
            # server (same cheap-construction rule GlinerOnnx had).
            from .decision_backend_d1 import D1Backend

            model = str(D1Backend().backend_id or "")
        except Exception:  # noqa: BLE001 — unknown identity = no flips
            return ""
    if not model:
        return ""
    return decision_identity(model, CURRENT_READOUT_MODE, consumer_id, candidate_cap)



def _bar_record_enforced() -> frozenset:
    """Consumers the BAR RECORD says are enforced, MEASURED ON THIS ENGINE.

    Owner decision 2026-09-27 (option B): passing the bar turns a consumer on,
    with no hand-edited list. Two conditions, both required:

      * the record's status is ``enforced`` - which ``derive_status`` sets only
        when rows >= 100 AND precision >= 0.90 AND ECE <= 0.05. Never a partial
        flip (AC18.4/AC22.4);
      * the record was measured against the CURRENT engine identity, so a flip
        earned on a retired model cannot carry over. This mirrors the
        stale-configuration guard, and it is the same mistake that let 457
        retired-engine rows report as the current model's accuracy - see §16 of
        docs/architecture/oracle.md.

    NOT filtered by CONSUMERS: a consumer that registered itself is exactly the
    case this exists for, and it still cannot be enforced without passing the
    bar, which cannot happen without a calibrated threshold for the active
    backend. An absent record (never written, unreadable, empty) enforces
    nothing - the safe default.

    REQ-2 (AC2.1/AC2.2): the recorded ``backend_id`` is the FULL DECISION
    identity ``model|readout_mode|criteria_hash`` of the consumer the bar was
    earned for, so each consumer is compared against ITS OWN active identity.
    A bar recorded under the retired letter readout carries a
    ``legacy_letters`` (or bare model) identity and never matches a native one
    - the flip must be re-earned on the deployed readout and criteria.
    """
    try:
        from .consumer_bar import load_bar_record

        record = load_bar_record()
    except Exception as e:  # noqa: BLE001 — an unreadable record enables nothing
        logger.debug("decision_engine: bar record unreadable (%r)", e)
        return frozenset()
    if not record:
        return frozenset()
    out = set()
    for cid, bar in record.items():
        try:
            if str(getattr(bar, "status", "") or "") != "enforced":
                continue
            measured_on = str(
                (getattr(bar, "config", None) or {}).get("backend_id") or ""
            )
            current = _current_backend_identity(cid)
            if not current or measured_on != current:
                logger.warning(
                    "decision_engine: NOT enforcing %s - its bar was measured on "
                    "%r while the active engine is %r (a flip must be re-earned "
                    "on the deployed model)",
                    cid, measured_on or "an unrecorded engine", current or "unknown",
                )
                continue
            out.add(cid)
        except Exception:  # noqa: BLE001 — a malformed bar is skipped
            continue
    return frozenset(out)


def _owner_allow_list() -> frozenset:
    """The consumers the OWNER switched on (``IRIS_DECISION_ENFORCE``, a csv).

    DEFAULT EMPTY. It used to default to "tool_choice": born "enforced", but
    tool_choice has no production deciding path and sits below the bar, so the
    default switched on nothing real and hid that the bar record alone could
    enforce. The owner decides WHERE the Oracle pays; the bar decides whether it
    MAY (narration passes the bar - AUROC 0.78, precision 0.905 - but its
    reference is a free deterministic rule, so enforcing it would swap a 0 ms
    rule for a 300 ms model that disagrees 10% of the time).
    """
    raw = os.environ.get("IRIS_DECISION_ENFORCE", "")
    return frozenset(c.strip() for c in raw.split(",") if c.strip() in CONSUMERS)


def _config_stale() -> bool:
    """True when the deployed configuration differs from the calibrated one.

    `EngineConfig.threshold_for` already refuses a threshold then, but a caller
    that forgets to check would still steer (AC31.4/AC31.6). Reading staleness
    must NEVER break the reply path: a config object without the attribute (a
    stub, a partially-built engine) or an unreadable one means "not stale" - the
    real guarantee is that `threshold_for` independently returns None.
    """
    try:
        cfg = getattr(get_decision_engine(), "_cfg", None)
        _stale_attr = (
            getattr(cfg, "threshold_stale", None) if cfg is not None else None
        )
        stale = bool(_stale_attr() if callable(_stale_attr) else _stale_attr)
    except Exception as e:  # noqa: BLE001 - an unreadable config changes nothing
        logger.debug("decision_engine: staleness unreadable (%r)", e)
        return False
    if stale:
        logger.warning(
            "decision_engine: deployed configuration differs from the "
            "calibrated one (candidate_cap=%s, calibrated_cap=%s) - thresholds "
            "are STALE, refusing enforcement (AC31.4)",
            getattr(cfg, "candidate_cap", None),
            getattr(cfg, "calibrated_cap", None),
        )
    return stale


def _enforcement(consumer_id: str) -> Tuple[Optional[float], str]:
    """``(calibrated threshold, "")`` when the consumer may decide, else ``(None, why)``.

    The four keys, cheapest first: the owner's switch, the earned bar, a fitted
    threshold for the ACTIVE engine, a configuration that is not stale.
    """
    if consumer_id not in _owner_allow_list():
        return None, "not switched on (IRIS_DECISION_ENFORCE)"
    if consumer_id not in _bar_record_enforced():
        return None, "not earned (no enforced bar record for the active engine)"
    from . import oracle_calibration

    t = oracle_calibration.threshold(
        _current_backend_identity(consumer_id), consumer_id)

    if t is None:
        return None, "no fitted threshold for the active engine"
    if _config_stale():
        return None, "stale configuration"
    return t, ""


_ENFORCEMENT_LOGGED = False
_ENFORCEMENT_IDENTITY: Optional[str] = None


def _log_enforcement_once() -> None:
    """One INFO line per process: who decides, and why each allow-listed
    consumer that does not, does not. A silent "nothing decides" would be
    indistinguishable from a broken switch."""
    global _ENFORCEMENT_LOGGED, _ENFORCEMENT_IDENTITY
    # Once - and ONCE MORE when the engine's identity changes. The first
    # decides() can run while d1 is still loading: the identity then falls
    # back to the declared variant (no readout tag) and the line said "not
    # earned" for a consumer that decided a second later (measured
    # 2026-10-11). Re-logging on the identity change reports the state the
    # decisions actually use; a process with no engine still logs (a silent
    # "nothing decides" must stay distinguishable from a broken switch).
    try:
        ident = str(getattr(get_decision_engine(), "model_id", "") or "")
    except Exception:  # noqa: BLE001 - identity is best-effort
        ident = ""
    if _ENFORCEMENT_LOGGED and (not ident or ident == _ENFORCEMENT_IDENTITY):
        return
    _ENFORCEMENT_LOGGED = True
    _ENFORCEMENT_IDENTITY = ident
    allowed = sorted(_owner_allow_list())
    deciding, refused = [], []
    for c in allowed:
        t, why = _enforcement(c)
        if t is not None:
            deciding.append(f"{c}@{t}")
        else:
            refused.append(f"{c} ({why})")
    logger.info(
        "%s enforcement: deciding=%s; allow-listed but NOT deciding=%s%s",
        ENGINE_NAME, deciding or "none", refused or "none",
        "" if allowed else " (IRIS_DECISION_ENFORCE is empty)",
    )


# ── AC6.6 tier C: REFUSED OUTRIGHT ──────────────────────────────────────────
# Never enforced, never sampled, never resolved to a threshold. This is a
# REFUSAL, not a default: no flag, config value or later wave may enable one.
#
# `call_closing` is here BY DESIGN (REQ-10 AC10.0 fence 1). The owner's fear -
# "the agent stops its work early thinking it's done and not adhering to the
# goal contract" - is NOT hypothetical: `done` already has a live enforcement
# path (agent_kernel.py:20962 passes `enforced=_done_dec` and :20970 writes the
# Oracle's answer into `data["done"]`, the bit the loop reads). So a
# naming convention is not a defence. Three fences stand instead: this refusal,
# a contract test that `node_executor` never reads the answer (T1.12), and the
# existing goal-contract veto at agent_kernel.py:20983-20989.
REFUSED_CONSUMERS: frozenset = frozenset({"call_closing"})


# ── REQ-10: `call_closing`'s candidate rule ─────────────────────────────────
# Asked ONLY about calls that CLAIMED to close the step (AC10.2), and NEVER
# about a call that changed a file (AC10.5). Both are DECLARATIONS, not per-run
# judgements, so they live beside the refusal list rather than at a call site
# someone can quietly flip. The consult itself lands in Wave 5.
CALL_CLOSING_CONSUMER = "call_closing"
CALL_CLOSING_CHANGED_FILE_EXCLUDED = True


def call_closing_is_candidate(*, claimed_step_done: bool,
                              batch_changed: bool) -> bool:
    """Should ``call_closing`` be asked about this call? (AC10.2, AC10.5)

    Asked ONLY about calls where the model claimed ``step_done`` (or wrote a
    status line) - never about every call. Most calls make no such claim, so the
    GPU cost is bounded by construction rather than by hope, and the
    premature-close risk is measured exactly where it lives.

    A call that changed a file is EXCLUDED: ``node_executor.py:629`` already
    forbids such a call from closing the step - the rule added 2026-10-02 after
    a small model set ``step_done`` on its own edit and the step closed with a
    buggy method nobody ran - so its claim is POLICY, not judgement (AC10.5).
    Asking d1 about it would teach a rule the system already enforces and make
    the measurement meaningless. Excluded rows are COUNTED, never dropped.
    """
    if batch_changed:
        return False
    return bool(claimed_step_done)


# ── REQ-6 AC6.3a (T5.0): the row SCOPE — turn_id / step_id / node_exec_id ──
# The join key was never missing from the turn (198 turn_id uses in
# agent_kernel; the gateway passes it at turn entry) - it simply never reached
# the row payload. The scope rides a contextvar set where the ids exist (turn
# entry for the loop task; node entry for the node thread) and is read AT
# ROW-BUILD / SUBMIT TIME as VALUES: a shadow lane scores later on a worker
# thread whose context says nothing. `job_input()` never sees it - the state
# is the model's input recipe and a scope id is not an input.
_SCOPE: "contextvars.ContextVar" = contextvars.ContextVar(
    "oracle_scope", default=None)

_SCOPE_KEYS = ("turn_id", "step_id", "node_exec_id")


def set_scope(**ids) -> "contextvars.Token":
    """Bind the current scope (a contextvar; per task/thread).

    MERGES into the existing scope: a step bind must never wipe the turn bind.
    Measured live 2026-10-17: every depth_met row carried step_id but NO
    turn_id - the review site's step bind had REPLACED the turn-entry bind, so
    no turn-level join (the external verdict label, the sampled-row outcome
    join) could ever fire for anything scored after it. An explicit None (or
    empty string) CLEARS its key, so turn entry resets the previous turn's
    ids: ``set_scope(turn_id=t, step_id=None, node_exec_id=None)``.
    """
    merged = dict(_SCOPE.get() or {})
    for k, v in ids.items():
        if v is None or str(v) == "":
            merged.pop(k, None)
        else:
            merged[k] = str(v)
    return _SCOPE.set(merged)


def scope_now() -> Dict[str, str]:
    """The current scope as plain VALUES ({} when unset) - safe to bind into
    a deferred closure; a lane thread's own context is never read."""
    s = _SCOPE.get()
    return {k: v for k, v in (s or {}).items() if k in _SCOPE_KEYS and v}


# ── REQ-10/REQ-14 (T5.7/T5.12): the deferred OUTCOME label ──────────────────
# A deferred row is SCORED first (on the ``oracle_shadow`` lane, AC10.6) and
# REGISTERED pending; its label arrives when its scope closes - one loop
# iteration later for a closing claim (AC10.4) - and only then is it WRITTEN.
# A batch is a transport unit, never a LABEL unit (AC14.1): every row keeps
# its own scope key (turn_id, step_id, node_exec_id, call_ordinal), resolves
# at its own time, carries its own label.
OUTCOME_CORRECT = "correct"
OUTCOME_PREMATURE = "premature"
OUTCOME_UNTESTED = "untested"
OUTCOME_ABANDONED = "abandoned"

_PENDING_LOCK = threading.Lock()
# node_exec_id -> {ordinal: {"scope": dict, "row": Optional[dict],
#                            "label": Optional[str]}}
_PENDING: "OrderedDict[str, Dict[int, dict]]" = OrderedDict()
_PENDING_NODE_CAP = 512  # node executions held at once; drop-oldest counts
_PENDING_DROPPED = 0     # cap overflows (counted, AC14.4)
_PENDING_UNSCORED = 0    # resolved but never scored (engine away; counted)


def deferred_counters() -> Dict[str, int]:
    """The pending-registry counters (AC14.4: counted, never silent)."""
    with _PENDING_LOCK:
        return {
            "pending_nodes": len(_PENDING),
            "pending_rows": sum(len(v) for v in _PENDING.values()),
            "dropped_overflow": _PENDING_DROPPED,
            "unscored_dropped": _PENDING_UNSCORED,
        }


def _emit_outcome_row(scope: Dict[str, str], row: Dict[str, Any],
                      label: str) -> None:
    """Stamp the resolved label and hand the row to the installed sink.

    AC14.2 shape: ``outcome_label`` always; ``label_source = "outcome"`` (the
    report's split metric, T5.10); `outside_label` carries the CLAIM'S truth
    ("yes"/"no" for a closing claim) so `decision_label`'s name-comparison
    judges the engine's answer against reality - not against itself.
    "untested"/"abandoned" leave it ABSENT, so the fit excludes the row and
    counts it instead of scoring it (a PENDING row counted as a negative
    would be a fabricated observation, AC14.4).
    """
    out = dict(row)
    out.update(scope)
    out["outcome_label"] = label
    out["label_source"] = "outcome"
    if label == OUTCOME_CORRECT:
        out["outside_label"] = "yes"
    elif label == OUTCOME_PREMATURE:
        out["outside_label"] = "no"
    sink = _OUTCOME_SINK
    if callable(sink):
        try:
            sink(out)
        except Exception as e:  # noqa: BLE001 - an observer never blocks
            logger.debug("decision_engine: outcome sink failed (%r)", e)
    else:
        logger.info(
            "decision_engine: outcome row consumer=%s label=%s (no sink)",
            out.get("consumer_id"), label)


_OUTCOME_SINK: Optional[Callable[[dict], None]] = None


def set_outcome_sink(sink: Optional[Callable[[dict], None]]) -> None:
    """Install the process-wide sink for resolved outcome rows (the kernel's
    single-writer shadow sink). None = log only, never silently dropped."""
    global _OUTCOME_SINK
    _OUTCOME_SINK = sink


def _register_close_claim(node_exec_id: str, ordinal: int,
                          scope: Dict[str, str]) -> None:
    global _PENDING_DROPPED
    with _PENDING_LOCK:
        node = _PENDING.setdefault(node_exec_id, OrderedDict())
        _PENDING.move_to_end(node_exec_id)
        node[ordinal] = {"scope": dict(scope), "row": None, "label": None}
        while len(_PENDING) > _PENDING_NODE_CAP:
            _PENDING.popitem(last=False)
            _PENDING_DROPPED += 1


def _attach_close_score(node_exec_id: str, ordinal: int,
                        row: Optional[Dict[str, Any]]) -> None:
    """The lane's score lands. If the claim is already labelled, emit now."""
    global _PENDING_UNSCORED
    if not row:
        with _PENDING_LOCK:
            node = _PENDING.get(node_exec_id) or {}
            ent = node.get(ordinal)
            labelled = bool(ent and ent.get("label"))
        if labelled:
            # Resolved BEFORE the engine answered (engine unavailable / lane
            # dropped the job): the label exists but there is no score to
            # carry it - dropped and COUNTED, never fabricated (AC14.4).
            with _PENDING_LOCK:
                _PENDING_UNSCORED += 1
                node = _PENDING.get(node_exec_id)
                if node is not None:
                    node.pop(ordinal, None)
                    if not node:
                        _PENDING.pop(node_exec_id, None)
        return
    with _PENDING_LOCK:
        node = _PENDING.get(node_exec_id)
        ent = node.get(ordinal) if node is not None else None
        if ent is None:
            return
        ent["row"] = row
        label = ent.get("label")
        scope = dict(ent["scope"])
        if label:
            node.pop(ordinal, None)
            if not node:
                _PENDING.pop(node_exec_id, None)
    if label:
        _emit_outcome_row(scope, row, label)


def resolve_pending(node_exec_id: str, label: str) -> int:
    """Label every still-pending claim of one node execution (AC14.2).

    Emits at once where the score already landed; entries awaiting a score
    stay pending and emit from the lane when it arrives. Idempotent: calling
    twice resolves nothing the second time. Returns how many claims this call
    labelled (fixture harness asserts on it, AC14.6).
    """
    with _PENDING_LOCK:
        node = _PENDING.get(node_exec_id)
        if not node:
            return 0
        ready = []
        waiting = 0
        for ordinal, ent in node.items():
            if ent.get("label"):
                continue
            ent["label"] = label
            if ent.get("row") is not None:
                ready.append((ordinal, dict(ent["scope"]), ent["row"]))
            else:
                waiting += 1
        for ordinal, _scope, _row in ready:
            node.pop(ordinal, None)
        if not node:
            _PENDING.pop(node_exec_id, None)
        n = len(ready) + waiting
    for _ordinal, _scope, _row in ready:
        _emit_outcome_row(_scope, _row, label)
    return n


def sweep_turn_pending(turn_id: str) -> int:
    """AC14.4: mark this turn's still-pending claims ABANDONED at turn end -
    a distinct, counted value, never a fabricated negative."""
    if not turn_id:
        return 0
    abandoned = 0
    with _PENDING_LOCK:
        hits = [
            (nid, dict(node)) for nid, node in _PENDING.items()
            if any(str(e.get("scope", {}).get("turn_id") or "") == str(turn_id)
                   for e in node.values())
        ]
    for nid, node in hits:
        if node:
            abandoned += resolve_pending(nid, OUTCOME_ABANDONED)
    return abandoned


class CloseClaimProbe:
    """REQ-10: the node loop's closing-claim measurement hook.

    MEASUREMENT-ONLY, permanently - the consumer is tier C
    (``REFUSED_CONSUMERS``): the score is never read back into the loop, which
    is why ``node_executor`` only ever TOUCHES this probe and never reads from
    it. The kernel installs it on ``NodeContext``; the loop only RECORDS claims
    and REPORTS its own exits, and the label IS the exit (AC10.4/AC14.2).
    """

    def __init__(self, *, turn_id: str = "", step_id: str = "",
                 node_exec_id: str = "", goal: str = "") -> None:
        self._scope = {
            "consumer_id": CALL_CLOSING_CONSUMER,
            "turn_id": str(turn_id or ""),
            "step_id": str(step_id or ""),
            "node_exec_id": str(node_exec_id or ""),
        }
        self._node_exec_id = self._scope["node_exec_id"]
        self._goal = str(goal or "")

    def supersede_prior(self, prior_exec_id: str) -> None:
        """AC14.3: a retried step's earlier execution NEVER adjudicated its
        claims - the final execution is the truth, so the superseded one's
        rows are UNTESTED (and counted)."""
        if prior_exec_id and prior_exec_id != self._node_exec_id:
            resolve_pending(prior_exec_id, OUTCOME_UNTESTED)

    def claimed(self, call_ordinal: int, call_desc: str, result_excerpt: str,
                *, file_changed: bool) -> None:
        """AC10.2/AC10.5: only candidate closings are asked, and a file-
        changing call is never a candidate (excluded rows are counted).
        Never raises; the reply path never waits (AC10.6)."""
        global _CALL_CLOSING_EXCLUDED
        try:
            if not call_closing_is_candidate(
                    claimed_step_done=True, batch_changed=file_changed):
                _CALL_CLOSING_EXCLUDED += 1
                return
            ordinal = int(call_ordinal)
            _register_close_claim(
                self._node_exec_id, ordinal,
                {**self._scope, "call_ordinal": ordinal})
            engine = get_decision_engine()
            if engine is None:
                return  # row registered; it will count as unscored at sweep
            frame = {
                # the judge_call job fields - the question's three subjects
                # (AC10.3): the goal, the call, the call's result.
                "goal": self._goal[:400],
                "call": str(call_desc)[:200],
                "result": str(result_excerpt)[:400],
            }
            try:
                register_declared(
                    CALL_CLOSING_CONSUMER,
                    "Is this call the closing call of this step?",
                    ("yes", "no"),
                )
            except Exception:  # noqa: BLE001 - registration is best-effort
                pass

            def _attach(row: Optional[Dict[str, Any]],
                        _nid=self._node_exec_id, _ord=ordinal) -> None:
                _attach_close_score(_nid, _ord, row)

            engine.shadow(CALL_CLOSING_CONSUMER, ["yes", "no"], frame,
                          sink=_attach)
        except Exception as e:  # noqa: BLE001 - a shadow never raises
            logger.debug("decision_engine: close-claim consult failed (%r)", e)

    def resolve(self, label: str) -> int:
        """Report THIS execution's exit label - the loop's only contact with
        the measurement, and it is one-directional (never reads back)."""
        try:
            return resolve_pending(self._node_exec_id, label)
        except Exception:  # noqa: BLE001
            return 0


_CALL_CLOSING_EXCLUDED = 0


def call_closing_counters() -> Dict[str, int]:
    """The candidate-gate counter (AC10.5: excluded rows are counted)."""
    return {"excluded_changed_file": _CALL_CLOSING_EXCLUDED}


# ── REQ-6 (T5.1-T5.4): the SAMPLED rung ─────────────────────────────────────
# shadow measures agreement; enforced requires the full bar; nothing in
# between can EVER produce evidence that d1 is better than the incumbent
# (oracle.md S0.7 - the label ceiling). The missing rung DECIDES on a bounded
# fraction, and the row is labelled by the turn's OUTCOME (AC6.3), never by
# the incumbent.
#
# AC6.6 two gates, both must pass, NO defaults (AC6.6b):
#   Gate 1 REVERSIBILITY: a wrong answer must be cheap and reversible.
#   Gate 2 GROUND TRUTH: an outcome signal must exist to label the row.
# The tier table is the structural admission; `call_closing` is tier C
# (REFUSED, never sampleable); done/sufficient/depth_met/tool_choice are
# JOIN-only (labelled by outcome, never sampled); consumers with no ground
# truth are observation-only (mode/narration/presentation/event_*).
# tool_choice JOINS the samplable tier (owner, 2026-10-11: "the Oracle decides
# all tools if capable - find out how"). Gate 1: a sampled pick only NARROWS the
# tool model's menu to one tool - the model still writes the arguments, may
# finish instead of calling, and the next pick sees the FAILED result in the
# step's own history. Gate 2: the call's outcome (ok / FAILED) labels the row.
# Parity could never show capability: three valid tools (read_file /
# list_directory / glob_files) score two of them "wrong" (replay 2026-10-11:
# 57.8% agreement with the decision lines).
TIER_SAMPLABLE: frozenset = frozenset({
    "needs_action", "recovery_strategy", "escalate_incomplete", "tool_choice",
})
# AC6.6: refuse-direction ONLY - sampled, but the engine may only ever tighten
# (refuse/veto where the incumbent allowed), never loosen. Wired at the
# incumbent's own refuse junction.
TIER_REFUSE_ONLY: frozenset = frozenset({
    "click_safety", "review_verdict",
    # tool_approval (2026-10-18): the pre-call guard may only REJECT a call
    # the model was allowed to make - it never forces one, and its correction
    # budget (_MAX_GUARD_CORRECTIONS) bounds it so it can never deadlock.
    "tool_approval",
})
TIER_JOIN_ONLY: frozenset = frozenset({
    "done", "sufficient", "depth_met",
})

# AC6.4: the fraction is a NAMED CONSTANT with a stated default and a kill
# switch. It is never raised on a measurement that lacks outcome labels - the
# report's label-width per consumer (label_source == "outcome") is the
# evidence any raise must show.
SAMPLE_FRACTION = 0.05
_SAMPLE_KILL = "IRIS_ORACLE_SAMPLE"        # "0" kills sampling outright
_SAMPLE_FRACTION_ENV = "IRIS_ORACLE_SAMPLE_FRACTION"


def sampled_consult_ok(consumer_id: str, scope_key: str) -> bool:
    """AC6.2: may this consumer's answer substitute for the incumbent on THIS
    consult? Bounded (a deterministic hash of the consult's scope against
    SAMPLE_FRACTION), reversible-gated (the tier table), kill-switched, and
    never available to a REFUSED or untiered consumer. Deterministic per
    scope: the same consult re-asked answers the same way, so retries do not
    double-sample."""
    if consumer_id in REFUSED_CONSUMERS or consumer_id not in (
            TIER_SAMPLABLE | TIER_REFUSE_ONLY):
        return False
    if os.environ.get(_SAMPLE_KILL, "1") == "0":
        return False
    # Per-consumer override first (IRIS_ORACLE_SAMPLE_FRACTION_TOOL_CHOICE=1
    # runs the tool A/B at 100% while every other consumer keeps its share).
    _per = os.environ.get(f"{_SAMPLE_FRACTION_ENV}_{consumer_id.upper()}")
    try:
        frac = float(_per if _per is not None
                     else os.environ.get(_SAMPLE_FRACTION_ENV, SAMPLE_FRACTION))
    except (TypeError, ValueError):
        frac = SAMPLE_FRACTION
    frac = min(1.0, max(0.0, frac))
    if frac <= 0.0:
        return False
    import hashlib

    digest = hashlib.sha256(
        f"{consumer_id}|{scope_key}".encode("utf-8")).digest()
    return (int.from_bytes(digest[:8], "big") / float(2 ** 64)) < frac


# Turn-scoped outcome join (AC6.3/AC6.3b): a sampled row knows its SCORE at
# consult time; its LABEL arrives at turn end, joined on turn_id from the
# signals turn end already computes (DER_DAG S6 - run grade / task done /
# contract met). Adjudicated values: "turn_ok" / "turn_fail"; the
# label-integrity metric counts BOTH as adjudicated (only UNTESTED and
# abandoned are non-adjudicated - AC14.5).
OUTCOME_TURN_OK = "turn_ok"
OUTCOME_TURN_FAIL = "turn_fail"

_TURN_PENDING: "OrderedDict[str, Dict[str, dict]]" = OrderedDict()
_TURN_PENDING_CAP = 256  # turns held at once


def register_turn_pending(scope: Dict[str, str], row: Dict[str, Any]) -> None:
    """A sampled consult's row, awaiting its turn outcome. Bounded; the
    oldest turn is dropped (counted by the sweep at ITS end - a dropped turn
    is exactly a turn that never resolved)."""
    tid = str(scope.get("turn_id") or "")
    if not tid:
        return
    with _PENDING_LOCK:
        turns = _TURN_PENDING
        turns.setdefault(tid, {})[id(row)] = {"scope": dict(scope), "row": dict(row)}
        turns.move_to_end(tid)
        while len(turns) > _TURN_PENDING_CAP:
            turns.popitem(last=False)


def resolve_turn_pending(turn_id: str, ok: bool) -> int:
    """AC6.3: label this turn's sampled rows by the turn's OUTCOME and emit
    them (join on turn_id). Returns the count labelled."""
    tid = str(turn_id or "")
    if not tid:
        return 0
    with _PENDING_LOCK:
        rows = _TURN_PENDING.pop(tid, None) or {}
        entries = list(rows.values())
    label = OUTCOME_TURN_OK if ok else OUTCOME_TURN_FAIL
    for ent in entries:
        row = dict(ent["row"])
        row.update(ent["scope"])
        row["outcome_label"] = label
        row["label_source"] = "outcome"
        # AC6.3: the label is the TURN'S outcome. It only joins a NAMED or
        # BOOL decision when the comparison is meaningful: a noul row's
        # chosen is a bool, so "turn_ok" maps to "the engine's answer was
        # borne out"; a choice row's answer is a NAME with no boolean reading,
        # so it carries the outcome_label alone (counted by the integrity
        # metric, never rank-scored against an incommensurable reference).
        if isinstance(row.get("chosen"), bool):
            row["outside_label"] = bool(ok)
        _emit_outcome_row({}, row, label)
    return len(entries)


def sampled_row(consumer_id: str, chosen: Any, confidence: float,
                **extra) -> Dict[str, Any]:
    """The ONE row shape of a sampled consult (AC6.3): the engine's answer,
    its confidence, route="sampled" (the ledger marks incumbent-labelled rows
    as shadow) - labelled by the turn outcome via ``register_turn_pending``,
    never by the incumbent."""
    row: Dict[str, Any] = {
        "consumer_id": consumer_id,
        "engine": str(getattr(get_decision_engine(), "model_id", "") or ""),
        "job": oracle_job(consumer_id).name,
        "chosen": chosen,
        "confidence": round(float(confidence), 4),
        "route": "sampled",
    }
    row.update(extra)
    return row



def decides(consumer_id: str) -> Optional[float]:
    """THE chokepoint: the calibrated threshold when *consumer_id* may decide.

    ALL four hold, else None: the owner switched it on, its bar record says
    ``enforced`` on the active engine, a threshold was fitted for it on that
    engine, and the configuration is not stale. With the default configuration
    NOTHING decides. A site that gets None keeps its rule / Brain path. Never
    raises (a fault is "does not decide").

    REQ-10 AC10.0 fence 1: a REFUSED consumer never decides, whatever the
    owner's switch or the bar record says. This is a refusal, not a default.
    """
    if consumer_id in REFUSED_CONSUMERS:
        return None
    try:
        _log_enforcement_once()
        return _enforcement(consumer_id)[0]
    except Exception as e:  # noqa: BLE001 - fail closed
        logger.debug("decision_engine: decides(%s) failed (%r)", consumer_id, e)
        return None


def oracle_acts(consumer_id: str, raw_conf: float) -> bool:
    """True when the Oracle's verdict replaces the incumbent for THIS decision.

    ``raw_conf`` is the confidence in the CHOSEN answer (max(p, 1-p) for a
    yes/no), the number a ledger row carries - the calibration map was fitted on
    that scale. Below the calibrated threshold the existing path decides.
    """
    try:
        t = decides(consumer_id)
        if t is None:
            return False
        from . import oracle_calibration

        c = oracle_calibration.calibrated(
            _current_backend_identity(consumer_id), consumer_id, raw_conf)
        return c is not None and c >= t
    except Exception as e:  # noqa: BLE001 - fail closed
        logger.debug("decision_engine: oracle_acts(%s) failed (%r)", consumer_id, e)
        return False


def enforced_consumers() -> frozenset:
    """The consumers that currently decide: the INTERSECTION of the owner's
    switch and the earned bar (``decides`` is not None). Never a union - a bar
    record alone, or the owner's list alone, enforces nothing."""
    return frozenset(c for c in _owner_allow_list() if decides(c) is not None)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@dataclass
class EngineConfig:
    model_dir: Optional[str] = None      # explicit ONNX model dir wins
    max_args_tokens: int = 192
    acquire_timeout_s: float = 2.0
    # The ACTIVE backend's bare MODEL id (AC25.8). Set from the loaded backend
    # at load time; `threshold_for` composes the full decision identity
    # (model|readout_mode|criteria_hash, REQ-2 AC2.1) around it.
    backend_id: Optional[str] = None
    # THRESHOLDS ARE KEYED BY DECISION IDENTITY (REQ-22 AC22.1, REQ-25 AC25.8,
    # REQ-2 AC2.1: `model_id|readout_mode|criteria_hash`).
    # A probability threshold is only meaningful for the distribution it was
    # measured on: 0.85 suits LFM's sharpened softmax, 0.40 suits GLiNER's
    # menu-wide softmax. Keyed by the full identity, a model swap, a READOUT
    # change or a CRITERIA edit degrades to SHADOW (no entry for the new
    # identity = fail-closed) instead of silently enforcing on a curve
    # measured under a different input shape.
    backend_thresholds: Dict[str, float] = None  # set in __post_init__ below
    # Per-consumer thresholds (REQ-13): tools that execute external side effects
    # sit higher than display gates; calm narration anti-spamming sits lower.
    # Ordered: explicit per-consumer → decision-identity threshold (AC2.1).
    thresholds: Dict[str, float] = None  # set in __post_init__ below
    # Bounded cost per decision. Ships at CANDIDATE_CAP_DEFAULT (11, raised
    # from 6 on 2026-09/10-2026 — see that constant for the measurement that
    # forced it: at 6 only FOUR real tools reached the model and write_file
    # was unreachable). Changing it marks the calibrated threshold STALE
    # (AC25.5), which is the correct outcome: the curve was derived at the old
    # width and says nothing about this one.
    candidate_cap: int = CANDIDATE_CAP_DEFAULT
    # The menu width the current threshold curve was derived at (AC25.7).
    # A candidate_cap that differs from this marks the threshold STALE
    # (AC25.5): enforcement is refused until the curve is re-derived.
    # Left at 6 deliberately — that is the width the fitted curve was measured
    # at, so the mismatch with candidate_cap is what keeps enforcement refused.
    # 6 -> 32 (2026-10-11): the FIRST curve fitted on d1 (tool_choice,
    # tc-decide-v3, outcome-labelled, 388 distinct rows) was measured at menu
    # width 32 - every one of those rows ran after the cap moved to 32. A
    # different deployed width is still stale (and re-identifies via
    # criteria_hash).
    calibrated_cap: int = 32

    def __post_init__(self) -> None:
        if self.backend_thresholds is None:
            self.backend_thresholds = {}
        if self.thresholds is None:
            self.thresholds = {}

    def threshold_stale(self) -> bool:
        """AC25.5: True when the deployed cap differs from the calibrated
        width — the threshold is stale and enforcement is refused until the
        curve is re-derived (REQ-31 AC31.4)."""
        return self.candidate_cap != self.calibrated_cap

    def threshold_for(self, consumer_id: str) -> Optional[float]:
        """Threshold for one consumer, keyed by the ACTIVE DECISION IDENTITY.

        Resolution (AC22.1/AC25.8, REQ-2 AC2.1): explicit per-consumer override
        → the active decision identity's ``backend_thresholds`` entry. Returns
        None when the active identity has no entry, or when the deployed cap
        differs from the calibrated width (AC25.5 stale → fail-closed) — callers
        REFUSE ENFORCEMENT: the consumer stays shadow rather than enforcing on an
        unknown curve.

        The key is `model|readout_mode|criteria_hash` (AC2.1), so a READOUT
        change or a CRITERIA edit empties the map instead of silently reusing a
        curve measured on a different input shape (AC2.2/AC2.4).
        """
        if consumer_id in REFUSED_CONSUMERS:
            return None  # AC6.6 tier C: never resolved to a threshold
        if self.threshold_stale():
            return None
        if consumer_id in (self.thresholds or {}):
            return float(self.thresholds[consumer_id])
        bt = self.backend_thresholds or {}
        # AC2.1: the key is the FULL DECISION identity for THIS consumer.
        # `self.backend_id` is the bare MODEL id (the row's `engine` field),
        # set from the loaded backend at load time; the readout and the
        # consumer's criteria hash complete it here. With no declared backend
        # on the config, fall back to the process-wide resolver.
        if self.backend_id:
            key = decision_identity(
                str(self.backend_id), CURRENT_READOUT_MODE, consumer_id,
                self.candidate_cap)
        else:
            key = _current_backend_identity(consumer_id, self.candidate_cap)
        if key and key in bt:
            return float(bt[key])
        # The fitted curve for this identity (fit_oracle_calibration.py),
        # converted to the RAW scale its callers compare a raw confidence on.
        if key:
            from backend.agent import oracle_calibration
            return oracle_calibration.raw_threshold(key, consumer_id)
        return None


# ---------------------------------------------------------------------------
# Config authority (REQ-25): the oracle block parsed into EngineConfig
# ---------------------------------------------------------------------------

_DEFAULT_CONFIG_PATH = "./backend/agent/agent_config.yaml"
_config_fallback_logged = False


def _log_config_fallback(why: str) -> None:
    global _config_fallback_logged
    if not _config_fallback_logged:
        _config_fallback_logged = True
        logger.warning(
            "oracle config fallback (%s) — code defaults apply", why
        )


def load_engine_config(
    config_path: str = _DEFAULT_CONFIG_PATH,
) -> EngineConfig:
    """Parse the ``oracle`` block into EngineConfig (REQ-25 AC25.1).

    Every documented key is parsed or removed (AC25.6). A missing or malformed
    key falls back to the code default and logs the fallback ONCE (AC25.3) —
    never crashes, never silently accepts a partial config. The block is
    located by id, not by position. Never raises.
    """
    global _config_fallback_logged
    cfg = EngineConfig()
    try:
        import yaml  # lazy — config parsing is not on the decision hot path

        p = Path(config_path)
        if not p.is_file():
            if config_path == _DEFAULT_CONFIG_PATH:
                # The default path is CWD-relative; try the module-relative
                # location before giving up (robustness, not substitution).
                p = Path(__file__).resolve().parent / "agent_config.yaml"
            if not p.is_file():
                _log_config_fallback("config file not found")
                return cfg
        with open(p, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        block = None
        for m in data.get("models", []) or []:
            if isinstance(m, dict) and m.get("id") == "oracle":
                block = m
                break
        if block is None:
            _log_config_fallback("oracle block not found")
            return cfg
        constraints = block.get("constraints")
        if not isinstance(constraints, dict):
            _log_config_fallback("constraints malformed")
            constraints = {}
        path = block.get("path")
        if path:
            cfg.model_dir = str(path)
        cap = constraints.get("candidate_cap")
        if isinstance(cap, int) and not isinstance(cap, bool) and cap > 0:
            cfg.candidate_cap = cap
        elif cap is not None:
            _log_config_fallback(f"candidate_cap malformed: {cap!r}")
        ato = constraints.get("acquire_timeout_s")
        if isinstance(ato, (int, float)) and not isinstance(ato, bool) and ato > 0:
            cfg.acquire_timeout_s = float(ato)
        elif ato is not None:
            _log_config_fallback(f"acquire_timeout_s malformed: {ato!r}")
        bt = constraints.get("backend_thresholds")
        if isinstance(bt, dict) and all(
            isinstance(v, (int, float)) and not isinstance(v, bool)
            for v in bt.values()
        ):
            cfg.backend_thresholds = {str(k): float(v) for k, v in bt.items()}
        elif bt is not None:
            _log_config_fallback("backend_thresholds malformed")
        th = constraints.get("thresholds")
        if isinstance(th, dict) and all(
            isinstance(v, (int, float)) and not isinstance(v, bool)
            for v in th.values()
        ):
            cfg.thresholds = {str(k): float(v) for k, v in th.items()}
        elif th is not None:
            _log_config_fallback("thresholds malformed")
        return cfg
    except Exception as e:
        _log_config_fallback(f"parse failed: {e!r}")
        return cfg


# ---------------------------------------------------------------------------
# The engine
# ---------------------------------------------------------------------------


# AC30.5 (T42): the name every dedicated-inference worker carries. The engine
# detects "already on the inference thread" by this prefix, so it must stay in
# sync with the pool's `thread_name_prefix`.
_INFER_THREAD_PREFIX = "iris-decision-inference"

# ---------------------------------------------------------------------------
# Oracle phase participation (flag IRIS_ORACLE_PHASE, default OFF)
# ---------------------------------------------------------------------------
# Spec: specs/oracle-phase-concurrency. Design: docs/architecture/PHASE_DOMAINS.md.
# With the flag on, `decide` takes NO engine lock: it passes the Oracle's own
# phase domain (a participant per "{session}:{consumer_id}", priority classes
# bypass, fail-open) and then runs its own single-question session run, several
# at once on the one loaded session (`InferenceSession.run` is thread-safe).
# NOTHING shares a pass between questions (oracle.md S9). The resource enters the
# domain only as a LOAD parameter - runs in flight over the CPU's run capacity
# (logical cores / intra-op threads) - never as a cap or a semaphore.
ORACLE_PHASE_DOMAIN = "decision.oracle_cpu"
# Upper bound on how long shutdown waits for in-flight runs before it swaps the
# backend anyway (a stuck ORT run must not hang process teardown).
_SHUTDOWN_DRAIN_S = 30.0
_ORACLE_RUNS_LOCK = threading.Lock()
# REQ-7 AC7.3 (Wave 6): counted as QUESTIONS, not runs - a batched run of n
# questions contributes n while it flies. (The name passed through unchanged
# below; the semantic is the load function's.)
_oracle_questions_in_flight = 0  # questions executing now, process-wide
_oracle_intra_op = 0         # the loaded session's intra-op thread count


def _oracle_phase_enabled() -> bool:
    return os.environ.get("IRIS_ORACLE_PHASE", "").strip().lower() in (
        "1", "true", "on", "yes",
    )


def _env_float(name: str, default: float) -> float:
    try:
        v = os.environ.get(name)
        return float(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def _oracle_load_fraction() -> float:
    """Load fed to the Oracle's phase domain: QUESTIONS in flight / capacity.

    REQ-7 AC7.3 (Wave 6): the signal counts QUESTIONS, not runs. A three-
    question batch occupies three times the work for ONE admission; counting
    questions keeps admission fair by the work performed ("a three-consumer
    job is admitted a third as often"). Capacity = logical cores / intra-op
    threads per run (8 / 4 = 2 here). It is a PARAMETER of the mechanism
    (it slows the cadence through the amplitude), never a ceiling.
    """
    cores = os.cpu_count() or 1
    intra = _oracle_intra_op or max(1, cores // 2)
    return min(1.0, _oracle_questions_in_flight / max(1, cores // max(1, intra)))


def _oracle_domain() -> Any:
    from backend.agent.phase_domain import get_phase_domain

    return get_phase_domain(
        ORACLE_PHASE_DOMAIN,
        # Sized to the measured Oracle decision (benchmarks/oracle_phase_classical.json:
        # p50 138 ms alone): a participant is due again half a period after it
        # fires, so 0.3 s -> ~150 ms, about one decision.
        period_s=_env_float("IRIS_ORACLE_PHASE_PERIOD_S", 0.3),
        max_wait_s=_env_float("IRIS_ORACLE_PHASE_MAX_WAIT_S", 0.3),
        k=_env_float("IRIS_ORACLE_PHASE_K", 0.6),
        load_fn=_oracle_load_fraction,
        # Exit-driven admission (IRIS_ORACLE_PHASE_EXIT): a run slot frees when
        # a decision is DONE; the slot count is the CPU's own run capacity.
        capacity_fn=_oracle_run_capacity if _oracle_phase_exit_enabled() else None,
    )


def _oracle_phase_exit_enabled() -> bool:
    return os.environ.get("IRIS_ORACLE_PHASE_EXIT", "").strip().lower() in (
        "1", "true", "on", "yes",
    )


def _oracle_run_capacity() -> int:
    """Runs the CPU hosts without sharing cores: logical cores / intra-op threads
    (8 / 4 = 2 here) - the same number _oracle_load_fraction divides by."""
    cores = os.cpu_count() or 1
    intra = _oracle_intra_op or max(1, cores // 2)
    return max(1, cores // max(1, intra))


def _oracle_session_id() -> str:
    """The caller's session id when one is set, else ``default``.

    Read from the correlation ContextVar only if that module is already loaded -
    the engine never imports it (heavy), and `decide` takes no session argument.
    """
    mod = sys.modules.get("backend.monitoring.session_correlation")
    try:
        sid = mod._current_session_id.get() if mod is not None else None
    except Exception:  # noqa: BLE001
        sid = None
    return sid or "default"


class DecisionEngine:
    """One serialized ONNX scoring backend. CPU only. Lazy load. Never raises."""

    def __init__(
        self,
        config: Optional[EngineConfig] = None,
        backend_factory: Optional[Callable[..., Any]] = None,  # test seam
        llama_factory: Optional[Callable[..., Any]] = None,    # args test seam
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self._cfg = config or EngineConfig()
        self._backend_factory = backend_factory
        self._llama_factory = llama_factory
        self._clock = clock
        self._lock = threading.Lock()
        # AC30.5 (T42): ONE dedicated inference thread. Step execution already
        # runs on a shared pool (`agent_kernel.py:9421`, `:15690`); letting
        # each of those threads drive ONNX directly made the engine's intra-op
        # threads contend with step scheduling and oversubscribed the CPU when
        # several steps resolved at once. Lazily created, so an engine that
        # never scores pays nothing.
        self._infer_pool: Any = None
        self._infer_pool_lock = threading.Lock()
        # Phase path (IRIS_ORACLE_PHASE) shared state, each guarded by its own
        # SMALL lock: counters; the one-time lazy load; and the run gate that
        # keeps load/unload from racing an in-flight run (a refcount, not a cap).
        self._counter_lock = threading.Lock()
        self._load_lock = threading.Lock()
        self._run_cv = threading.Condition()
        self._runs = 0
        self._closing = False
        # The ONNX scoring backend (lazy; the only scorer — no fallback model).
        self._backend: Any = None
        # Generative args model. Test seam ONLY: production injects no factory
        # (the ONNX backend scores labels, it does not generate arguments),
        # so this stays None and generate_args degrades (AC2.4 escalates).
        self._llm: Any = None
        self._load_attempted = False
        self._notice_logged = False
        self.counters = EngineCounters()
        self.model_id: Optional[str] = None

    # -- dedicated inference thread (AC30.5 / T42) -------------------------

    def _get_infer_pool(self) -> Any:
        """The single-worker pool that owns model inference, or None.

        Created once, lazily. Returns None when the pool cannot be built, so
        the caller can fall back to an inline call rather than lose a decision.
        Never raises.
        """
        if self._infer_pool is not None:
            return self._infer_pool
        with self._infer_pool_lock:
            if self._infer_pool is None:
                try:
                    from concurrent.futures import ThreadPoolExecutor

                    self._infer_pool = ThreadPoolExecutor(
                        max_workers=1,
                        thread_name_prefix=_INFER_THREAD_PREFIX,
                    )
                except Exception as e:  # noqa: BLE001 — plumbing, not the work
                    logger.debug(
                        "decision_engine: inference pool unavailable (%r)", e
                    )
                    return None
        return self._infer_pool

    def _run_inference(self, fn: Callable[[], Any], concurrent: bool = False) -> Any:
        """AC30.5 (T42): run backend inference on the dedicated engine thread.

        Serialises the model work (which the engine lock already did) while
        keeping ONNX's intra-op threads off the step scheduler's CPU budget and
        out of a step thread's stack.

        Degradation is deliberate and total: an unusable pool runs the work
        inline (today's behaviour), while a pool that accepted the work but
        overran its budget returns None — the same "no verdict, use the legacy
        path" contract every other engine failure uses (AC26.1). The work is
        NEVER retried after submission, because a retry would score twice.
        Runs inline when already on the inference thread, so a nested call
        cannot deadlock. Never raises.

        ``concurrent=True`` (phase path) gives THIS run its own inference thread
        instead of the single-worker pool, so runs overlap; the thread is named
        with the same prefix, so inference still never runs on a step thread.
        """
        if threading.current_thread().name.startswith(_INFER_THREAD_PREFIX):
            return fn()
        pool = None
        submitted = None
        if concurrent:
            from concurrent.futures import Future

            submitted = Future()

            def _work() -> None:
                try:
                    submitted.set_result(fn())
                except BaseException as exc:  # noqa: BLE001 — handed to the waiter
                    submitted.set_exception(exc)

            try:
                threading.Thread(
                    target=_work, name=f"{_INFER_THREAD_PREFIX}-run", daemon=True
                ).start()
            except Exception:  # noqa: BLE001 — cannot spawn: run inline, never lose it
                return fn()
        else:
            pool = self._get_infer_pool()
            if pool is None:
                return fn()
        try:
            if submitted is None:
                submitted = pool.submit(fn)
            return submitted.result(
                timeout=float(self._cfg.acquire_timeout_s) * 2.0 + 5.0
            )
        except Exception as e:  # noqa: BLE001 — never lose a decision to plumbing
            from concurrent.futures import TimeoutError as _FuturesTimeout

            if isinstance(e, _FuturesTimeout):
                with self._counter_lock:
                    self.counters.lock_timeouts += 1
                logger.warning(
                    "decision_engine: inference overran its budget on the "
                    "dedicated thread — returning no verdict"
                )
            else:
                logger.warning(
                    "decision_engine: inference on the dedicated thread "
                    "failed: %r", e,
                )
            return None

    # -- lifecycle ---------------------------------------------------------

    @property
    def loaded(self) -> bool:
        return self._backend is not None

    @property
    def model_hash(self) -> Optional[str]:
        """The deployed model file's sha256 (AC6.5/AC22.5 attribution) —
        delegated to the backend; None before load."""
        backend = self._backend
        if backend is None:
            return None
        return getattr(backend, "model_hash", None)

    def availability(self) -> Tuple[bool, str]:
        """(usable, reason). Never raises."""
        if self._backend is not None:
            return True, "loaded"
        if self._load_attempted:
            return False, "load_failed_or_missing"
        try:
            # Wave 5: the backend is d1 on the shared llama-server — its
            # availability is its own truthful check (borrow-only), not a
            # model_dir probe (the GLiNER path this replaced).
            from backend.agent.decision_backend_d1 import D1Backend

            ok, why = D1Backend().availability()
            return ok, why
        except Exception:
            pass
        return True, "loadable_pending"

    def _load(self) -> bool:
        """Load the ONNX scoring backend. Lazy, once. Never raises.

        Also creates the generative args model from an injected factory
        (test seam only — production has none).
        """
        if self._backend is not None:
            return True
        if self._load_attempted:
            return False
        self._load_attempted = True
        if self._llama_factory is not None and self._llm is None:
            try:
                self._llm = self._llama_factory()
            except Exception as e:
                self.counters.load_failures += 1
                self._log_unavailable(f"args model load failed: {e!r}")
        try:
            factory = self._backend_factory
            if factory is None:
                # Wave 3 (specs/phonon2-d1-model-swap T3.1): the resident
                # decision backend is d1-3B on the shared llama-server. The
                # GLiNER ONNX backend is RETIRED from construction (its code
                # and history stay until the T5.3 deletion; oracle.md §9 —
                # no fallback model: a d1 miss means unavailable, never a
                # silent GLiNER substitute).
                from backend.agent.decision_backend_d1 import D1Backend

                def factory(**kwargs: Any) -> Any:
                    return D1Backend(**kwargs)

            backend = factory(model_dir=self._cfg.model_dir)
            if backend is None or not backend.load():
                self._log_unavailable(
                    "decision backend unavailable (Wave 3: the shared server "
                    "must host the d1 GGUF) — no fallback model"
                )
                # BORROW-ONLY backends (d1) may become available later — the
                # shared server can host the model minutes after this miss
                # (found live 2026-10-08: the boot-time miss made the load
                # sticky and the Oracle scored nothing all session). A
                # backend that declares retry_load resets the stickiness so
                # the next decide() probes again; a file-based backend keeps
                # the old permanent-sticky behaviour.
                if backend is not None and getattr(backend, "retry_load", False):
                    self._load_attempted = False
                return False
            self._backend = backend
            # model_id FIRST: a backend may tag it with the readout (d1's
            # "+letters") so rows and thresholds address the distribution
            # they were measured on; backend_id is the bare variant fallback.
            self.model_id = getattr(backend, "model_id", None) or getattr(
                backend, "backend_id", None
            )
            self._cfg.backend_id = self.model_id  # AC25.8: active identity
            logger.info(
                "%s loaded backend=%s", ENGINE_NAME, self.model_id
            )
            return True
        except Exception as e:  # load failure must never escape (AC1.3)
            self._backend = None
            self.counters.load_failures += 1
            self._log_unavailable(f"backend load failed: {e!r}")
            return False

    def _log_unavailable(self, why: str) -> None:
        if not self._notice_logged:
            self._notice_logged = True
            self.counters.unavailable_events += 1
            logger.warning("decision_engine unavailable (%s) — using legacy path", why)

    @property
    def name(self) -> str:
        """The engine's DISPLAY name (telemetry, logs, UI).

        Deliberately separate from ``model_id``: this is a label, while
        ``model_id`` is the backend identity that KEYS the calibrated
        threshold. Renaming this changes nothing about enforcement.
        """
        return ENGINE_NAME

    def effective_config(self) -> Dict[str, Any]:
        """AC25.2: the effective configuration, observable.

        Returns the resolved engine config as a plain dict — backend identity
        included — so a config round-trip can prove a non-default value
        actually takes effect. Never raises.
        """
        return {
            "name": ENGINE_NAME,
            "model_dir": self._cfg.model_dir,
            "backend_id": self.model_id or self._cfg.backend_id,
            "candidate_cap": self._cfg.candidate_cap,
            "acquire_timeout_s": self._cfg.acquire_timeout_s,
            "backend_thresholds": dict(self._cfg.backend_thresholds or {}),
            "thresholds": dict(self._cfg.thresholds or {}),
        }

    def shutdown(self) -> None:
        """Free the backend. Idempotent. Called from the lifespan teardown."""
        with self._lock:
            # Phase path: never swap the backend under an in-flight run. New runs
            # wait at the gate (`_closing`); in-flight ones finish first. With
            # the flag off `_runs` is always 0, so this returns at once.
            with self._run_cv:
                self._closing = True
                if not self._run_cv.wait_for(
                    lambda: self._runs == 0, timeout=_SHUTDOWN_DRAIN_S
                ):
                    logger.warning(
                        "decision_engine: shutdown drain timed out with %d run(s) "
                        "in flight", self._runs,
                    )
                backend, self._backend = self._backend, None
                self._llm = None
                self._load_attempted = False
                self._closing = False
                self._run_cv.notify_all()
        # AC30.5 (T42): the dedicated inference thread is engine-owned, so it
        # must not outlive the engine.
        pool, self._infer_pool = self._infer_pool, None
        if pool is not None:
            try:
                pool.shutdown(wait=False)
            except Exception:
                pass
        if backend is not None:
            try:
                shutdown = getattr(backend, "shutdown", None)
                if callable(shutdown):
                    shutdown()
            except Exception:
                pass

    # -- scoring (Jev Choice over a caller-provided option set) ------------

    def decide(
        self,
        consumer_id: str,
        options: Sequence[str],
        frame: Dict[str, Any],
        instruction: Optional[str] = None,
    ) -> Optional[DecisionScore]:
        """Score every option in one schema pass; softmax; return winner +
        distribution.

        Returns None when the engine is unavailable, the lock times out, or
        scoring fails — callers treat None as "degrade to legacy path" (AC1.3,
        AC2.4). Never raises.
        """
        # The DECLARED-SET GATE is gone (2026-09-27). It refused every consumer
        # outside the frozen CONSUMERS tuple, which meant a new decision point
        # could not be measured at all until someone hand-wrote a ConsumerSpec
        # and edited that tuple - the ceremony the owner asked to remove. The
        # application should evolve with use.
        #
        # This is safe because REGISTERING IS NOT ENFORCING: the backend
        # auto-registers the consumer's criteria with the options the caller
        # already passes, and an uncalibrated consumer has no threshold for the
        # active backend, so it cannot steer anything. The bar still demands 100
        # rows, precision >= 0.90 and ECE <= 0.05 before a flip.
        if consumer_id not in CONSUMERS:
            logger.info(
                "decision_engine: consumer=%r is outside the declared set - "
                "measuring it in shadow (no threshold => no enforcement)",
                consumer_id,
            )
        # The ONE general bound is the option-code pool (A..Z then 00..99):
        # `candidate_cap` is the TOOL MENU's width, applied where the menu is
        # composed (ToolDecisionBox._compose_engine_menu). Cutting EVERY
        # consumer to it here (measured 2026-10-11) silently dropped page
        # elements past the 11th from browser_next - the element the model
        # clicked was often never on d1's menu.
        opts = [o for o in options if isinstance(o, str) and o][:OPTION_CEILING]
        if not opts:
            return None
        # THE input rule (Oracle jobs): the engine builds what the model
        # reads - ONE structured OracleState (REQ-3), never the raw frame.
        state = job_input(consumer_id, frame)
        _note_inline_shadow(consumer_id)
        if _oracle_phase_enabled():
            return self._decide_phase(consumer_id, opts, state, instruction)
        t_start = self._clock()  # REQ-26: lock-wait separated from compute
        if not self._lock.acquire(timeout=self._cfg.acquire_timeout_s):
            self.counters.lock_timeouts += 1
            return None
        lock_wait_ms = int((self._clock() - t_start) * 1000)
        try:
            if not self._load():
                return None
            backend = self._backend
            t0 = self._clock()
            # AC30.5 (T42): the model work runs on the dedicated inference
            # thread, never on the caller's step thread.
            ds = self._run_inference(
                lambda: backend.decide(
                    consumer_id, opts, state, instruction=instruction
                )
            )
            scoring_ms = int((self._clock() - t0) * 1000)
            if ds is None:
                return None
            self.counters.decisions += 1
            self.counters.bump_consumer(consumer_id)  # REQ-13 per-consumer
            total_ms = int((self._clock() - t_start) * 1000)
            logger.info(
                "%s decide consumer=%s chosen=%s conf=%.3f "
                "candidates=%d scoring_latency_ms=%d lock_wait_ms=%d "
                "decision_latency_ms=%d backend=%s",
                ENGINE_NAME, consumer_id, ds.chosen, ds.confidence,
                len(ds.distribution),
                scoring_ms, lock_wait_ms, total_ms, self.model_id,
            )
            return ds
        except Exception as e:
            logger.warning("decision_engine scoring failed: %r", e)
            return None
        finally:
            self._lock.release()

    # -- REQ-7 (Wave 6): one run, one STATE, that state's questions --------

    # AC7.4: the METHOD is configurable and measured, never assumed. The cap
    # bounds run width; the degenerate single-question case runs unbatched
    # through decide() (one state, one question IS one pass). Each row records
    # its grouping (`grouping` on the row) so two groupings stay comparable.
    BATCH_CAP = int(os.environ.get("IRIS_ORACLE_BATCH_CAP", "8") or 8)

    def decide_many(
        self,
        consults: Sequence[Tuple[str, Sequence[str], Dict[str, Any]]],
        instruction: Optional[str] = None,
    ) -> List[Optional["DecisionScore"]]:
        """Score a JOB's questions in one pass (AC7.1/AC7.2).

        Each consult is ``(consumer_id, options, frame)``. Grouping is the
        SPEC's rule, not a heuristic: only consults of the SAME job sharing
        the SAME rendered state share a pass (AC7.1 - different fields are a
        different state; two jobs never merge). Cap per REQ-7 AC7.4
        (``BATCH_CAP``); a 1-question group runs one pass over one question,
        the degenerate case the rule already ships.
        """
        try:
            rendered: List[Optional[OracleState]] = []
            for cid, options, frame in consults:
                if not [o for o in options if isinstance(o, str) and o]:
                    rendered.append(None)
                    continue
                rendered.append(job_input(cid, frame))
            # consult index -> (group index, position within the group)
            order: List[Optional[tuple]] = []
            group_members: List[List[tuple]] = []
            group_state: List[str] = []
            g_index: Dict[tuple, int] = {}
            for i, st in enumerate(rendered):
                if st is None:
                    order.append(None)
                    continue
                key = (st.job, st.text)
                if key not in g_index:
                    g_index[key] = len(group_members)
                    group_members.append([])
                    group_state.append(st.text)
                g = g_index[key]
                cid, options, _frame = consults[i]
                opts = [o for o in options if isinstance(o, str) and o][
                    :OPTION_CEILING]
                order.append((g, len(group_members[g])))
                group_members[g].append((cid, opts))
            out: List[Optional[DecisionScore]] = [None] * len(consults)
            for g, members in enumerate(group_members):
                got: List[Optional[DecisionScore]] = []
                for start in range(0, len(members), self.BATCH_CAP):
                    chunk = members[start:start + self.BATCH_CAP]
                    got.extend(self._decide_batch_group(
                        group_state[g],
                        [(c, o, instruction) for c, o in chunk]))
                for li, ds in enumerate(got):
                    for i, p in enumerate(order):
                        if p == (g, li):
                            out[i] = ds
                            break
            return out
        except Exception as e:  # noqa: BLE001 - fail closed, never raises
            logger.warning("decision_engine decide_many failed: %r", e)
            return [None] * len(consults)

    def _decide_batch_group(
        self,
        state_text: str,
        consults: Sequence[Tuple[str, List[str], Optional[str]]],
    ) -> List[Optional["DecisionScore"]]:
        """ONE admitted pass for one group (the phase domain admits the JOB;
        the load counts the QUESTIONS - AC7.3). Lock path and phase path both
        land here; one question degenerates to the classical decide shape."""
        _note_inline_shadow(consults[0][0])  # same the single path does
        global _oracle_questions_in_flight
        if _oracle_phase_enabled():
            _dom = _oracle_domain()
            _tok = None
            try:
                _osc = f"{_oracle_session_id()}:job:{oracle_job(consults[0][0]).name}"
                if _oracle_phase_exit_enabled():
                    _tok = _dom.enter(_osc)  # the dial's participant = the JOB
                else:
                    _dom.acquire(_osc)
            except Exception as e:  # noqa: BLE001 - a gate fault admits
                logger.warning("decision_engine: phase gate failed open (%r)", e)
            if not self._enter_run():
                if _tok is not None:
                    _dom.exit(_tok)
                return [None] * len(consults)
            try:
                with _ORACLE_RUNS_LOCK:
                    _oracle_questions_in_flight += len(consults)
                try:
                    return self._run_inference(
                        lambda: self._backend.decide_batch(state_text, consults),
                        concurrent=True)
                finally:
                    with _ORACLE_RUNS_LOCK:
                        _oracle_questions_in_flight -= len(consults)
            finally:
                self._exit_run()
        t_start = self._clock()
        if not self._lock.acquire(timeout=self._cfg.acquire_timeout_s):
            self.counters.lock_timeouts += 1
            return [None] * len(consults)
        try:
            if not self._load():
                return [None] * len(consults)
            backend = self._backend
            t0 = self._clock()
            with _ORACLE_RUNS_LOCK:
                _oracle_questions_in_flight += len(consults)
            try:
                out = self._run_inference(
                    lambda: backend.decide_batch(state_text, consults))
            finally:
                with _ORACLE_RUNS_LOCK:
                    _oracle_questions_in_flight -= len(consults)
                el = int((self._clock() - t0) * 1000)
                self.counters.decisions += sum(1 for ds in out if ds is not None)
                logger.info(
                    "%s decide_batch questions=%d latency_ms=%d backend=%s",
                    ENGINE_NAME, len(consults), el, self.model_id,
                )
            _ = t_start
            return out
        except Exception as e:
            logger.warning("decision_engine batch scoring failed: %r", e)
            return [None] * len(consults)
        finally:
            self._lock.release()

    def shadow_many(
        self,
        consults: Sequence[Tuple[str, Sequence[str], Dict[str, Any],
                                 Optional[Dict[str, Any]]]],
        *,
        sink: Callable[[dict], None],
        instruction: Optional[str] = None,
    ) -> bool:
        """A batched SHADOW consult: one lane job, ONE forward pass, and ONE
        ROW PER QUESTION - a batch is a transport unit, never a label unit
        (AC14.1). Every row keeps its own scope and reference; the row records
        the grouping that produced it (AC7.4) so two groupings stay
        comparable. Returns False when the lane refused it."""
        _items = [
            (cid, list(options), dict(frame or {}), dict(ref or {}), scope_now())
            for cid, options, frame, ref in consults
        ]

        def _job() -> None:
            out = self.decide_many(
                [(cid, options, frame) for cid, options, frame, _r, _s in _items],
                instruction,
            )
            for (cid, options, frame, ref, scope), ds in zip(_items, out):
                if ds is None:
                    continue  # no score: never fabricate a row
                row = {
                    "consumer_id": cid,
                    "engine": self.model_id or ENGINE_NAME,
                    "job": oracle_job(cid).name,
                    "chosen": ds.chosen,
                    "confidence": round(float(ds.confidence), 4),
                    "candidates": [
                        {"name": c.name, "prob": round(float(c.prob), 4)}
                        for c in (ds.distribution or ())
                    ],
                    "engine_latency_ms": ds.engine_latency_ms,
                    "shadow": True,
                    "grouping": f"job_batch:{len(_items)}",
                }
                if scope:
                    row.update(scope)
                if ref:
                    row.update(ref)
                sink(row)

        try:
            from backend.utils.durability_queue import lane

            ok = lane("oracle_shadow").submit(
                f"shadow_batch:{len(_items)}", _job)
            if not ok:
                logger.warning(
                    "%s shadow batch dropped (lane full)", ENGINE_NAME)
            return ok
        except Exception as e:  # noqa: BLE001 - a shadow never raises
            logger.warning("%s shadow_many submit failed: %r", ENGINE_NAME, e)
            return False

    # -- phase path (IRIS_ORACLE_PHASE) -------------------------------------

    def _enter_run(self) -> bool:
        """Take a run slot (load/unload gate) and make sure the backend is loaded.

        A refcount, not a cap: any number of runs may hold a slot. Shutdown waits
        for the count to drain, and new entries wait only while it is closing.
        """
        with self._run_cv:
            while self._closing:
                self._run_cv.wait()
            self._runs += 1
        ok = False
        try:
            if self._backend is not None:
                ok = True
            else:
                with self._load_lock:  # the lazy load happens ONCE, not per caller
                    ok = self._load()
        finally:
            if not ok:
                self._exit_run()
        return ok

    def _exit_run(self) -> None:
        with self._run_cv:
            self._runs -= 1
            self._run_cv.notify_all()

    def _decide_phase(
        self,
        consumer_id: str,
        opts: Sequence[str],
        frame: Dict[str, Any],
        instruction: Optional[str],
    ) -> Optional[DecisionScore]:
        """`decide` under the Caducean phase model: no engine lock, one question
        per run, runs overlap. Returns None only when the engine is unavailable
        or scoring fails - never because another decision held a lock."""
        global _oracle_questions_in_flight, _oracle_intra_op
        t_start = self._clock()
        _dom = _tok = None
        try:
            # Participant "{session}:{consumer_id}"; priority classes bypass (0)
            # on the timed gate, have right of way on the exit-driven one.
            _dom = _oracle_domain()
            _osc = f"{_oracle_session_id()}:{consumer_id}"
            if _oracle_phase_exit_enabled():
                _tok = _dom.enter(_osc)  # admitted when a run EXITS (natural exit)
            else:
                _dom.acquire(_osc)
        except Exception as e:  # noqa: BLE001 — fail-open: a gate fault admits
            logger.warning("decision_engine: phase gate failed open (%r)", e)
        phase_wait_ms = int((self._clock() - t_start) * 1000)
        if not self._enter_run():
            if _tok is not None:
                _dom.exit(_tok)
            return None
        try:
            backend = self._backend
            intra = (getattr(backend, "session_options", None) or {}).get(
                "intra_op_num_threads"
            )
            if isinstance(intra, int) and intra > 0:
                _oracle_intra_op = intra
            t0 = self._clock()
            with _ORACLE_RUNS_LOCK:
                _oracle_questions_in_flight += 1
            try:
                ds = self._run_inference(
                    lambda: backend.decide(
                        consumer_id, opts, frame, instruction=instruction
                    ),
                    concurrent=True,
                )
            finally:
                with _ORACLE_RUNS_LOCK:
                    _oracle_questions_in_flight -= 1
            scoring_ms = int((self._clock() - t0) * 1000)
            if ds is None:
                return None
            with self._counter_lock:
                self.counters.decisions += 1
                self.counters.bump_consumer(consumer_id)
            total_ms = int((self._clock() - t_start) * 1000)
            logger.info(
                "%s decide consumer=%s chosen=%s conf=%.3f "
                "candidates=%d scoring_latency_ms=%d phase_wait_ms=%d "
                "decision_latency_ms=%d backend=%s",
                ENGINE_NAME, consumer_id, ds.chosen, ds.confidence,
                len(ds.distribution),
                scoring_ms, phase_wait_ms, total_ms, self.model_id,
            )
            return ds
        except Exception as e:  # noqa: BLE001 — never raises
            logger.warning("decision_engine scoring failed: %r", e)
            return None
        finally:
            self._exit_run()
            if _tok is not None:
                _dom.exit(_tok)  # the decision is done: free its slot

    def shadow(
        self,
        consumer_id: str,
        options: Sequence[str],
        frame: Dict[str, Any],
        *,
        sink: Callable[[dict], None],
        reference: Optional[Dict[str, Any]] = None,
        instruction: Optional[str] = None,
    ) -> bool:
        """THE shadow call: score OFF the answer path and hand the row to *sink*.

        A shadow decision only produces a calibration row, so nothing the caller
        does may wait for it. The score runs on lane("oracle_shadow"); the row is
        the standard shape plus *reference* (``brain_choice`` / ``brain_bool``
        and any extra fields - bind VALUES now, the job runs later) and the
        consumer's job. Returns False when the lane refused the job (counted by
        the lane, logged here). Never raises. oracle.md S19.
        """
        _ref = dict(reference or {})
        _opts = list(options)
        _frame = dict(frame or {})
        # AC6.3a (T5.0): the scope is read NOW, on the caller's thread - the
        # lane's worker would see its own (empty) context.
        _scope = scope_now()

        def _job() -> None:
            ds = self.decide(consumer_id, _opts, _frame, instruction)
            if ds is None:
                return  # no engine / no criteria: never fabricate a row
            row = {
                "consumer_id": consumer_id,
                "engine": self.model_id or ENGINE_NAME,
                "job": oracle_job(consumer_id).name,
                "chosen": ds.chosen,
                "confidence": round(float(ds.confidence), 4),
                "candidates": [
                    {"name": c.name, "prob": round(float(c.prob), 4)}
                    for c in (ds.distribution or ())
                ],
                "engine_latency_ms": ds.engine_latency_ms,
                "shadow": True,
            }
            if _scope:
                row.update(_scope)
            row.update(_ref)
            sink(row)

        try:
            from backend.utils.durability_queue import lane

            ok = lane("oracle_shadow").submit(f"shadow:{consumer_id}", _job)
            if not ok:
                logger.warning("%s shadow %s dropped (lane full)", ENGINE_NAME, consumer_id)
            return ok
        except Exception as e:  # noqa: BLE001 - a shadow never raises
            logger.warning("%s shadow %s submit failed: %r", ENGINE_NAME, consumer_id, e)
            return False

    def noul(
        self,
        consumer_id: str,
        statement: str,
        frame: Optional[Dict[str, Any]] = None,
        *,
        true_label: str = "yes",
        false_label: str = "no",
    ) -> Optional[Noul]:
        """REQ-14 AC14.6 (T18): score a STATEMENT and return P(true).

        The bool monitor consumers (``sufficient`` / ``done``)
        ask "is this statement true", so they are answered with a ``Noul`` — a
        single calibrated probability — rather than a two-option Choice.

        Returns None when the engine is unavailable, the consumer has no
        criteria, or scoring fails. Callers MUST treat None as fail-closed
        (REQ-14 AC14.4) rather than as "true". Never raises.
        """
        try:
            ds = self.decide(
                consumer_id, [true_label, false_label],
                frame if frame is not None else {"goal": statement},
            )
            if ds is None:
                return None
            prob = 0.0
            for c in (ds.distribution or ()):
                if c.name == true_label:
                    prob = float(c.prob)
                    break
            else:
                return None  # the true label was not scored — refuse to guess
            return Noul(
                consumer_id=consumer_id,
                probability=prob,
                engine_latency_ms=ds.engine_latency_ms,
            )
        except Exception as e:  # noqa: BLE001 — fail-closed, never raises
            logger.warning("decision_engine noul failed: %r", e)
            return None

    # ── REQ-20 BATCHED SCORING — REMOVED 2026-09-26 (owner decision) ───────
    # `decide_many` used to live here. It is deleted, not disabled, so the
    # mistake cannot be repeated by calling it:
    #   * MEASURED with the real model: a batch of three distinct questions
    #     CHANGED a verdict (batch "no" where the same question scored alone
    #     answered "yes"). So the calibrated threshold, measured on solo runs,
    #     does not transfer to a batched verdict.
    #   * JEV's fan-out property is INDEPENDENCE ("one answer is never hidden
    #     context for another"). This export cannot provide it: one session run
    #     carries one question's context, so sharing the read while isolating
    #     the questions is impossible without changing the model.
    #   * The owner's rule: no parallelism without no-regression benefit.
    # The speed this promised is therefore unavailable, and the honest levers
    # left are: score fewer consumers, reuse the same-question cache, tune ORT
    # threads, keep the engine warm. Re-adding a batch requires a NEW
    # calibration for the batch shape, not a call site.

    # -- constrained args generation (bounded empty retry, REQ-4) ----------
    # REQ-2: single-parameter query tools — the goal text maps directly to
    # the 'query' parameter in 0ms, bypassing generate_args token generation
    # (+500-1,500ms of autoregressive generation saved).
    _SINGLE_PARAM_QUERY_TOOLS = frozenset({"search", "crawler_query"})

    # ── REQ-10 (T13): vision target fast path ──────────────────────────────
    # Pattern ids are STABLE calibration join keys (AC10.3) — renaming one
    # splits the historical rows into a different pattern.
    _VISION_TARGET_TOOL = "vision_detect_element"
    _VISION_TARGET_PARAM = "description"
    _CLICK_VERB = re.compile(r"\b(?:click|tap|press)\b", re.IGNORECASE)
    # Straight quotes (either style) and curly quotes (either orientation).
    _QUOTED_TARGET = re.compile(
        r'"([^"]+)"'
        r"|'([^']+)'"
        r"|\u201c([^\u201c\u201d]+)\u201d"
        r"|\u201e([^\u201e\u201c]+)\u201c"
    )
    _THE_X_BUTTON = re.compile(
        r"\bthe\s+([A-Za-z0-9][A-Za-z0-9 _\-]{0,60}?)\s+button\b", re.IGNORECASE
    )
    _MAX_TARGET_LEN = 120

    def fast_path_args(
        self,
        option: str,
        schema: Dict[str, Any],
        frame: Dict[str, Any],
    ) -> Optional[ArgsResult]:
        """REQ-2 + REQ-10: deterministic fast-path slot filling.

        REQ-2 — single-parameter query tools (search, crawler_query): the user
        goal text maps directly to the 'query' parameter in 0ms.
        REQ-10 (T13) — ``vision_detect_element``: a click/tap/press goal whose
        target is quoted, or written as "the X button", fills the element
        target in 0ms with zero LLM tokens.

        Returns None when no fast path applies (a different tool, a multi-arg
        schema, an empty goal, or no pattern match) — the caller falls back to
        generate_args / the legacy ladder (AC2.4, AC10.2). Never raises.
        """
        try:
            if option == self._VISION_TARGET_TOOL:
                props = (schema.get("properties") or {})
                if self._VISION_TARGET_PARAM not in props:
                    return None  # never fabricate a param the schema lacks
                return self._vision_target_fast_path(frame)
            if option not in self._SINGLE_PARAM_QUERY_TOOLS:
                return None
            required = [
                k for k, v in (schema.get("properties") or {}).items()
                if not (v or {}).get("optional", False)
            ]
            if required != ["query"]:
                return None  # multi-arg schema → AC2.4's generation path
            goal = str(frame.get("goal", "")).strip()
            if not goal:
                return None  # empty/invalid goal → fallback
            return ArgsResult(args={"query": goal}, retried=False,
                              fast_path="goal_to_query")
        except Exception:
            return None

    def _vision_target_fast_path(
        self, frame: Dict[str, Any]
    ) -> Optional[ArgsResult]:
        """REQ-10 (T13): deterministic vision target extraction.

        AC10.1 — a click/tap/press goal with a quoted target (or "the X
        button") fills the element target with 0 LLM tokens.
        AC10.2 — no pattern → None, so the caller's LLM resolution runs
        unchanged.
        Edge — a target that is empty or longer than 120 chars is NOT a fast
        path: we never dispatch an empty or absurd target.
        """
        goal = str(frame.get("goal", "")).strip()
        if not goal or not self._CLICK_VERB.search(goal):
            return None  # not a click-shaped goal → LLM resolution unchanged

        target, pattern = "", ""
        _m = self._QUOTED_TARGET.search(goal)
        if _m:
            target = next((g for g in _m.groups() if g), "")
            pattern = "quoted_target"
        else:
            _m = self._THE_X_BUTTON.search(goal)
            if _m:
                target, pattern = _m.group(1), "the_x_button"

        target = (target or "").strip()
        if not target or len(target) > self._MAX_TARGET_LEN:
            return None  # edge: empty / over-long → fallback, never empty dispatch
        return ArgsResult(
            args={self._VISION_TARGET_PARAM: target},
            retried=False,
            fast_path=pattern,
        )

    @staticmethod
    def _extract_json_obj(text: str) -> Optional[Dict[str, Any]]:
        if not text or not text.strip():
            return None
        try:
            v = json.loads(text)
            return v if isinstance(v, dict) else None
        except Exception:
            pass
        # balanced-brace salvage (mirrors tool_decision._extract_json style)
        start = text.find("{")
        if start < 0:
            return None
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        v = json.loads(text[start : i + 1])
                        return v if isinstance(v, dict) else None
                    except Exception:
                        return None
        return None

    def generate_args(
        self,
        consumer_id: str,
        option: str,
        schema: Dict[str, Any],
        frame: Dict[str, Any],
    ) -> ArgsResult:
        """Generate args JSON for the chosen option, validated against its schema.

        Retry rule (REQ-4): empty/whitespace output is retried exactly once;
        invalid JSON or schema-violating args are NOT retried (escalates).

        REQ-21/D12: the ONNX backend scores labels, it does not generate
        arguments — production injects no generative factory, so this
        degrades to ``ArgsResult(args=None, retried=False)`` and the box
        escalates to the legacy ladder (the Brain does schema-constrained
        generation there via function-calling, AC2.4). The generative path
        stays behind the ``llama_factory`` test seam so the args stage stays
        testable.
        """
        if not self._lock.acquire(timeout=self._cfg.acquire_timeout_s):
            self.counters.lock_timeouts += 1
            return ArgsResult(args=None, retried=False)
        t_start = self._clock()  # REQ-26: lock-wait separated from compute
        lock_wait_ms = int((self._clock() - t_start) * 1000)
        result = ArgsResult(args=None, retried=False)
        try:
            if self._llm is None:
                if self._llama_factory is None:
                    # No generative backend (production): degrade — the box
                    # escalates to the legacy ladder (AC2.4).
                    return result
                try:
                    self._llm = self._llama_factory()
                except Exception as e:
                    self.counters.load_failures += 1
                    logger.warning(
                        "decision_engine args model load failed: %r", e
                    )
                    return result
            allowed = set(schema.get("properties", {}).keys())
            required = set(schema.get("required", []))
            prompt = (
                f"You fill arguments for the function {option}.\n"
                f"State: {json.dumps(frame, default=str)[:400]}\n"
                f"Parameters (JSON schema): {json.dumps(schema)[:600]}\n"
                "Output ONLY one JSON object with the arguments. No prose.\n"
            )
            last_text = ""
            for attempt in (0, 1):
                out = self._llm.create_completion(
                    prompt,
                    max_tokens=self._cfg.max_args_tokens,
                    temperature=0.0,
                    stop=["\n\n"],
                )
                text = (out.get("choices", [{}])[0].get("text") or "").strip()
                if not text:
                    if attempt == 0:
                        self.counters.retries += 1
                        continue  # bounded empty retry (AC4.1)
                    result = ArgsResult(args=None, retried=True)
                    return result
                last_text = text
                break
            else:
                result = ArgsResult(args=None, retried=True)
                return result
            parsed = self._extract_json_obj(last_text)
            if parsed is None:
                return result
            if not required.issubset(parsed.keys()):
                return result
            if allowed and not set(parsed.keys()).issubset(allowed | set()):
                parsed = {k: v for k, v in parsed.items() if k in allowed}
            result = ArgsResult(args=parsed, retried=False)
            return result
        finally:
            # REQ-26 AC26.2: the args latency breakdown, emitted on every path.
            args_ms = int((self._clock() - t_start) * 1000)
            logger.info(
                "decision_engine generate_args consumer=%s option=%s "
                "args_latency_ms=%d lock_wait_ms=%d args_valid=%s retried=%s",
                consumer_id, option, args_ms, lock_wait_ms,
                result.args is not None, result.retried,
            )
            self._lock.release()


# ---------------------------------------------------------------------------
# Module-level singleton + shutdown hook anchor
# ---------------------------------------------------------------------------

_ENGINE: Optional[DecisionEngine] = None
_ENGINE_LOCK = threading.Lock()


def get_decision_engine(
    config: Optional[EngineConfig] = None,
    backend_factory: Optional[Callable[..., Any]] = None,
    llama_factory: Optional[Callable[..., Any]] = None,
) -> DecisionEngine:
    """Process-wide engine. Tests pass their own instance; production uses this.

    With no config passed (production), the ``oracle`` block is
    parsed into EngineConfig (REQ-25 AC25.1) — the block is LIVE, not
    decorative.
    """
    global _ENGINE
    with _ENGINE_LOCK:
        if _ENGINE is None:
            if config is None:
                config = load_engine_config()
            _ENGINE = DecisionEngine(
                config=config, backend_factory=backend_factory,
                llama_factory=llama_factory,
            )
        return _ENGINE


def shutdown_decision_engine() -> None:
    """Lifespan teardown hook (backend/main.py shutdown block)."""
    global _ENGINE
    with _ENGINE_LOCK:
        eng, _ENGINE = _ENGINE, None
    if eng is not None:
        try:
            eng.shutdown()
        except Exception:
            pass


def gate(
    consumer_id: str, options: Sequence[str], frame: Dict[str, Any]
) -> Tuple[Optional[DecisionScore], bool]:
    """The gate primitive for visible-surface consumers (REQ-11/12/13).

    Returns (score, enforced). score is None on any engine failure —
    callers then take their legacy heuristic path. enforced=False means
    shadow mode: record the decision but let the heuristics decide.
    Never raises.

    A calibration only transfers to the SAME question. A consumer registered
    with a fixed label set is scored and may act ONLY on options equal to that
    set; any other menu returns ``(None, False)`` without scoring (2026-10-05:
    the narration gate asked "speak"/"silent" on a constant frame while its
    calibration rows measure speak_all/speak_first_only/stay_silent). `enforced`
    is the chokepoint's verdict for THIS score's confidence.
    """
    try:
        # Wave 5: the spec registry lives in THIS module now (moved from the
        # deleted decision_backend_onnx) — no import needed.
        spec = get_consumer_spec(consumer_id)
        if spec is not None and spec.labels and set(options) != set(spec.labels):
            return None, False
        eng = get_decision_engine()
        ds = eng.decide(consumer_id, options, frame)
        if ds is None:
            return None, False
        return ds, oracle_acts(consumer_id, ds.confidence)
    except Exception as _e:
        logger.debug("decision_engine gate failed: %r", _e)
        return None, False
