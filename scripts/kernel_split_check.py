#!/usr/bin/env python
"""Kernel decomposition guard + map tool (docs/architecture/KERNEL_DECOMPOSITION.md).

Sub-commands (stdlib only; source is read as bytes and parsed with ast, the kernel
is never imported):
  map [--write]              K0: assign every method / module function to a target.
  manifest [--write|--check] G1: per-function ast hash; works before and after moves.
  globals --check            G2 (static): moved functions only load names they bind.
  move --target T ...        K4: byte mover (use on a copy via --root until Stage B).
  accounting --orig FILE     every original line appears exactly once after moves.

Every sub-command takes --root (default: the repo root) so it can run on a copied
tree that has backend/agent/agent_kernel.py and, optionally, backend/agent/kernel/.
"""
from __future__ import annotations

import argparse
import ast
import builtins as _builtins
import hashlib
import json
import os
import re
import sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_ROOT = os.path.dirname(HERE)
KERNEL_REL = "backend/agent/agent_kernel.py"
KERNEL_DIR_REL = "backend/agent/kernel"
MAP_REL = "docs/architecture/kernel_split_map.json"
MANIFEST_REL = "docs/architecture/kernel_manifest.json"
ALLOW_REL = "docs/architecture/kernel_manifest_allow.json"

# Blueprint section 5 string-patch targets (must be reached through the owning module).
PATCH_TARGETS = ("debit_work_units", "get_agent_kernel", "peek_active_kernel",
                 "_session_active_conversation")

BUILTINS = set(dir(_builtins)) | {"__file__", "__name__", "__doc__", "__package__",
                                  "__spec__", "__builtins__", "__loader__", "__path__",
                                  "__class__"}
SELF_NAMES = ("self", "owner", "kernel")
TARGETS = ("base", "models", "surface", "context", "turn", "planning", "der/run",
           "der/finalize", "der/node", "der/physics", "der/recovery", "der/report", "facade")

# ---------------------------------------------------------------------------
# K0 assignment table. Order of precedence:
#   1. EXPLICIT   name -> (target, reason). A reason starting "cluster:" is a member of
#                 a blueprint section-10 cluster; "rule:" a blueprint rule;
#                 "judgement:" a placement made by reading the body / callers.
#   2. PREFIX_RULES  (regex, target, why), first match wins.
#   3. module functions / classes only: the target most of their callers live in.
#   4. FALLBACK 'UNASSIGNED' (must stay at zero).
# Module-level names defined AFTER class AgentKernel (factories, singletons, global
# flag setters) go to 'facade' by rule (blueprint: factories and globals stay).
# ---------------------------------------------------------------------------
EXPLICIT = {}
PREFIX_RULES = [
    (r"^_goal_contract_", "planning", "cluster: goal_contract"),
]
FALLBACK = "UNASSIGNED"

# RES-2: names blueprint section 6b puts in kernel/base.py regardless of the count rule
# (the map derives the rest: loaded by >= 3 targets, or shared mutable state).
RES2_BASE = ("_CLAIM_LOCKS _CLAIM_LOCKS_GUARD _SCREEN_CLAIM _DER_NODE_QUOTA _NODE_CLAIMS "
             "_update_counters _update_counters_lock _der_recovery_lock _FILL_NO_TURN "
             "_emit_event _step_tool _step_calls _step_decisive_call _turn_in_flight "
             "logger").split()
# Methods placed by the caller rule (computed from the call data, not by name).
RES11_BLOCK_NAME = "DER_MAX_CYCLES"   # the try/except block that binds it moves to base
# Cycle-breakers: module functions two parts import from each other move to base
# (evidence: der/physics <-> der/finalize would import each other at module level).
CYCLE_BREAK_BASE = ("_der_fold_envelope",)
CALLER_RULE_METHODS = ("_der_plan_next_step", "_der_build_step_envelope")


def _put(target, names, reason):
    for n in names.split():
        EXPLICIT[n] = (target, reason)


# ---- facade: construction, lifecycle, module-flag setters, status -----------------
_put("facade", "__init__ _initialize_components set_main_loop set_memory_interface "
     "clear_conversation get_status get_conversation_context update_personality "
     "set_internet_access get_internet_access set_swarm_enabled get_swarm_enabled "
     "_handle_control_codes",
     "rule: __init__ / lifecycle / cleanup / global flag setters stay in the facade")
_put("facade", "_smart_excerpt",
     "judgement: pure helper with 9 callers in 4 targets and no data owner; stays in the facade")

# ---- models: model_config + vps_gateway -------------------------------------------
_put("models", "initialize_vps_gateway shutdown_vps_gateway configure_vps "
     "_normalise_endpoint configure_lmstudio configure_openai_compat configure_ollama "
     "configure_api configure_inprocess_local _model_provider _selected_reasoning_model "
     "_selected_tool_execution_model _model_for_role _provider_string_for_instance "
     "_is_openai_compat _is_api_provider _is_local_provider _local_openai_base "
     "_get_lmstudio_client prewarm_lmstudio _normalize_model_id set_model_selection "
     "get_model_selection", "cluster: model_config / vps_gateway")
_put("models", "response_max_tokens response_temperature",
     "judgement: per-role generation parameters read from the model selection, not token accounting")
_put("models", "set_role_binding",
     "judgement: writes the model role binding (model_config), no turn entry point")
_put("models", "infer",
     "judgement: 34-line adapter that only calls self._router.generate + _accrue_tokens; it IS the model call, used by 6 DER callers")

# ---- context: context_prompt + tokens_budget (CLM call sites) ---------------------
_put("context", "set_launcher_mode _effective_launcher_mode _get_developer_context "
     "_bound_external_project _build_system_prompt _assemble_direct_context "
     "_sanitize_messages _mycelium_profile_messages save_context_to_store "
     "restore_context_from_store", "cluster: context_prompt")
_put("context", "_accrue_tokens _count_tokens get_effective_token_budget "
     "resolve_context_window resolve_context_window_with_source "
     "resolve_turn_context_window _emit_context_usage", "cluster: tokens_budget")
_put("context", "_sync_context_window",
     "judgement: syncs the context-window budget; its 3 callers are model-config methods but the data it writes is the budget (CLM gate G-KERNEL)")
_put("context", "_der_bound_step_context",
     "judgement: bounds the step working context via resolve_context_window (REQ-3 forgetting); a CLM call site; sole caller is the DER loop")
_put("context", "_context_package_fields",
     "judgement: builds the prompt context package; sole caller _plan_task is planning but the data is context")

# ---- surface: documents_cards + narration_tts -------------------------------------
_put("surface", "_get_document_store _extract_sources_from_raw _apply_trust_ceiling "
     "_store_document_data _prism_card_id_for create_artifact _note_artifact_emitted "
     "update_document _json_default _is_capture_worthy _capture_tool_result "
     "reformat_document _record_reformat_edge suggest_reformat vocalize_document "
     "diagram_document retrieve_documents_by_trajectory _task_start_payload "
     "_effective_plan_title _multiagent_tags _register_card _resolve_card_identity "
     "_card_envelope _queue_steps_snapshot _persist_card_snapshot _save_card_footprint "
     "_der_emit_card_settle", "cluster: documents_cards")
_put("surface", "spoken_brief_needed stream_spoken_brief prepare_spoken_text "
     "_is_document_content _finalize_response _unwrap_tool_envelope "
     "_process_structured_response _emit_reply_progressively _supportive_text _log_surface",
     "cluster: narration_tts")
_put("surface", "_der_count_tool_call",
     "judgement: writes _suppressed_card_turn and only calls card helpers (_persist_card_snapshot, _task_start_payload ...); caller is der/node")

# ---- turn: transport_dispatch + process_text_message + direct reply + tools -------
_put("turn", "process_text_message _respond_direct _dispatch_api _dispatch_openai_compat "
     "_dispatch_inprocess _thinking_body _thinking_retry_body _needs_thinking "
     "_parse_thinking _strip_thinking _broadcast_inference_event _safe_stream "
     "_extract_chunk_text _chunk_batcher _stream_and_collect",
     "cluster: transport_dispatch / process_text_message / direct reply")
_put("turn", "_ensure_tool_bridge _get_openai_tools _get_tool_box _turn_is_bounded_content_ask",
     "cluster: tools (blueprint puts tools in turn although _get_tool_box has 7 callers, mostly DER)")
_put("turn", "_sanitize_task _pacman_zone_for_turn mark_external_tool clear_turn_trust_flag",
     "judgement: per-turn entry / trust bookkeeping; main caller is process_text_message")

# ---- planning: planning_routing + goal_contract + memory_facts --------------------
_put("planning", "_plan_task plan_task _build_planning_prompt _parse_planner_json "
     "_iter_json_objects _planned_beats _classify_provider_error _classify_plan_failure "
     "_admit_planned_beats _admit_first_beat _is_web_search_request _looks_informational "
     "_should_skip_der _empty_der_fallback_message _route_v2_frame _route_v2_route "
     "_log_route_shadow _gate register_planning_hook _web_mode_on _needs_planning "
     "_stamp_gate_telemetry _classify_intent _is_followup_to_task _get_active_goal_for "
     "_set_active_goal_for apply_follow_up _gc_result_is_error",
     "cluster: planning_routing / goal_contract")
_put("planning", "_get_memory_context _store_task_episode", "cluster: memory_facts")
_put("planning", "_shadow_row_sink",
     "judgement: callers are _initialize_components (facade) + two route-v2 methods; the shadow row sink belongs to routing")
_put("planning", "_caducean_modulate_temperature",
     "judgement: modulates the planner temperature; sole caller is _plan_task (reads u, decides no split)")

# ---- der/run ----------------------------------------------------------------------
_put("der/finalize", "_der_finalize_step _der_post_step",
     "res5: the second giant (finish one step) and its settle function get their own file")
_put("der/run", "_execute_plan_der _der_stamp_session_exit "
     "_turn_choke_check _session_has_client_for _note_tool_wait _end_tool_wait "
     "_maybe_trigger_skill_creation",
     "cluster: der_loop_steps (loop owners and their direct helpers)")
# ---- der/node ---------------------------------------------------------------------
_put("der/node", "_der_run_node _der_run_step_execution _der_run_direct_node "
     "_der_before_call _der_after_call _der_pre_dispatch_guard _der_tool_deadline "
     "_der_warm_vision_browser _der_note_quick_tier _run_step_direct "
     "_format_tool_result_for_step _format_tool_result _der_evidence_cap "
     "_der_query_has_reference _der_refine_query", "cluster: der_run_node")
_put("der/node", "_verify_step_result _verified_fraction _get_verifier",
     "judgement: result verification (plan -> node work -> verification); named in no blueprint cluster; _get_verifier is a patch target")

# ---- der/physics ------------------------------------------------------------------
_put("der/physics", "_der_physics_step _der_submit_physics _split_step _der_split_blocker "
     "_der_split_width _growth_width _der_surface_branch_candidates _der_region_node_id "
     "_der_record_governance _der_choose_coupling_branch _der_record_coupling_decision "
     "_der_verify_strictness _der_route_subloop_children", "cluster: der_physics_split")
_put("der/physics", "_der_live_cad_state",
     "judgement: reads the live Caducean engine for the split decision; 7 callers across run / recovery / report")

# ---- der/recovery -----------------------------------------------------------------
_put("der/recovery", "_der_handle_step_failure _der_maybe_open_recovery _der_enqueue_recovery "
     "_der_route_step_failure _der_execute_with_recovery _der_step_error_is_retryable "
     "_der_graft_missing_artifacts _declared_file_names _artifact_missing",
     "cluster: der_recover")
_put("der/recovery", "_der_check_steering _der_streak_gate _der_apply_steering "
     "_der_suspend_task _emit_steering_ack _der_amend_graph", "cluster: der_steer")
_put("der/recovery", "_der_findings_sufficient",
     "judgement: sufficiency gate; sole caller is _der_handle_step_failure")

# ---- der/report -------------------------------------------------------------------
_put("der/report", "_der_synthesize_outcome _der_synthesize_success_outcome "
     "_der_deterministic_failure_summary _der_deterministic_success_summary "
     "_der_user_facing_evidence _humanize_evidence _no_raw_source_dump "
     "_der_node_record_evidence _synthesize_response _generate_response "
     "_der_report_run_grade", "cluster: der_synth_report")
_put("der/report", "_der_recall_neighborhood _der_trace_task_id _der_visited_block "
     "_der_mediator_for _der_emit_fan_trace _turn_sources _der_topic_domain "
     "_der_execution_domain", "cluster: der_trace_recall")
_put("der/report", "_der_score_step_outcome",
     "judgement: thin wiring over the fan trace and mediator (181 lines); callers are finalize / failure handler")
_put("der/report", "_build_crawl_failure_explanation",
     "judgement: writes the user-facing crawl-failure text; sole caller _execute_plan_der")

# Module-level functions placed by judgement instead of by caller count.
_put("der/node", "_der_start_node _der_take_finished _der_claim _der_release _der_claim_lock",
     "judgement: parallel-node plumbing (claims, start, harvest) - same bench as _der_run_node")
_put("der/physics", "_der_settle_split", "judgement: settles the split race; physics decision")
_put("der/physics", "_der_physics_settle",
     "judgement: waits on the physics fold-back (fold.ready); the one physics reader")
_put("der/report", "_der_neighbors_block", "judgement: renders the recalled-neighbors block (trace recall)")


# ---------------------------------------------------------------------------
# Source reading and AST helpers
# ---------------------------------------------------------------------------
def read_text(path):
    with open(path, "rb") as fh:
        return fh.read().decode("utf-8", errors="surrogateescape")


def parse_file(path):
    return ast.parse(read_text(path), filename=path)


def span(node):
    start = node.lineno
    for d in getattr(node, "decorator_list", []):
        start = min(start, d.lineno)
    return start, node.end_lineno


def module_bindings(tree):
    """name -> kind for every name bound at module level (not inside def/class)."""
    out = {}

    def tgt(t, kind):
        if isinstance(t, ast.Name):
            out.setdefault(t.id, kind)
        elif isinstance(t, (ast.Tuple, ast.List)):
            for e in t.elts:
                tgt(e, kind)
        elif isinstance(t, ast.Starred):
            tgt(t.value, kind)

    def walk(body):
        for n in body:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                out.setdefault(n.name, "function")
            elif isinstance(n, ast.ClassDef):
                out.setdefault(n.name, "class")
            elif isinstance(n, ast.Assign):
                for t in n.targets:
                    tgt(t, "assign")
            elif isinstance(n, (ast.AnnAssign, ast.AugAssign)):
                tgt(n.target, "assign")
            elif isinstance(n, ast.Import):
                for a in n.names:
                    out.setdefault(a.asname or a.name.split(".")[0], "import")
            elif isinstance(n, ast.ImportFrom):
                for a in n.names:
                    out.setdefault(a.asname or a.name, "import")
            elif isinstance(n, (ast.For, ast.AsyncFor)):
                tgt(n.target, "assign")
                walk(n.body)
                walk(n.orelse)
            elif isinstance(n, ast.Try):
                walk(n.body)
                for h in n.handlers:
                    walk(h.body)
                walk(n.orelse)
                walk(n.finalbody)
            elif isinstance(n, (ast.If, ast.While)):
                walk(n.body)
                walk(n.orelse)
            elif isinstance(n, (ast.With, ast.AsyncWith)):
                walk(n.body)

    walk(tree.body)
    return out


def module_level_imports(tree):
    """Import / ImportFrom nodes executed at module level (incl. inside try / if)."""
    found = []

    def walk(body):
        for n in body:
            if isinstance(n, (ast.Import, ast.ImportFrom)):
                found.append(n)
            elif isinstance(n, ast.Try):
                walk(n.body)
                for h in n.handlers:
                    walk(h.body)
                walk(n.orelse)
                walk(n.finalbody)
            elif isinstance(n, (ast.If, ast.While, ast.For, ast.With)):
                walk(n.body)
                walk(getattr(n, "orelse", []))

    walk(tree.body)
    return found


_MUT_CALLS = ("Lock", "RLock", "Event", "Semaphore", "object", "dict", "set", "list",
              "deque", "defaultdict", "Counter", "OrderedDict", "Queue")


def mutable_module_state(tree):
    """Module-level names bound to a mutable object (dict / list / set / lock / ...):
    copying one into a second module silently makes two objects."""
    out = {}
    for n in tree.body:
        pairs = []
        if isinstance(n, ast.Assign):
            pairs = [(t, n.value) for t in n.targets]
        elif isinstance(n, ast.AnnAssign) and n.value is not None:
            pairs = [(n.target, n.value)]
        for t, v in pairs:
            if not isinstance(t, ast.Name):
                continue
            if isinstance(v, (ast.Dict, ast.List, ast.Set, ast.DictComp, ast.ListComp, ast.SetComp)):
                out[t.id] = type(v).__name__
            elif isinstance(v, ast.Call):
                fn = v.func
                nm = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
                if nm in _MUT_CALLS:
                    out[t.id] = nm + "()"
    return out


def local_names(fn):
    """Names bound inside fn (args, stores, local imports, nested defs, handlers).
    Names declared `global` are module names and are excluded."""
    loc, glob = set(), set()
    for n in ast.walk(fn):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            a = n.args
            for x in a.posonlyargs + a.args + a.kwonlyargs:
                loc.add(x.arg)
            if a.vararg:
                loc.add(a.vararg.arg)
            if a.kwarg:
                loc.add(a.kwarg.arg)
            if not isinstance(n, ast.Lambda):
                loc.add(n.name)
        elif isinstance(n, ast.ClassDef):
            loc.add(n.name)
        elif isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
            loc.add(n.id)
        elif isinstance(n, ast.ExceptHandler) and n.name:
            loc.add(n.name)
        elif isinstance(n, ast.Import):
            for a in n.names:
                loc.add(a.asname or a.name.split(".")[0])
        elif isinstance(n, ast.ImportFrom):
            for a in n.names:
                loc.add(a.asname or a.name)
        elif isinstance(n, ast.Global):
            glob.update(n.names)
    return loc - glob


def loaded_names(fn):
    return {n.id for n in ast.walk(fn)
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}


def global_stmt_names(fn):
    names = set()
    for n in ast.walk(fn):
        if isinstance(n, ast.Global):
            names.update(n.names)
    return names


def free_module_loads(fn):
    """Names the function loads that no local scope in it binds (module / builtin)."""
    return loaded_names(fn) - local_names(fn)


def self_param(fn, is_method):
    pos = fn.args.posonlyargs + fn.args.args
    if not pos:
        return None
    first = pos[0].arg
    if is_method:
        return first
    return first if first in SELF_NAMES else None


def attr_access(fn, selfname):
    """(reads, writes) of attributes on the self-like name. A subscript store or an
    augmented assignment on self.x counts as a write of x."""
    reads, writes = set(), set()
    if not selfname:
        return reads, writes
    for n in ast.walk(fn):
        if (isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)
                and n.value.id == selfname):
            if isinstance(n.ctx, (ast.Store, ast.Del)):
                writes.add(n.attr)
            else:
                reads.add(n.attr)
        elif isinstance(n, ast.Subscript) and isinstance(n.ctx, (ast.Store, ast.Del)):
            v = n.value
            if (isinstance(v, ast.Attribute) and isinstance(v.value, ast.Name)
                    and v.value.id == selfname):
                writes.add(v.attr)
    return reads, writes


def method_refs(fn, selfname, method_names):
    """AgentKernel methods called or referenced: self.X, AgentKernel.X."""
    out = set()
    for n in ast.walk(fn):
        if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name):
            if (n.value.id == selfname or n.value.id == "AgentKernel") and n.attr in method_names:
                out.add(n.attr)
    return out


def node_hash(node):
    dump = ast.dump(node, include_attributes=False)
    return hashlib.sha256(dump.encode("utf-8", "surrogateescape")).hexdigest()


def load_json(path):
    with open(path, "rb") as fh:
        return json.loads(fh.read().decode("utf-8"))


def write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = json.dumps(obj, indent=1, ensure_ascii=True) + "\n"
    with open(path, "wb") as fh:
        fh.write(data.encode("utf-8"))


# ---------------------------------------------------------------------------
# map (K0)
# ---------------------------------------------------------------------------
def module_dependent(fn):
    """Reasons a function's behaviour depends on WHICH module it is defined in
    (RES-9): reads __file__/__name__/__package__/..., frames, globals(), sys.modules."""
    out = set()
    loads = free_module_loads(fn)
    for x in ("__file__", "__name__", "__package__", "__spec__", "__path__", "__loader__"):
        if x in loads:
            out.add(x)
    for n in ast.walk(fn):
        if isinstance(n, ast.Call):
            f = n.func
            if isinstance(f, ast.Name) and f.id in ("globals", "__import__"):
                out.add(f.id + "()")
            d = _dotted(f)
            if d in ("inspect.currentframe", "inspect.stack", "inspect.getmodule", "inspect.getouterframes",
                     "inspect.getframeinfo", "sys._getframe", "sys._current_frames", "sys.modules.get"):
                out.add(d + "()")
        elif isinstance(n, ast.Subscript) and _dotted(n.value) == "sys.modules":
            out.add("sys.modules[...]")
    return sorted(out)


def stored_globals(fn):
    """Names declared `global` in fn that fn actually binds with a plain name store
    (a rebind). `global X` followed only by X[k] = v / X.append() is a mutation."""
    decl = global_stmt_names(fn)
    out = set()
    for n in ast.walk(fn):
        if isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)) and n.id in decl:
            out.add(n.id)
    return out


def top_consts(tree):
    """Direct module-level Assign / AnnAssign statements: name -> node."""
    out = {}
    for n in tree.body:
        if isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Name):
                    out[t.id] = n
        elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
            out[n.target.id] = n
    return out


def stmt_loads(node):
    """Names loaded by a module-level assignment statement (value and annotation)."""
    return {x.id for x in ast.walk(node) if isinstance(x, ast.Name) and isinstance(x.ctx, ast.Load)}


def build_map(root):
    path = os.path.join(root, KERNEL_REL)
    tree = parse_file(path)
    binds = module_bindings(tree)
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "AgentKernel")
    fnode = (ast.FunctionDef, ast.AsyncFunctionDef)
    methods = [n for n in cls.body if isinstance(n, fnode)]
    mnames = {m.name for m in methods}
    class_end = cls.end_lineno
    mod_items = [n for n in tree.body if isinstance(n, fnode + (ast.ClassDef,))
                 and n.name != "AgentKernel"]
    mod_names = {n.name for n in mod_items}
    consts = top_consts(tree)
    mutable = mutable_module_state(tree)

    patched = scan_patches(root)
    unparsable = patched.pop("__unparsable_test_files__", None)
    # "rebound": declared `global` in a function AND either rebound there by a plain store
    # or assigned / patched by tests (a test that swaps the object is a rebind). A global
    # that is only mutated (_update_counters[k] = v) is shared state, not a rebound name.
    rebound_sites = defaultdict(list)
    for n in ast.walk(tree):
        if isinstance(n, fnode):
            st = stored_globals(n)
            for g in global_stmt_names(n):
                if g in st or g in patched:
                    rebound_sites[g].append(n.name)
    rebound = set(rebound_sites)

    entries = []
    for n in methods + mod_items:
        is_method = n in methods
        kind = "method" if is_method else ("class" if isinstance(n, ast.ClassDef) else "function")
        s, e = span(n)
        e_ = {"name": n.name, "kind": kind, "start": s, "end": e, "lines": e - s + 1,
              "is_async": isinstance(n, ast.AsyncFunctionDef)}
        if kind == "class":
            e_.update(self_param=None, attrs_read=[], attrs_written=[], calls_methods=[])
        else:
            sp = self_param(n, is_method)
            r, w = attr_access(n, sp)
            e_.update(self_param=sp, attrs_read=sorted(r), attrs_written=sorted(w),
                      calls_methods=sorted(method_refs(n, sp, mnames)))
        loads = free_module_loads(n)
        e_["module_names_loaded"] = sorted(x for x in loads if x in binds)
        e_["calls_functions"] = sorted(x for x in loads if x in mod_names)
        e_["rebinds_globals"] = sorted(stored_globals(n))
        e_["uses_file_or_package"] = sorted(x for x in loads if x in ("__file__", "__package__"))
        e_["module_dependent"] = module_dependent(n)
        e_["lazy_relative_imports"] = sum(1 for x in ast.walk(n) if isinstance(x, ast.ImportFrom) and x.level)
        e_["_node"] = n
        e_["_after_class"] = (not is_method) and s > class_end
        entries.append(e_)

    by_name_m = {e["name"]: e for e in entries if e["kind"] == "method"}
    by_name_f = {e["name"]: e for e in entries if e["kind"] != "method"}

    # method callers (distinct) - needed by the caller rule for methods
    mcallers = defaultdict(set)
    for e in entries:
        for m in e["calls_methods"]:
            if not (e["kind"] == "method" and m == e["name"]):
                mcallers[m].add(e["name"])

    # --- assignment: explicit, rules ---
    for e in entries:
        e["target"], e["rule"] = None, None
        nm = e["name"]
        if e["kind"] != "method" and e["_after_class"]:
            e["target"], e["rule"] = "facade", "rule: defined after the class - factory / singleton / global flag setter"
        elif e["kind"] == "method" and nm in CALLER_RULE_METHODS:
            pass  # by the caller rule below
        elif nm in EXPLICIT:
            e["target"], e["rule"] = EXPLICIT[nm]
        else:
            for rx, tg, why in PREFIX_RULES:
                if re.search(rx, nm):
                    e["target"], e["rule"] = tg, why
                    break
    # --- RES-4 (revised by RES-7): a function that loads a name facade code STORES via a
    # `global` statement stays in the facade (the store does not pass through the module
    # __setattr__ that propagates patches). Names that are only mutated are propagated. ---
    stored_names = set()
    for n in ast.walk(tree):
        if isinstance(n, fnode):
            stored_names |= stored_globals(n)
    # what the compiled bytecode says (STORE_GLOBAL / DELETE_GLOBAL) for every rebound name
    bytecode_stores = defaultdict(set)
    import dis as _dis
    stack_ = [compile(read_text(path), path, "exec")]
    while stack_:
        co = stack_.pop()
        for ins in _dis.get_instructions(co):
            if ins.opname in ("STORE_GLOBAL", "DELETE_GLOBAL") and ins.argval in rebound:
                bytecode_stores[ins.argval].add(co.co_name)
        stack_.extend(c for c in co.co_consts if hasattr(c, "co_code"))
    res4 = []
    for e in entries:
        hit = sorted(set(e["module_names_loaded"]) & stored_names)
        if hit and e["target"] != "facade":
            res4.append({"name": e["name"], "kind": e["kind"], "was": e["target"] or "(by callers)",
                         "loads": hit})
            e["target"], e["rule"] = "facade", "res4: loads a name stored via `global`: " + ", ".join(hit)
    # --- RES-9: code whose behaviour depends on its module stays in the facade ---
    res9 = []
    for e in entries:
        reasons = e["module_dependent"]
        if reasons and e["target"] != "facade":
            res9.append({"name": e["name"], "kind": e["kind"], "was": e["target"] or "(by callers)",
                         "reasons": reasons})
            e["target"], e["rule"] = "facade", "res9: depends on its module (" + ", ".join(reasons) + ")"

    # callers of module items: methods + other module functions that load the name
    callers = defaultdict(set)
    for e in entries:
        for fn_name in e["calls_functions"]:
            if fn_name != e["name"] or e["kind"] == "method":
                callers[fn_name].add((e["kind"], e["name"]))
    for _ in range(5):  # fixed point over call chains
        for e in entries:
            if e["target"]:
                continue
            if e["kind"] == "method":
                if e["name"] not in CALLER_RULE_METHODS:
                    continue
                cs = [by_name_m[c] for c in mcallers[e["name"]] if c in by_name_m]
            else:
                cs = []
                for ck, cn in callers[e["name"]]:
                    ce = by_name_m[cn] if ck == "method" else by_name_f.get(cn)
                    if ce and cn != e["name"]:
                        cs.append(ce)
            votes = Counter(ce["target"] for ce in cs if ce["target"])
            if votes:
                best = max(votes.items(), key=lambda kv: (kv[1], -TARGETS.index(kv[0])))
                e["target"] = best[0]
                e["rule"] = "callers: %s" % ", ".join(
                    "%s=%d" % kv for kv in sorted(votes.items(), key=lambda kv: -kv[1]))
    for e in entries:
        if not e["target"]:
            e["target"], e["rule"] = FALLBACK, "no rule"
        e["callers"] = (sorted(cn for ck, cn in callers[e["name"]]) if e["kind"] != "method"
                        else sorted(mcallers[e["name"]]))

    # --- RES-11: the DER try/except import block moves once, to base ---
    module_blocks = []
    for n in tree.body:
        if isinstance(n, ast.Try):
            bb = module_bindings(ast.Module(body=[n], type_ignores=[]))
            if RES11_BLOCK_NAME in bb:
                s_, e_ = span(n)
                module_blocks.append({"start": s_, "end": e_, "lines": e_ - s_ + 1, "target": "base",
                                      "names": sorted(bb),
                                      "exported": sorted(module_bindings(ast.Module(body=n.body, type_ignores=[])))})
    block_names = {x for b in module_blocks for x in b["names"]}

    # --- RES-2: the base module, derived from the data ---
    loaders = defaultdict(set)
    for e in entries:
        for nme in e["module_names_loaded"]:
            loaders[nme].add(e["target"])
    base_items = {}
    facade_named = {e["name"] for e in entries if e["target"] == "facade" and e["kind"] != "method"}
    for nme, kind in binds.items():
        if kind == "import" or nme == "AgentKernel" or nme in rebound or nme in facade_named \
                or nme in block_names:
            continue
        n_t = len(loaders.get(nme, ()))
        why = []
        if n_t >= 3:
            why.append("loaded by %d targets" % n_t)
        if nme in mutable and n_t > 1:
            why.append("mutable state loaded by %d targets" % n_t)
        if nme in RES2_BASE:
            why.append("RES-2 list")
        if why:
            base_items[nme] = why
    for nme in RES2_BASE:
        if nme in binds and nme not in base_items and nme not in rebound:
            base_items[nme] = ["RES-2 list"]
    for nme in CYCLE_BREAK_BASE:
        if nme in binds:
            base_items.setdefault(nme, []).append("cycle-break (der/physics <-> der/finalize)")
    # constants: loaded by one non-facade target only -> owned by it; by two or more
    # targets -> shared, so base; by the facade alone / by nothing -> facade
    const_home = {}
    for nme in consts:
        if nme in base_items or nme in rebound or nme in patched:
            continue
        ts = loaders.get(nme, set())
        if not ts or ts == {"facade"}:
            continue
        if len(ts) == 1:
            const_home[nme] = next(iter(ts))
        else:
            base_items[nme] = ["shared constant loaded by %d targets" % len(ts)]
    # dependency closure: base may depend on nothing outside base (imports are copied)
    fn_by_name = {e["name"]: e for e in entries if e["kind"] != "method"}
    changed = True
    while changed:
        changed = False
        for nme in list(base_items):
            need = set()
            if nme in fn_by_name:
                need |= set(fn_by_name[nme]["module_names_loaded"])
            if nme in consts:
                need |= stmt_loads(consts[nme]) & set(binds)
            for x in sorted(need):
                if (binds.get(x) == "import" or x == "AgentKernel" or x in base_items
                        or x in rebound or x in facade_named or x == nme):
                    continue
                base_items[x] = ["dependency of " + nme]
                const_home.pop(x, None)
                changed = True
    for e in entries:
        if e["name"] in base_items and e["kind"] != "method" and e["target"] != "facade":
            e["target"], e["rule"] = "base", "base: " + "; ".join(base_items[e["name"]])
    # constants / state: base when selected, else they stay in the facade
    const_rows = []
    for nme, node in sorted(consts.items(), key=lambda kv: kv[1].lineno):
        s, e = span(node)
        const_rows.append({"name": nme, "start": s, "end": e, "lines": e - s + 1,
                           "target": ("base" if nme in base_items else const_home.get(nme, "facade")),
                           "mutable": nme in mutable,
                           "loaded_by_targets": sorted(loaders.get(nme, ()))})
    # base items must depend on nothing outside base (imports are copied alongside)
    base_names = set(base_items)
    violations = []
    for e in entries:
        if e["target"] == "base":
            for x in e["module_names_loaded"]:
                if binds.get(x) != "import" and x not in base_names and x != "AgentKernel":
                    violations.append("%s loads %s (%s) which is not in base" % (e["name"], x, binds.get(x)))
    for r in const_rows:
        if r["target"] == "base":
            for x in stmt_loads(consts[r["name"]]):
                if x in binds and binds.get(x) != "import" and x not in base_names:
                    violations.append("%s loads %s (%s) which is not in base" % (r["name"], x, binds.get(x)))
    for nme in base_items:
        if binds.get(nme) in ("assign",) and nme not in consts:
            violations.append("%s is bound inside a try/if block; it cannot move by span" % nme)

    # --- facade-only names reached from non-facade targets (A3) ---
    home = {}
    for e in entries:
        if e["kind"] != "method":
            home[e["name"]] = e["target"]
    for r in const_rows:
        home[r["name"]] = r["target"]
    for nme in rebound:
        home[nme] = "facade"
    facade_reach, patch_blind = [], []
    for e in entries:
        if e["target"] in ("facade",):
            continue
        reach = []
        for x in e["module_names_loaded"]:
            if x == "AgentKernel" or binds.get(x) == "import":
                continue
            h = home.get(x, "facade")  # unplaced non-import bindings (try-block fallbacks) stay in the facade
            if h == "facade":
                reach.append({"name": x, "what": ("rebound global" if x in rebound else
                              "facade function" if x in facade_named else "facade constant/state")})
        if reach:
            facade_reach.append({"name": e["name"], "target": e["target"], "kind": e["kind"], "needs": reach})
        pb = sorted(x for x in e["module_names_loaded"] if x in patched and x != "AgentKernel")
        if pb:
            patch_blind.append({"name": e["name"], "target": e["target"], "patched_names_loaded": pb})

    for e in entries:
        e["callers_in_other_targets"] = []
        if e["kind"] != "method":
            tg = set()
            for ck, cn in callers[e["name"]]:
                ce = by_name_m[cn] if ck == "method" else by_name_f.get(cn)
                if ce and ce["target"] != e["target"]:
                    tg.add(ce["target"])
            e["callers_in_other_targets"] = sorted(tg)

    # --- attribute owner = target whose functions write it most ---
    wv = defaultdict(Counter)
    for e in entries:
        if e["target"] == "facade":
            continue  # __init__ / _initialize_components write every attribute once; not an owner
        for a in e["attrs_written"]:
            wv[a][e["target"]] += 1
    owner = {a: max(c.items(), key=lambda kv: (kv[1], -TARGETS.index(kv[0]) if kv[0] in TARGETS else 0))[0]
             for a, c in wv.items()}
    for e in entries:
        w, r = e["attrs_written"], e["attrs_read"]
        wa = sum(1 for a in w if a in owner)
        wo = sum(1 for a in w if owner.get(a) == e["target"])
        ro = sum(1 for a in r if owner.get(a) == e["target"])
        ra = sum(1 for a in r if a in owner)
        e["attr_fit"] = {"written": len(w), "written_with_owner": wa, "written_owned_by_target": wo,
                         "read_with_owner": ra, "read_owned_by_target": ro}
        misfit = (wa >= 2 and wo / wa < 0.5) or (wa == 0 and ra >= 5 and ro / ra < 0.3)
        e["misfit"] = bool(misfit and e["target"] not in ("facade", "base"))
    # --- matrix of distinct caller->callee pairs between targets ---
    matrix = defaultdict(Counter)
    for e in entries:
        callees = [by_name_m[m] for m in e["calls_methods"] if m in by_name_m and m != e["name"]]
        callees += [by_name_f[f] for f in e["calls_functions"] if f in by_name_f and f != e["name"]]
        for c in callees:
            matrix[e["target"]][c["target"]] += 1

    # --- per-target module-level names loaded (input for the globals guard) ---
    per_target = defaultdict(set)
    for e in entries:
        per_target[e["target"]].update(e["module_names_loaded"])
    name_targets = defaultdict(set)
    for t, names in per_target.items():
        for nme in names:
            name_targets[nme].add(t)

    class_level = [{"start": n.lineno, "end": n.end_lineno,
                    "what": (ast.unparse(n.targets[0]) if isinstance(n, ast.Assign)
                             else ast.unparse(n.target) if isinstance(n, ast.AnnAssign)
                             else type(n).__name__)}
                   for n in cls.body if not isinstance(n, fnode)
                   and not (isinstance(n, ast.Expr) and isinstance(getattr(n, "value", None), ast.Constant))]

    for e in entries:
        del e["_node"], e["_after_class"]

    return {
        "source": KERNEL_REL,
        "class_span": [cls.lineno, cls.end_lineno],
        "counts": {"methods": len(methods), "module_functions": sum(1 for e in entries if e["kind"] == "function"),
                   "module_classes": sum(1 for e in entries if e["kind"] == "class"),
                   "unassigned": sum(1 for e in entries if e["target"] == FALLBACK)},
        "module_globals_rebound": {g: sorted(set(v)) for g, v in sorted(rebound_sites.items())},
        "res4_moved_to_facade": res4,
        "res9_kept_in_facade": res9,
        "global_store_bytecode": {g: sorted(bytecode_stores.get(g, ())) for g in sorted(rebound)},
        "global_store_ast": {g: sorted(rebound_sites[g]) for g in sorted(rebound)},
        "module_blocks": module_blocks,
        "base": {"items": [{"name": n, "binding": binds.get(n), "why": w,
                            "loaded_by_targets": sorted(loaders.get(n, ()))}
                           for n, w in sorted(base_items.items())],
                 "violations": violations},
        "facade_only_reach": facade_reach,
        "patched_names": patched,
        "unparsable_test_files": (unparsable or {}).get("files", []),
        "patch_blind": patch_blind,
        "patch_targets": list(PATCH_TARGETS),
        "class_level_statements": class_level,
        "module_constants": const_rows,
        "module_names_by_target": {t: sorted(per_target[t]) for t in TARGETS if t in per_target},
        "module_names_loaded_by_targets": {n: sorted(ts) for n, ts in sorted(name_targets.items())},
        "module_mutable_state": {n: {"kind": k, "loaded_by_targets": sorted(name_targets.get(n, ()))}
                                 for n, k in sorted(mutable.items())},
        "module_bindings": dict(sorted(binds.items())),
        "call_matrix": {a: dict(sorted(b.items())) for a, b in sorted(matrix.items())},
        "entries": entries,
    }


KERNEL_MOD = "backend.agent.agent_kernel"


def _dotted(n):
    parts = []
    while isinstance(n, ast.Attribute):
        parts.append(n.attr)
        n = n.value
    if isinstance(n, ast.Name):
        parts.append(n.id)
        return ".".join(reversed(parts))
    return None


def scan_patches(root):
    """Names of the kernel module that tests patch / assign. Returns
    {name: {count, files, forms}}. Forms detected: a string argument starting with
    'backend.agent.agent_kernel.' in ANY call (patch, mocker.patch, monkeypatch.setattr,
    patch.multiple ...); patch.object / setattr / setitem / delattr / patch.multiple on
    the module through an alias (import ... as A, from backend.agent import agent_kernel
    [as A], A = importlib.import_module(...), A = sys.modules[...], or the full dotted
    name); and A.X = value / A.X += value."""
    found = {}
    skipped = []

    def rec(name, rel, form):
        head = name.split(".")[0]
        d = found.setdefault(head, {"count": 0, "files": set(), "forms": set()})
        d["count"] += 1
        d["files"].add(rel)
        d["forms"].add(form)

    skip_dirs = {".venv", "node_modules", "__pycache__", ".claude", ".git", ".next", "kernel"}
    for sub in ("backend", "tests", "scripts", "evals"):
        base = os.path.join(root, sub)
        if not os.path.isdir(base):
            continue
        for dp, dn, fn in os.walk(base):
            dn[:] = sorted(d for d in dn if d not in skip_dirs or (d == "kernel" and "tests" in dp))
            for f in sorted(fn):
                if not f.endswith(".py"):
                    continue
                p = os.path.join(dp, f)
                raw = open(p, "rb").read()
                if b"agent_kernel" not in raw:
                    continue
                rel = os.path.relpath(p, root).replace("\\", "/")
                try:
                    tr = ast.parse(raw.decode("utf-8-sig", "surrogateescape"))
                except (SyntaxError, ValueError):
                    skipped.append(rel)
                    continue
                aliases = set()
                for n in ast.walk(tr):
                    if isinstance(n, ast.Import):
                        for a in n.names:
                            if a.name == KERNEL_MOD and a.asname:
                                aliases.add(a.asname)
                    elif isinstance(n, ast.ImportFrom):
                        for a in n.names:
                            if a.name == "agent_kernel" and (n.module == "backend.agent" or n.level):
                                aliases.add(a.asname or a.name)
                    elif isinstance(n, ast.Assign):
                        v = n.value
                        is_mod = False
                        if (isinstance(v, ast.Call) and v.args and isinstance(v.args[0], ast.Constant)
                                and v.args[0].value == KERNEL_MOD):
                            is_mod = True
                        if (isinstance(v, ast.Subscript) and isinstance(v.slice, ast.Constant)
                                and v.slice.value == KERNEL_MOD):
                            is_mod = True
                        if is_mod:
                            for t in n.targets:
                                if isinstance(t, ast.Name):
                                    aliases.add(t.id)

                def is_mod(x):
                    return (isinstance(x, ast.Name) and x.id in aliases) or _dotted(x) == KERNEL_MOD

                for n in ast.walk(tr):
                    if isinstance(n, ast.Call):
                        for a in n.args[:2]:
                            if (isinstance(a, ast.Constant) and isinstance(a.value, str)
                                    and a.value.startswith(KERNEL_MOD + ".")):
                                rec(a.value[len(KERNEL_MOD) + 1:], rel, "string target")
                        fname = n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, "id", "")
                        if fname in ("object", "setattr", "setitem", "delattr", "delitem", "multiple") and n.args \
                                and is_mod(n.args[0]):
                            if len(n.args) > 1 and isinstance(n.args[1], ast.Constant) and isinstance(n.args[1].value, str):
                                rec(n.args[1].value, rel, "alias + name arg")
                            for kw in n.keywords:
                                if kw.arg and fname == "multiple":
                                    rec(kw.arg, rel, "patch.multiple")
                    elif isinstance(n, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
                        tgts = n.targets if isinstance(n, ast.Assign) else [n.target]
                        for t in tgts:
                            if isinstance(t, ast.Attribute) and is_mod(t.value):
                                rec(t.attr, rel, "attribute assignment")
    out = {}
    for k, d in sorted(found.items()):
        out[k] = {"count": d["count"], "files": sorted(d["files"]), "forms": sorted(d["forms"])}
    if skipped:
        out["__unparsable_test_files__"] = {"count": len(skipped), "files": skipped, "forms": []}
    return out


def cmd_map(args):
    root = args.root
    m = build_map(root)
    ents = m["entries"]
    print("kernel_split_map: %d methods, %d module functions, %d module classes, UNASSIGNED=%d" % (
        m["counts"]["methods"], m["counts"]["module_functions"], m["counts"]["module_classes"],
        m["counts"]["unassigned"]))
    print("\n%-14s %8s %10s %10s %s" % ("target", "methods", "functions", "lines", "(lines = methods + module items)"))
    tot = Counter()
    for t in list(TARGETS) + [FALLBACK]:
        es = [e for e in ents if e["target"] == t]
        if not es:
            continue
        nm = sum(1 for e in es if e["kind"] == "method")
        lines = sum(e["lines"] for e in es)
        tot["m"] += nm
        tot["f"] += len(es) - nm
        tot["l"] += lines
        print("%-14s %8d %10d %10d" % (t, nm, len(es) - nm, lines))
    print("%-14s %8d %10d %10d" % ("TOTAL", tot["m"], tot["f"], tot["l"]))
    print("\ncross-target call matrix (rows call columns; distinct caller->callee pairs)")
    cols = [t for t in TARGETS if any(t in m["call_matrix"].get(r, {}) or t == r for r in m["call_matrix"])]
    print("%-14s" % "" + "".join("%13s" % c for c in cols))
    for r in cols:
        print("%-14s" % r + "".join("%13d" % m["call_matrix"].get(r, {}).get(c, 0) for c in cols))
    shared = [(n, ts) for n, ts in m["module_names_loaded_by_targets"].items() if len(ts) > 3]
    print("\nmodule names loaded by more than 3 targets:")
    for n, ts in shared:
        print("  %-24s %-9s %2d targets" % (n, m["module_bindings"][n], len(ts)))
    cross = [e for e in ents if e["kind"] != "method" and e["callers_in_other_targets"]]
    print("\nmodule functions/classes called from another target (need a cross-module import): %d" % len(cross))
    for e in cross:
        print("  %-30s in %-12s <- %s" % (e["name"], e["target"], ", ".join(e["callers_in_other_targets"])))
    if args.judgement:
        print("\nplaced by judgement:")
        for e in ents:
            if (e["rule"] or "").startswith("judgement"):
                print("  %-34s %-12s %s" % (e["name"], e["target"], e["rule"][11:]))
    if args.misfits:
        print("\nattribute misfits (writes mostly attributes owned by another target):")
        for e in ents:
            if e["misfit"]:
                print("  %-34s %-12s %s" % (e["name"], e["target"], e["attr_fit"]))
    bl = sum(r["lines"] for r in m["module_constants"] if r["target"] == "base")
    print("\nbase module constants/state moved by span: %d lines in %d statements"
          % (bl, sum(1 for r in m["module_constants"] if r["target"] == "base")))
    print("\nRES-2 base content (%d items; loaded-by shows the targets that load each):" % len(m["base"]["items"]))
    for it in m["base"]["items"]:
        print("  %-26s %-9s %-34s <- %s" % (it["name"], it["binding"], "; ".join(it["why"]), ", ".join(it["loaded_by_targets"]) or "-"))
    print("base dependency violations: %d" % len(m["base"]["violations"]))
    for v in m["base"]["violations"]:
        print("  VIOLATION " + v)
    print("\nRES-4: %d entries moved to the facade because they load a rebound global" % len(m["res4_moved_to_facade"]))
    for r in m["res4_moved_to_facade"]:
        print("  %-34s %-8s was %-14s loads %s" % (r["name"], r["kind"], r["was"], ", ".join(r["loads"])))
    fr = m["facade_only_reach"]
    pairs = sum(len(r["needs"]) for r in fr)
    print("\nnon-facade functions that still load a facade-only name: %d functions, %d (function, name) pairs" % (len(fr), pairs))
    for r in fr:
        print("  %-34s %-12s needs %s" % (r["name"], r["target"], ", ".join("%s [%s]" % (x["name"], x["what"]) for x in r["needs"])))
    print("\ntest patches of kernel-module names (count, files):")
    for nme, d in m["patched_names"].items():
        print("  %-30s %3d  %s  loaded by %s" % (nme, d["count"], ",".join(d["forms"]) or "-",
              ", ".join(m["module_names_loaded_by_targets"].get(nme, [])) or "(not a loaded module name)"))
        if args.details:
            for f in d["files"]:
                print("        " + f)
    print("patch-blind loaders (non-facade function loads a patched name): %d functions" % len(m["patch_blind"]))
    if args.details:
        for r in m["patch_blind"]:
            print("  %-34s %-12s %s" % (r["name"], r["target"], ", ".join(r["patched_names_loaded"])))
    print("\nrebound globals:", ", ".join(m["module_globals_rebound"]) or "none")
    if m["counts"]["unassigned"]:
        print("UNASSIGNED:", ", ".join(e["name"] for e in ents if e["target"] == FALLBACK))
    if args.write:
        out = os.path.join(root, MAP_REL)
        write_json(out, m)
        print("wrote", MAP_REL)
    return 1 if m["counts"]["unassigned"] else 0


# ---------------------------------------------------------------------------
# kernel file scan shared by manifest and globals
# ---------------------------------------------------------------------------
def kernel_files(root):
    files = [os.path.join(root, KERNEL_REL)]
    kdir = os.path.join(root, KERNEL_DIR_REL)
    if os.path.isdir(kdir):
        for dp, dn, fn in os.walk(kdir):
            dn.sort()
            for f in sorted(fn):
                if f.endswith(".py"):
                    files.append(os.path.join(dp, f))
    return files


def generated_ranges(text):
    """(start, end) line ranges of the facade's generated <kernel-split:...> blocks."""
    out, start = [], None
    for i, l in enumerate(text.split("\n"), 1):
        if l.startswith("# <kernel-split:"):
            start = i
        elif l.startswith("# </kernel-split:") and start:
            out.append((start, i))
            start = None
    return out


def collect_functions(root):
    """-> (records, problems). record: dict(key, name, kind, file, owner, hash, node, tree).
    key = 'method:<name>' | 'function:<name>' | 'class:<name>'."""
    fnode = (ast.FunctionDef, ast.AsyncFunctionDef)
    recs, defined = [], defaultdict(list)
    for path in kernel_files(root):
        rel = os.path.relpath(path, root).replace("\\", "/")
        if os.path.basename(path) == "__init__.py":
            continue  # package markers; kernel/__init__.py holds kernel_source() only
        tree = parse_file(path)
        gen = generated_ranges(read_text(path))
        for n in tree.body:
            if any(a <= n.lineno <= b for a, b in gen):
                continue  # inside a generated facade block
            if isinstance(n, fnode):
                recs.append(dict(key="function:" + n.name, name=n.name, kind="function",
                                 file=rel, owner=None, node=n, tree=tree))
            elif isinstance(n, ast.ClassDef):
                if n.name == "AgentKernel" or n.name.endswith("Mixin"):
                    for m in n.body:
                        if isinstance(m, fnode):
                            recs.append(dict(key="method:" + m.name, name=m.name, kind="method",
                                             file=rel, owner=n.name, node=m, tree=tree))
                else:
                    recs.append(dict(key="class:" + n.name, name=n.name, kind="class",
                                     file=rel, owner=None, node=n, tree=tree))
    for r in recs:
        r["hash"] = node_hash(r["node"])
        defined[r["key"]].append("%s::%s" % (r["file"], r["owner"] or "<module>"))
    dupes = {k: v for k, v in defined.items() if len(v) > 1}
    return recs, dupes


# ---------------------------------------------------------------------------
# manifest (G1)
# ---------------------------------------------------------------------------
def cmd_manifest(args):
    root = args.root
    recs, dupes = collect_functions(root)
    entries = {}
    for r in recs:
        entries.setdefault(r["key"], r["hash"])  # first definition; dupes reported below
    manifest = {"version": 1,
                "note": "sha256(ast.dump(node, include_attributes=False)); key = kind:name; "
                        "methods of AgentKernel and *Mixin classes are one namespace",
                "counts": {"method": sum(1 for k in entries if k.startswith("method:")),
                           "function": sum(1 for k in entries if k.startswith("function:")),
                           "class": sum(1 for k in entries if k.startswith("class:"))},
                "entries": dict(sorted(entries.items()))}
    mpath = os.path.join(root, MANIFEST_REL)
    if args.write:
        if dupes:
            print("REFUSING to write: a name is defined twice:")
            for k, v in sorted(dupes.items()):
                print("  %s defined in %s" % (k, ", ".join(v)))
            return 1
        write_json(mpath, manifest)
        c = manifest["counts"]
        print("wrote %s: %d methods, %d functions, %d classes" % (MANIFEST_REL, c["method"], c["function"], c["class"]))
        return 0
    # --check (default)
    if not os.path.exists(mpath):
        print("FAIL: no stored manifest at", MANIFEST_REL)
        return 1
    stored = load_json(mpath)["entries"]
    allow_path = os.path.join(root, ALLOW_REL)
    allow = load_json(allow_path) if os.path.exists(allow_path) else {}
    bad = []
    for k, v in sorted(dupes.items()):
        bad.append("SHADOW   %s is defined %d times: %s" % (k, len(v), ", ".join(v)))
    for k in sorted(set(stored) - set(entries)):
        bad.append("MISSING  %s (in manifest, not found in any scanned file)" % k)
    for k in sorted(set(entries) - set(stored)):
        bad.append("NEW      %s (found, not in manifest)" % k)
    allowed = []
    for k in sorted(set(entries) & set(stored)):
        if entries[k] == stored[k]:
            continue
        name = k.split(":", 1)[1]
        a = allow.get(k) or allow.get(name)
        if a and a.get("old") == stored[k] and a.get("new") == entries[k]:
            allowed.append("%s (%s)" % (k, a.get("reason", "")))
        elif a:
            bad.append("HASH     %s changed, allow-list entry does not match both hashes "
                       "(old %s.. new %s..; allow old %s.. new %s..)" % (
                           k, stored[k][:12], entries[k][:12],
                           str(a.get("old"))[:12], str(a.get("new"))[:12]))
        else:
            bad.append("HASH     %s body changed (stored %s.., now %s..)" % (k, stored[k][:12], entries[k][:12]))
    if bad:
        print("manifest --check FAILED (%d problems)" % len(bad))
        for b in bad:
            print("  " + b)
        return 1
    print("manifest --check OK: %d entries match%s" % (
        len(stored), "; %d allow-listed edits: %s" % (len(allowed), "; ".join(allowed)) if allowed else ""))
    return 0


# ---------------------------------------------------------------------------
# globals (G2, static)
# ---------------------------------------------------------------------------
def kernel_dotted(root, path):
    rel = os.path.relpath(path, root).replace("\\", "/")
    return rel[:-3].replace("/", ".")


def parse_propagate(tree):
    """The facade's generated `_PROPAGATE = {module: (names...)}` table and whether the
    module class swap (`sys.modules[__name__].__class__ = ...`) is present."""
    table, swap = {}, False
    for n in tree.body:
        if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "_PROPAGATE" for t in n.targets) \
                and isinstance(n.value, ast.Dict):
            for k, v in zip(n.value.keys, n.value.values):
                if isinstance(k, ast.Constant) and isinstance(v, (ast.Tuple, ast.List)):
                    table[k.value] = {e.value for e in v.elts if isinstance(e, ast.Constant)}
        if isinstance(n, ast.Assign) and any(isinstance(t, ast.Attribute) and t.attr == "__class__"
                                             for t in n.targets):
            swap = True
    return table, swap


def kernel_import_edges(tree, mod_dotted):
    """Module-level imports of other kernel modules: set of dotted module names."""
    out = set()
    for imp in module_level_imports(tree):
        if isinstance(imp, ast.ImportFrom):
            if imp.level:
                pkg = mod_dotted.rsplit(".", imp.level)[0] if imp.level else ""
                m = pkg + ("." + imp.module if imp.module else "")
            else:
                m = imp.module or ""
            if m.startswith("backend.agent.kernel"):
                out.add(m)
                for a in imp.names:
                    out.add(m + "." + a.name)  # `from backend.agent.kernel import x` may name a module
        else:
            for a in imp.names:
                if a.name.startswith("backend.agent.kernel"):
                    out.add(a.name)
    return out


def cmd_globals(args):
    root = args.root
    fpath = os.path.abspath(os.path.join(root, KERNEL_REL))
    moved = [p for p in kernel_files(root) if os.path.abspath(p) != fpath
             and os.path.basename(p) != "__init__.py"]
    if not moved:
        print("no moved modules yet")
        return 0
    fnode = (ast.FunctionDef, ast.AsyncFunctionDef)
    ftree = parse_file(fpath)
    # rebound globals: `global` statements in every scanned file
    declared, stored = set(), set()
    for p in kernel_files(root):
        for n in ast.walk(parse_file(p)):
            if isinstance(n, fnode):
                declared |= global_stmt_names(n)
                stored |= stored_globals(n)
    # patched names: the stored map (written from the real tree), or a rescan on request
    mp = os.path.join(root, MAP_REL)
    if args.rescan_tests:
        patched = set(scan_patches(root)) - {"__unparsable_test_files__"}
    else:
        patched = set(load_json(mp).get("patched_names", {})) if os.path.exists(mp) else set()
    patched = (patched | set(PATCH_TARGETS)) - {"AgentKernel"}
    rebound = stored | (declared & patched)  # a bare `global X` with no store is not a rebind
    watched = rebound | patched
    fstate = mutable_module_state(ftree)
    base_path = os.path.join(root, KERNEL_DIR_REL, "base.py")
    bstate = mutable_module_state(parse_file(base_path)) if os.path.exists(base_path) else {}
    table, swap = parse_propagate(ftree)
    fbinds = module_bindings(ftree)
    errors = []
    if not table or not swap:
        errors.append("facade has no generated _PROPAGATE table + module class swap "
                      "(table: %s, class swap: %s)" % (bool(table), swap))

    # (b) sibling import cycles at module level
    graph = {}
    for p in moved:
        mod = kernel_dotted(root, p)
        graph[mod] = {m for m in kernel_import_edges(parse_file(p), mod)}
    known = set(graph)
    graph = {m: sorted(e & known - {m}) for m, e in graph.items()}
    color, stack = {}, []

    def dfs(u):
        color[u] = 1
        stack.append(u)
        for v in graph[u]:
            if color.get(v, 0) == 0:
                dfs(v)
            elif color.get(v) == 1:
                errors.append("import cycle between kernel modules: " + " -> ".join(stack[stack.index(v):] + [v]))
        stack.pop()
        color[u] = 2

    for m in sorted(graph):
        if color.get(m, 0) == 0:
            dfs(m)

    base_tree = parse_file(base_path) if os.path.exists(base_path) else None
    for p in moved:
        rel = os.path.relpath(p, root).replace("\\", "/")
        is_base = os.path.abspath(p) == os.path.abspath(base_path)
        mod = kernel_dotted(root, p)
        covered = table.get(mod, set())
        tree = parse_file(p)
        binds = module_bindings(tree)
        for imp in module_level_imports(tree):
            if isinstance(imp, ast.ImportFrom):
                m_ = ("." * imp.level) + (imp.module or "")
                hits_ak = m_.endswith("agent_kernel") or "agent_kernel" in [a.name for a in imp.names]
            else:
                hits_ak = any(a.name.endswith("agent_kernel") for a in imp.names)
            if hits_ak:
                errors.append("%s:%d R5 module-level import of agent_kernel (cycle): %s" % (
                    rel, imp.lineno, ast.unparse(imp)))
        for nme, kind in sorted(mutable_module_state(tree).items()):
            if nme in fstate:
                errors.append("%s defines its own %s (%s) - the facade already holds that object; "
                              "two copies split the state" % (rel, nme, kind))
            elif not is_base and nme in bstate:
                errors.append("%s defines its own %s (%s) - base.py holds that object; "
                              "two copies split the state" % (rel, nme, kind))
        funcs = []
        for n in tree.body:
            if isinstance(n, fnode):
                funcs.append((n.name, n))
            elif isinstance(n, ast.ClassDef):
                funcs.extend(("%s.%s" % (n.name, m.name), m) for m in n.body if isinstance(m, fnode))
        for qual, fn in funcs:
            loads = free_module_loads(fn)
            for g in sorted(stored_globals(fn)):
                errors.append("%s:%d %s rebinds `global %s` - it would rebind the NEW module's copy" % (
                    rel, fn.lineno, qual, g))
            for nme in sorted(loads):
                if nme in stored:
                    errors.append("%s:%d %s loads %s, which facade code STORES via `global` - the store does not "
                                  "pass through the propagating __setattr__, so this reader must stay in the facade" % (
                                      rel, fn.lineno, qual, nme))
                elif nme in covered:
                    continue  # propagated by the facade table (AgentKernel, patched and facade-owned names)
                elif nme == "AgentKernel" and nme not in binds:
                    errors.append("%s:%d %s loads AgentKernel but _PROPAGATE has no entry for %s" % (
                        rel, fn.lineno, qual, mod))
                elif nme in watched and nme in binds:
                    errors.append("%s:%d %s loads %s (%s), bound in this module and not covered by the "
                                  "_PROPAGATE table - a patch of the facade attribute would not reach it" % (
                                      rel, fn.lineno, qual, nme, "rebound global" if nme in rebound else "patched name"))
                elif nme not in binds and nme not in BUILTINS:
                    why = ("facade-owned name not covered by _PROPAGATE" if nme in fbinds
                           else "never imported or defined here (NameError at run time)")
                    errors.append("%s:%d %s loads %r: %s" % (rel, fn.lineno, qual, nme, why))
    # the facade itself: everything its remaining code loads must still be bound
    for n in ftree.body:
        items = [(n.name, n)] if isinstance(n, fnode) else (
            [("%s.%s" % (n.name, m.name), m) for m in n.body if isinstance(m, fnode)]
            if isinstance(n, ast.ClassDef) else [])
        for qual, fn in items:
            for nme in sorted(free_module_loads(fn)):
                if nme not in fbinds and nme not in BUILTINS:
                    errors.append("facade:%d %s loads %r which the facade no longer binds "
                                  "(missing re-export?)" % (fn.lineno, qual, nme))
    if errors:
        print("globals --check FAILED (%d errors)" % len(errors))
        for e in errors:
            print("  " + e)
        return 1
    print("globals --check OK: %d moved modules; _PROPAGATE covers %d modules, %d names" % (
        len(moved), len(table), len({x for v in table.values() for x in v})))
    return 0


# ---------------------------------------------------------------------------
# move (K4): byte mover. Works on BYTES by line span; nothing moved is decoded.
# ---------------------------------------------------------------------------
LEDGER_NAME = ".kernel_move_ledger.json"
MIXIN_NAMES = {"models": "ModelsMixin", "surface": "SurfaceMixin", "context": "ContextMixin",
               "turn": "TurnMixin", "planning": "PlanningMixin", "der/run": "DerRunMixin",
               "der/finalize": "DerFinalizeMixin", "der/node": "DerNodeMixin",
               "der/physics": "DerPhysicsMixin", "der/recovery": "DerRecoveryMixin",
               "der/report": "DerReportMixin"}
MARK_IMP = (b"# <kernel-split:imports>", b"# </kernel-split:imports>")
MARK_PROP = (b"# <kernel-split:propagate>", b"# </kernel-split:propagate>")
MARK_INJ = MARK_PROP
KERNEL_INIT = (b"# backend/agent/kernel package. Generated by scripts/kernel_split_check.py move.\n"
               b"# kernel_source(): the facade text followed by every kernel/**/*.py text in sorted order,\n"
               b"# for tests that scan the kernel source as text. Imports no kernel module.\n"
               b"import os\n\n\n"
               b"def kernel_source() -> str:\n"
               b"    here = os.path.dirname(os.path.abspath(__file__))\n"
               b"    paths = [os.path.join(os.path.dirname(here), \"agent_kernel.py\")]\n"
               b"    found = []\n"
               b"    for dirpath, dirnames, filenames in os.walk(here):\n"
               b"        dirnames[:] = sorted(d for d in dirnames if d != \"__pycache__\")\n"
               b"        found.extend(os.path.join(dirpath, f) for f in filenames if f.endswith(\".py\"))\n"
               b"    paths.extend(sorted(found, key=lambda q: os.path.relpath(q, here).replace(os.sep, \"/\")))\n"
               b"    parts = []\n"
               b"    for path in paths:\n"
               b"        with open(path, \"rb\") as fh:\n"
               b"            parts.append(fh.read().decode(\"utf-8\", errors=\"replace\"))\n"
               b"    return \"\".join(parts)\n")
HEADER_NOTE = (b"# Moved from backend/agent/agent_kernel.py by scripts/kernel_split_check.py move.\n"
               b"# Bodies are byte-identical to the originals (guard: kernel_split_check.py manifest --check).\n")
# Comment / blank-line travel rule (documented in the report): a unit is the def or
# assignment span (decorators included) PLUS the run of comment-only lines directly above
# it with no blank line between. Blank lines and comment lines separated by a blank line
# stay in the facade. Moved units are written back separated by generated blank lines.


def split_lines(data):
    parts = data.split(b"\n")
    out = [p + b"\n" for p in parts[:-1]]
    if parts[-1]:
        out.append(parts[-1])
    return out


def target_rel(t):
    return KERNEL_DIR_REL + "/" + t + ".py"


def absolutize(line):
    """Relative import line -> absolute (the module moves one package level down)."""
    if re.match(rb"^\s*from \.\. ?", line):
        raise ValueError("multi-level relative import: %r" % line)
    if re.match(rb"^(\s*)from \. import ", line):
        return line.replace(b"from . import ", b"from backend.agent import ", 1)
    if re.match(rb"^(\s*)from \.\w", line):
        return line.replace(b"from .", b"from backend.agent.", 1)
    return line


def lead_start(lines, s, floor):
    """First line (1-based) of the unit incl. comment-only lines directly above."""
    ls = s
    while ls - 2 >= floor and lines[ls - 2].strip().startswith(b"#"):
        ls -= 1
    return ls


def kernel_module_names(path):
    """Module-level names a kernel file defines (not plain imports) and its Mixin class.
    Names bound inside a module-level try block (the DER block in base) count."""
    tree = parse_file(path)
    names, mixin = [], None
    for n in tree.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.append(n.name)
        elif isinstance(n, ast.ClassDef):
            if n.name.endswith("Mixin"):
                mixin = n.name
            else:
                names.append(n.name)
        elif isinstance(n, ast.Assign):
            names.extend(t.id for t in n.targets if isinstance(t, ast.Name))
        elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
            names.append(n.target.id)
        elif isinstance(n, ast.Try):
            # only names the try BODY binds exist on the normal path (the except branch is a
            # fallback that defines more); re-exporting a fallback-only name would not import
            names.extend(module_bindings(ast.Module(body=n.body, type_ignores=[])))
    return names, mixin


def kernel_table(root, facade_owned, patched):
    """The _PROPAGATE table: {kernel module: sorted names}. A name is in it when a kernel
    module loads it and it is AgentKernel, a patched name, or a facade-owned name the
    module does not bind itself."""
    table = {}
    for t in TARGETS:
        if t == "facade":
            continue
        p = os.path.join(root, target_rel(t))
        if not os.path.exists(p):
            continue
        tree = parse_file(p)
        binds = module_bindings(tree)
        loads = set()
        for n in ast.walk(tree):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                loads |= free_module_loads(n)
        names = set()
        if "AgentKernel" in loads and "AgentKernel" not in binds:
            names.add("AgentKernel")
        names |= (loads | set(binds)) & patched  # a module that merely BINDS a patched name is kept in step too
        names |= {x for x in loads if x not in binds and x not in BUILTINS and x in facade_owned}
        if names:
            table["backend.agent.kernel." + t.replace("/", ".")] = sorted(names)
    return table


def facade_blocks(root, facade_owned, patched):
    """Generated re-export block (before the class) and propagation block (end of file)."""
    mods = []
    for t in TARGETS:
        if t == "facade":
            continue
        p = os.path.join(root, target_rel(t))
        if os.path.exists(p):
            names, mixin = kernel_module_names(p)
            mods.append((t, names, mixin))
    imp = [MARK_IMP[0] + b" generated by scripts/kernel_split_check.py move; do not edit by hand\n"]
    for t, names, mixin in mods:
        allnames = sorted(set(names)) + ([mixin] if mixin else [])
        if not allnames:
            continue
        dotted = "backend.agent.kernel." + t.replace("/", ".")
        imp.append(("from %s import (\n" % dotted).encode())
        for nme in allnames:
            imp.append(("    %s,\n" % nme).encode())
        imp.append(b")\n")
        imp.append(("import %s as _k_%s\n" % (dotted, t.replace("/", "_"))).encode())
    imp.append(MARK_IMP[1] + b"\n")
    table = kernel_table(root, facade_owned, patched)
    prop = [MARK_PROP[0] + b" generated by scripts/kernel_split_check.py move; do not edit by hand\n",
            b"# RES-7: an assignment to one of these module attributes (mock.patch, monkeypatch.setattr,\n",
            b"# plain `agent_kernel.X = v`) is forwarded to every kernel module that binds the name.\n",
            b"# A `global X; X = v` store inside this file does NOT pass through __setattr__.\n",
            b"import sys as _sys\n", b"import types as _types\n", b"_PROPAGATE = {\n"]
    for mod in sorted(table):
        prop.append(("    %r: (%s),\n" % (mod, "".join("%r, " % x for x in table[mod]))).encode())
    prop += [b"}\n", b"\n", b"\n", b"class _KernelModule(_types.ModuleType):\n",
             b"    def __setattr__(self, name, value):\n",
             b"        _types.ModuleType.__setattr__(self, name, value)\n",
             b"        for _mod_name, _names in _PROPAGATE.items():\n",
             b"            if name in _names:\n",
             b"                _target = _sys.modules.get(_mod_name)\n",
             b"                if _target is not None:\n",
             b"                    setattr(_target, name, value)\n",
             b"\n", b"\n",
             b"_sys.modules[__name__].__class__ = _KernelModule\n",
             b"for _mod_name, _names in _PROPAGATE.items():\n",
             b"    for _name in _names:\n",
             b"        setattr(_sys.modules[_mod_name], _name, globals()[_name])\n",
             MARK_PROP[1] + b"\n"]
    bases = [m for t, n, m in mods if m]
    return imp, prop, bases, table


def strip_block(lines, tags, marks):
    out, otags, skip = [], [], False
    for l, tg in zip(lines, tags):
        if l.startswith(marks[0]):
            skip = True
        if not skip:
            out.append(l)
            otags.append(tg)
        if skip and l.startswith(marks[1]):
            skip = False
    return out, otags


def cmd_move(args):
    root = args.root
    fpath = os.path.join(root, KERNEL_REL)
    data = open(fpath, "rb").read()
    if re.search(rb"\r(?!\n)", data) or (b"\r\n" in data and data.count(b"\r\n") != data.count(b"\n")):
        print("REFUSING: mixed or lone carriage returns in the facade; line spans are not byte-safe")
        return 2
    lines = split_lines(data)
    lp = os.path.join(root, LEDGER_NAME)
    if os.path.exists(lp):
        ledger = load_json(lp)
    else:
        ledger = {"orig_sha256": hashlib.sha256(data).hexdigest(), "orig_lines": len(lines),
                  "facade_tags": list(range(1, len(lines) + 1)), "files": {}, "edited": {}}
    tags = ledger["facade_tags"]
    assert len(tags) == len(lines), "ledger does not match the facade (edited outside the mover?)"
    targets = args.target or []
    if not targets:
        out = b"".join(lines)
        print("move (no targets): rebuilt %d lines; sha256 before %s after %s -> %s" % (
            len(lines), hashlib.sha256(data).hexdigest()[:16], hashlib.sha256(out).hexdigest()[:16],
            "IDENTICAL" if out == data else "DIFFERENT"))
        if not args.dry_run:
            open(fpath, "wb").write(out)
            write_json(lp, ledger)
        return 0 if out == data else 1
    mp = os.path.join(root, MAP_REL)
    if not os.path.exists(mp):
        print("no map at", MAP_REL, "- run `map --write` first")
        return 2
    kmap = load_json(mp)
    for t in targets:
        rc = move_one(root, kmap, t, lines, tags, ledger, args)
        if rc:
            return rc
        lines, tags = ledger["_lines"], ledger["_tags"]
    return 0


def fixup_siblings(root, T, ledger, NL):
    """After moving T: an earlier-moved module that loads a module-level name T now
    defines (and does not bind it) gets a sibling import line. Returns {file: names}."""
    tp = os.path.join(root, target_rel(T))
    new_names = set(kernel_module_names(tp)[0])
    done = {}
    for t in TARGETS:
        if t in ("facade", T):
            continue
        p = os.path.join(root, target_rel(t))
        rel = target_rel(t)
        if not os.path.exists(p) or rel not in ledger["files"]:
            continue
        tree = parse_file(p)
        binds = module_bindings(tree)
        loads = set()
        for n in ast.walk(tree):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                loads |= free_module_loads(n)
        want = sorted(x for x in loads if x in new_names and x not in binds)
        if not want:
            continue
        data = open(p, "rb").read()
        ls = split_lines(data)
        idx = next(i for i, l in enumerate(ls) if l.startswith(b"from __future__ import annotations"))
        add = [("from backend.agent.kernel.%s import (\n" % T.replace("/", ".")).encode().replace(b"\n", NL)]
        add += [("    %s,\n" % x).encode().replace(b"\n", NL) for x in want] + [b")" + NL]
        ls[idx + 2:idx + 2] = add
        open(p, "wb").write(b"".join(ls))
        tg = ledger["files"][rel]["tags"]
        tg[idx + 2:idx + 2] = [0] * len(add)
        done[rel] = want
    return done


def move_one(root, kmap, T, lines, tags, ledger, args):
    fpath = os.path.join(root, KERNEL_REL)
    if T == "facade" or (T != "base" and T not in MIXIN_NAMES):
        print("unknown or unmovable target", T)
        return 2
    text = b"".join(lines).decode("utf-8", "surrogateescape")
    tree = ast.parse(text)
    # the facade is CRLF throughout: generated lines follow it (moved lines are never touched)
    NL = b"\r\n" if lines and lines[0].endswith(b"\r\n") else b"\n"
    fnode = (ast.FunctionDef, ast.AsyncFunctionDef)
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "AgentKernel")
    fbinds = module_bindings(tree)
    ment = {e["name"]: e for e in kmap["entries"] if e["kind"] == "method"}
    fent = {e["name"]: e for e in kmap["entries"] if e["kind"] != "method"}
    tmap = {e["name"]: e["target"] for e in kmap["entries"] if e["kind"] != "method"}
    import_home = {}
    for n in tree.body:
        if isinstance(n, ast.ImportFrom) and (n.module or "").startswith("backend.agent.kernel"):
            continue  # the generated re-export block of an earlier move, not an original import
        if isinstance(n, ast.Import) and any(a.name.startswith("backend.agent.kernel") for a in n.names):
            continue
        if isinstance(n, ast.Try) and RES11_BLOCK_NAME in module_bindings(ast.Module(body=[n], type_ignores=[])):
            continue  # RES-11: moves to base; other parts import its names from base
        for nm, kd in module_bindings(ast.Module(body=[n], type_ignores=[])).items():
            if kd == "import":
                import_home.setdefault(nm, n)
    for r in kmap["module_constants"]:
        tmap[r["name"]] = r["target"]
    for b_ in kmap.get("module_blocks", []):
        for x in b_["exported"]:
            tmap[x] = b_["target"]
    consts = top_consts(tree)

    # ---- units to move (current facade line numbers) ----
    units = []  # dict(kind, name, s, e, node)

    def add(kind, name, node):
        s, e = span(node)
        units.append({"kind": kind, "name": name, "s": s, "e": e, "node": node})

    for n in cls.body:
        if isinstance(n, fnode) and n.name in ment and ment[n.name]["target"] == T:
            add("method", n.name, n)
    for n in tree.body:
        if isinstance(n, fnode + (ast.ClassDef,)) and n.name != "AgentKernel":
            e_ = fent.get(n.name)
            if e_ and e_["target"] == T:
                add("func", n.name, n)
    for r in kmap["module_constants"]:
        take = (r["target"] == "base" and T == "base") or (args.own_constants and r["target"] == T)
        if take and r["name"] in consts:
            add("const", r["name"], consts[r["name"]])
    block_binds = set()
    if T == "base":
        for n in tree.body:
            if isinstance(n, ast.Try):
                bb = module_bindings(ast.Module(body=[n], type_ignores=[]))
                if RES11_BLOCK_NAME in bb:
                    add("block", "<der-import-block>", n)
                    block_binds |= set(bb)
    if not units:
        print("move %s: nothing to move (already moved or empty)" % T)
        ledger["_lines"], ledger["_tags"] = lines, tags
        return 0
    units.sort(key=lambda u: u["s"])
    prev_end = 0
    for u in units:
        u["ls"] = lead_start(lines, u["s"], prev_end + 1)
        if u["ls"] <= prev_end:
            print("overlapping units near", u["name"])
            return 2
        prev_end = u["e"]
        first = lines[u["s"] - 1]
        if (not first.startswith(b"    ")) if u["kind"] == "method" else first[:1].isspace():
            print("unexpected indentation at unit", u["name"], first[:30])
            return 2

    # ---- checks on what must not move silently ----
    file_users = [u["name"] for u in units if u["kind"] not in ("const", "block") and set(
        (ment if u["kind"] == "method" else fent).get(u["name"], {}).get("uses_file_or_package", []))]
    rel_users = []
    for u in units:
        if u["kind"] in ("const", "block"):
            continue
        for x in ast.walk(u["node"]):
            if isinstance(x, ast.ImportFrom) and x.level:
                rel_users.append((u["name"], x.lineno))
    if file_users and not args.ack_file_users:
        print("REFUSING: moved code reads __file__/__package__ (its value changes in the new module): %s" % ", ".join(file_users))
        print("  pass --ack-file-users to move anyway")
        return 3
    if rel_users and not args.rewrite_relative:
        print("REFUSING: lazy relative imports inside moved bodies resolve against backend.agent.kernel: %s"
              % ", ".join("%s:%d" % x for x in rel_users))
        print("  pass --rewrite-relative to make them absolute (an allow-listed body edit)")
        return 3

    # ---- needed imports ----
    needed, unresolved, pending, propagated = set(), [], [], []
    own = {u["name"] for u in units} | block_binds
    for u in units:
        loads = (stmt_loads(u["node"]) if u["kind"] in ("const", "block") else free_module_loads(u["node"]))
        needed |= {x for x in loads if x in fbinds or x in tmap}
    if T == "base" and "logger" in own:
        needed.add("logging")
    imp_nodes, base_names, sib = {}, set(), defaultdict(set)
    inject_needed = "AgentKernel" in needed
    for x in sorted(needed):
        if x == "AgentKernel" or x in own:
            continue
        if x in import_home:
            imp_nodes[import_home[x].lineno] = import_home[x]
            continue
        t2 = tmap.get(x)
        if t2 == "base" and T != "base":
            base_names.add(x)
        elif t2 in (None, "facade"):
            propagated.append(x)  # facade-owned: injected by the _PROPAGATE table
        elif t2 == T:
            unresolved.append("%s (constant owned by %s, not moved: --no-own-constants)" % (x, T))
        elif os.path.exists(os.path.join(root, target_rel(t2))) or t2 == "base":
            sib[t2].add(x)
        else:
            pending.append("%s (target %s, not moved yet)" % (x, t2))

    # ---- build the destination ----
    dest, dtags = [], []

    def gen(b):
        dest.append(b.replace(b"\n", NL) if b.endswith(b"\n") and not b.endswith(b"\r\n") else b)
        dtags.append(0)

    for h in split_lines(HEADER_NOTE):
        gen(h)
    gen(b"from __future__ import annotations\n")
    gen(b"\n")
    for ln in sorted(imp_nodes):
        n = imp_nodes[ln]
        s_, e_ = span(n)
        for l in lines[s_ - 1:e_]:
            gen(absolutize(l))
    if base_names:
        gen(b"from backend.agent.kernel.base import (\n")
        for x in sorted(base_names):
            gen(("    %s,\n" % x).encode())
        gen(b")\n")
    for t2 in sorted(sib):
        gen(("from backend.agent.kernel.%s import (\n" % t2.replace("/", ".")).encode())
        for x in sorted(sib[t2]):
            gen(("    %s,\n" % x).encode())
        gen(b")\n")
    edited = {}
    mod_units = [u for u in units if u["kind"] != "method"]
    meth_units = [u for u in units if u["kind"] == "method"]

    def emit(u):
        rel_lines = {x.lineno for x in ast.walk(u["node"]) if isinstance(x, ast.ImportFrom) and x.level} \
            if u["kind"] not in ("const", "block") else set()
        for i in range(u["ls"], u["e"] + 1):
            l = lines[i - 1]
            tg = tags[i - 1]
            if i in rel_lines:
                nl = absolutize(l)
                if nl != l:
                    edited[u["name"]] = edited.get(u["name"], 0) + 1
                    l, tg = nl, "e%s" % tg
            if u["kind"] == "const" and u["name"] == "logger" and T == "base" and i == u["s"]:
                orig = tg
                l = b'logger = logging.getLogger("backend.agent.agent_kernel")  # RES-3: log name unchanged' + NL
                tg = "t%s" % orig
            dest.append(l)
            dtags.append(tg)

    first = True
    for u in mod_units:
        gen(b"\n")
        if first:
            gen(b"\n")
            first = False
        emit(u)
    if meth_units:
        gen(b"\n")
        gen(b"\n")
        gen(("class %s:\n" % MIXIN_NAMES[T]).encode())
        for k, u in enumerate(meth_units):
            if k:
                gen(b"\n")
            emit(u)

    # ---- facade after removal ----
    removed = set()
    for u in units:
        removed.update(range(u["ls"], u["e"] + 1))
    new_lines = [l for i, l in enumerate(lines, 1) if i not in removed]
    new_tags = [t for i, t in enumerate(tags, 1) if i not in removed]
    new_lines, new_tags = strip_block(new_lines, new_tags, MARK_IMP)
    new_lines, new_tags = strip_block(new_lines, new_tags, MARK_PROP)

    # write the destination first so facade_blocks() sees it
    dpath = os.path.join(root, target_rel(T))
    if os.path.exists(dpath):
        print("REFUSING: %s already exists" % target_rel(T))
        return 2
    summary = ("move %s: %d units (%d methods, %d module items), %d lines; imports: %d statements, base %d, "
               "siblings %d; unresolved %s; pending %s; edited %s; propagated-in %d" % (
                   T, len(units), len(meth_units), len(mod_units),
                   sum(u["e"] - u["ls"] + 1 for u in units), len(imp_nodes), len(base_names),
                   sum(len(v) for v in sib.values()), unresolved or "-", pending or "-", edited or "-",
                   len(set(propagated))))
    print(summary)
    if args.dry_run:
        ledger["_lines"], ledger["_tags"] = lines, tags
        return 0
    os.makedirs(os.path.dirname(dpath), exist_ok=True)
    for pkg in {os.path.join(root, KERNEL_DIR_REL), os.path.dirname(dpath)}:
        ip = os.path.join(pkg, "__init__.py")
        if not os.path.exists(ip):
            if os.path.abspath(pkg) == os.path.abspath(os.path.join(root, KERNEL_DIR_REL)):
                open(ip, "wb").write(KERNEL_INIT.replace(b"\n", NL))
            else:
                open(ip, "wb").write(b"# kernel subpackage marker (generated by scripts/kernel_split_check.py move)" + NL)
    open(dpath, "wb").write(b"".join(dest))
    ledger["files"][target_rel(T)] = {"tags": dtags}

    # re-parse the facade without the moved units, then edit bases, add blocks
    text2 = b"".join(new_lines).decode("utf-8", "surrogateescape")
    tree2 = ast.parse(text2)
    cls2 = next(n for n in tree2.body if isinstance(n, ast.ClassDef) and n.name == "AgentKernel")
    stripped = b"".join(new_lines)
    stripped_tree = tree2
    facade_owned = set(module_bindings(stripped_tree))
    patched = set(kmap.get("patched_names", {})) - {"AgentKernel"}
    imp_blk, inj_blk, bases, table = facade_blocks(root, facade_owned, patched)
    imp_blk = [b.replace(b"\n", NL) for b in imp_blk]
    inj_blk = [b.replace(b"\n", NL) for b in inj_blk]
    # earlier-moved modules that now find a sibling's helper they were missing
    fixups = fixup_siblings(root, T, ledger, NL)
    # import-time uses before the block: module-level code that loads a moved name
    moved_names = set()
    for t in TARGETS:
        p = os.path.join(root, target_rel(t))
        if t != "facade" and os.path.exists(p):
            moved_names |= set(kernel_module_names(p)[0])
    early = []
    for n in tree2.body:
        if n.lineno >= cls2.lineno:
            break
        if isinstance(n, fnode):
            probe = [x for d in n.decorator_list for x in ast.walk(d)] + \
                    [x for d in (n.args.defaults + [k for k in n.args.kw_defaults if k]) for x in ast.walk(d)]
        elif isinstance(n, ast.ClassDef):
            probe = [x for d in n.decorator_list for x in ast.walk(d)]
        else:
            probe = list(ast.walk(n))
        hit = {x.id for x in probe if isinstance(x, ast.Name) and isinstance(x.ctx, ast.Load)} & moved_names
        if hit:
            early.append("line %d uses %s at import time" % (n.lineno, ", ".join(sorted(hit))))
    if early:
        print("REFUSING (nothing written to the facade; destination %s was written - remove it): %s"
              % (target_rel(T), "; ".join(early)))
        return 3
    ci = cls2.lineno - 1
    old_cls = new_lines[ci]
    if not re.match(rb"^class AgentKernel(\(.*\))?:\s*$", old_cls):
        print("unexpected class line:", old_cls)
        return 2
    new_cls = (("class AgentKernel(%s):" % ", ".join(bases)).encode() if bases else b"class AgentKernel:") + NL
    ctag = new_tags[ci]
    if new_cls != old_cls:
        new_lines[ci] = new_cls
        new_tags[ci] = ctag if str(ctag).startswith("e") else "e%s" % ctag
    # propagation block at the end of the file, import block before the class line
    if not new_lines[-1].endswith(b"\n"):
        new_lines[-1] = new_lines[-1] + NL
    new_lines.extend([NL] + inj_blk)
    new_tags.extend([0] * (1 + len(inj_blk)))
    new_lines[ci:ci] = imp_blk + [NL]
    new_tags[ci:ci] = [0] * (len(imp_blk) + 1)
    open(fpath, "wb").write(b"".join(new_lines))
    ledger["facade_tags"] = new_tags
    ledger["_lines"], ledger["_tags"] = new_lines, new_tags
    # allow-list for the edited bodies (relative imports made absolute)
    if edited:
        ap = os.path.join(root, ALLOW_REL)
        allow = load_json(ap) if os.path.exists(ap) else {}
        stored = load_json(os.path.join(root, MANIFEST_REL))["entries"]
        recs, _ = collect_functions(root)
        for r in recs:
            if r["name"] in edited and r["key"] in stored and r["hash"] != stored[r["key"]]:
                allow[r["key"]] = {"old": stored[r["key"]], "new": r["hash"],
                                   "reason": "relative import made absolute (module moved from backend/agent to "
                                             "backend/agent/kernel); %d line(s)" % edited[r["name"]]}
        write_json(ap, allow)
        print("allow-list updated:", ", ".join(sorted(allow)))
    if fixups:
        print("sibling imports added to earlier modules:", fixups)
    save = {k: v for k, v in ledger.items() if not k.startswith("_")}
    write_json(os.path.join(root, LEDGER_NAME), save)
    return 0


def cmd_accounting(args):
    """Every original line appears exactly once across the facade and the new files."""
    root = args.root
    orig = split_lines(open(args.orig, "rb").read())
    ledger = load_json(os.path.join(root, LEDGER_NAME))
    problems, seen = [], Counter()
    transformed, edited = [], []
    srcs = [(KERNEL_REL, ledger["facade_tags"])] + [(k, v["tags"]) for k, v in ledger["files"].items()]
    for rel, tg in srcs:
        got = split_lines(open(os.path.join(root, rel), "rb").read())
        if len(got) != len(tg):
            problems.append("%s: %d lines on disk, %d tags" % (rel, len(got), len(tg)))
            continue
        last = 0
        for i, (l, t) in enumerate(zip(got, tg), 1):
            if t == 0:
                continue
            n = int(str(t).lstrip("et"))
            seen[n] += 1
            if n <= last:
                problems.append("%s:%d original line %d out of order (previous %d)" % (rel, i, n, last))
            last = n
            if isinstance(t, int):
                if l != orig[n - 1]:
                    problems.append("%s:%d differs from original line %d" % (rel, i, n))
            elif str(t).startswith("t"):
                transformed.append((rel, i, n))
            else:
                edited.append((rel, i, n))
    missing = [n for n in range(1, len(orig) + 1) if seen[n] == 0]
    dup = [n for n, c in seen.items() if c > 1]
    if missing:
        problems.append("%d original lines missing, first: %s" % (len(missing), missing[:5]))
    if dup:
        problems.append("%d original lines appear more than once, first: %s" % (len(dup), dup[:5]))
    gen = {rel: sum(1 for t in tg if t == 0) for rel, tg in srcs}
    print("accounting: %d original lines; %d exact, %d edited, %d transformed; generated lines per file: %s" % (
        len(orig), sum(1 for n in seen if seen[n] == 1) - len(edited) - len(transformed),
        len(edited), len(transformed), gen))
    for rel, i, n in transformed:
        print("  transformed: %s:%d replaces original line %d: %r" % (rel, i, n, orig[n - 1][:80]))
    for rel, i, n in edited:
        print("  edited: %s:%d from original line %d" % (rel, i, n))
    if problems:
        print("accounting FAILED")
        for p in problems:
            print("  " + p)
        return 1
    print("accounting OK")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=DEFAULT_ROOT, help="repo root (default: this repo)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("map")
    p.add_argument("--write", action="store_true")
    p.add_argument("--judgement", action="store_true", help="list placements made by judgement")
    p.add_argument("--misfits", action="store_true", help="list entries that fit their target badly")
    p.add_argument("--details", action="store_true", help="list patched-name files and patch-blind loaders")
    p.set_defaults(fn=cmd_map)
    p = sub.add_parser("manifest")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--write", action="store_true")
    g.add_argument("--check", action="store_true")
    p.set_defaults(fn=cmd_manifest)
    p = sub.add_parser("globals")
    p.add_argument("--check", action="store_true")
    p.add_argument("--rescan-tests", action="store_true", help="rescan the tests for patched names")
    p.set_defaults(fn=cmd_globals)
    p = sub.add_parser("move", help="byte mover (K4): move one or more targets out of the facade")
    p.add_argument("--target", action="append", help="target to move (repeatable, applied in order)")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--no-own-constants", dest="own_constants", action="store_false",
                   help="do not move constants owned by the target (RES-8 default: they move)")
    p.add_argument("--no-rewrite-relative", dest="rewrite_relative", action="store_false",
                   help="refuse lazy relative imports in moved bodies (RES-10 default: make them absolute)")
    p.set_defaults(own_constants=True, rewrite_relative=True)
    p.add_argument("--ack-file-users", action="store_true",
                   help="move code that reads __file__ / __package__ anyway")
    p.set_defaults(fn=cmd_move)
    p = sub.add_parser("accounting", help="every original line appears once across facade + new files")
    p.add_argument("--orig", required=True, help="pristine copy of agent_kernel.py")
    p.set_defaults(fn=cmd_accounting)
    args = ap.parse_args(argv)
    args.root = os.path.abspath(args.root)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
