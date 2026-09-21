"""Contract: the vision provider contains NO spawn surface.

REQ-1/REQ-2 of specs/vision-single-server: tier 3 borrows an already-running
multimodal server; it never spawns one. The standalone llama-server spawn path
(~1300 lines: _spawn_vision_server_now, single-flight lock, owned-PID
tracking, idle watchdog, VRAM ladders) is REMOVED by this spec, and this guard
makes its return impossible: the module must contain none of the spawn
symbols and must not start a subprocess at all.

AST-shaped, not substring-shaped: docstrings and comments may mention the
history freely; only real code (imports, calls, attribute references,
assignments) trips this guard.
"""

import ast
from pathlib import Path

_LFM = Path(__file__).resolve().parents[2] / "tools" / "lfm_vl_provider.py"

# Symbols that existed ONLY to spawn/manage an IRIS-owned llama-server.
_SPAWN_GLOBALS = (
    "_spawn_vision_server_now",
    "_spawn_attempt",
    "_spawn_lock",
    "_SpawnAttempt",
    "request_warm",
    "_VISION_SERVER_PID",
    "_stop_owned_vision_server",
    "_kill_process_tree",
    "_probe_av_latency",
    "_proc_cpu_seconds",
    "_read_log_tail",
    "_idle_stop",
    "should_idle_stop",
    "set_vision_idle_callback",
    "_touch_vision_use",
    "_read_free_vram_gb",
    "_estimate_vision_footprint_gb",
    "_configured_vision_ladder",
    "_brain_model_paths",
    "_discover_vision_candidates",
    "_find_vision_model",
    "_compute_vision_gpu_layers",
)


def _tree() -> ast.Module:
    return ast.parse(_LFM.read_text(encoding="utf-8"))


def test_no_spawn_symbols_defined():
    tree = _tree()
    defined = {
        n.name
        for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }
    assigned = {
        t.id
        for n in ast.walk(tree)
        if isinstance(n, ast.Assign)
        for t in n.targets
        if isinstance(t, ast.Name)
    }
    annassigned = {
        n.target.id
        for n in ast.walk(tree)
        if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name)
    }
    present = defined | assigned | annassigned
    offenders = sorted(s for s in _SPAWN_GLOBALS if s in present)
    assert not offenders, f"spawn surface still defined: {offenders}"


def test_no_subprocess_calls():
    tree = _tree()
    for n in ast.walk(tree):
        if not isinstance(n, ast.Call):
            continue
        f = n.func
        name = ""
        if isinstance(f, ast.Attribute):
            attr = f
            parts = []
            while isinstance(attr, ast.Attribute):
                parts.append(attr.attr)
                attr = attr.value
            if isinstance(attr, ast.Name):
                parts.append(attr.id)
            name = ".".join(reversed(parts))
        elif isinstance(f, ast.Name):
            name = f.id
        assert "Popen" not in name, "vision provider must never spawn a process"


def test_no_subprocess_or_signal_import():
    tree = _tree()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            assert not any(a.name in ("subprocess", "signal") for a in n.names), (
                "spawn-era stdlib import still present"
            )


def test_borrow_surface_intact():
    """The tier-3 path is discovery ONLY. These must keep existing."""
    tree = _tree()
    defined = {
        n.name
        for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }
    required = {
        "_discover_reusable_vision_server",
        "_ensure_vision_server_running",
        "_probe_vision_capability",
        "_model_is_multimodal",
        "LFMVLProvider",
        "LFMVLConfig",
        "VisionModelUnavailable",
        "_fail_vision_unavailable",
        "get_lfm_vl_provider",
        "_find_llama_server_binary",  # shared with embedding_sidecar, generic
    }
    missing = required - defined
    assert not missing, f"borrow surface broken: {missing}"
