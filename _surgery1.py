"""One-shot surgery: delete spawn machinery from lfm_vl_provider.py.

Every cut is verified against anchor text BEFORE anything is written.
Cuts are applied as (start_line, end_line) on the ORIGINAL file, 1-based,
inclusive, removed in one pass. Line numbers were measured at HEAD.
"""

from pathlib import Path

PATH = Path("backend/tools/lfm_vl_provider.py")
lines = PATH.read_text(encoding="utf-8").splitlines(keepends=False)
orig = list(lines)


def expect(idx: int, needle: str) -> None:
    """idx is 1-based original line number; needle must appear on that line."""
    got = lines[idx - 1] if 0 < idx <= len(lines) else "<EOF>"
    if needle not in got:
        raise SystemExit(f"ANCHOR FAIL at line {idx}: wanted {needle!r} got {got!r}")


def expect_blank(idx: int) -> None:
    expect(idx, "")


# ---- verify anchors of every cut region (original coordinates) ------

# C1: vision VRAM/ctx/pid/AV constants block: comment starts 38, ends 68.
expect(38, "# VRAM (GB)")
expect(44, "_VISION_VRAM_RESERVE_GB = 1.0")
expect(53, "_VISION_CTX_SIZE = 4096")
expect(59, "_VISION_SERVER_PID: Optional[int] = None")
expect(68, "_AV_WARM_SLOW_S")
# borrow comment block starts at 71/72 — untouched by C1.

# C2: idle lifecycle 412..605 (ends just before lifecycle broadcast at 607)
expect(412, "Idle lifecycle")
expect(432, "_STAY_WARM_S")
expect(443, "def set_vision_idle_callback")
expect(500, "class VisionLease")
expect(550, "def acquire_vision_lease")
expect(573, "def _prune_expired_leases")
expect(603, "_spawn_lock = threading.Lock()")
expect(604, "_spawn_attempt")
expect(607, "Vision lifecycle broadcast")

# C3: warm helpers 642..676 (ends before blank 677/678 and _stop_owned at 679)
expect(642, "Search-scoped warmth")
expect(653, "def request_warm")
expect(676, "_warm_in_flight = False")
expect(679, "def _stop_owned_vision_server")

# hmm: 677/678 blank check
expect_blank(677)
expect_blank(678)

# C4: kill/av/log-tail helpers 679..845 (next is _idle_stop comment 846/847)
expect(689, "def _kill_process_tree")
expect(714, "def _kill_pid")
expect(727, "def _probe_av_latency")
expect(800, "def _proc_cpu_seconds")
expect(827, "def _read_log_tail")
expect(844, "failed to read stderr log")
expect_blank(845)
expect_blank(846)

# C5: _idle_stop 847..874  (blank 875, singleton 876)
expect(847, "def _idle_stop")
expect(873, "pass")
expect_blank(874)
expect_blank(875)
expect(876, "_lfm_vl_provider_singleton = None")

# C6: vram/ladder/candidates/find_vision_model 961..1325 (keep _find_llama_server_binary 1326)
expect(961, "def _read_free_vram_gb")
expect(1015, "def _estimate_vision_footprint_gb")
expect(1057, "def _configured_vision_ladder")
expect(1087, "def _brain_model_paths")
expect(1122, "def _discover_vision_candidates")
expect(1227, "def _find_vision_model")
expect(1323, "return None")
expect(1326, "def _find_llama_server_binary")

# C7: _compute_vision_gpu_layers 1359..1458 (keep _ensure at 1459)
expect(1359, "def _compute_vision_gpu_layers")
expect(1456, "return 0")
expect_blank(1457)
expect_blank(1458)
expect(1459, "def _ensure_vision_server_running")

# C8: _spawn_vision_server_now 1549..1966 (keep screenshot_to_bytes 1967)
expect(1549, "def _spawn_vision_server_now")
expect(1962, "trigger=_current_trigger")
expect(1964, "return False")
expect_blank(1965)
expect_blank(1966)
expect(1967, "def screenshot_to_bytes")

CUTS = [
    (38, 68),      # C1 constants
    (412, 605),    # C2 idle+lease+spawn-state
    (642, 678),    # C3 warm helpers (incl trailing blanks)
    (679, 846),    # C4 kill/av/log helpers
    (847, 875),    # C5 idle_stop
    (961, 1325),   # C6 vram/ladder/candidates/find
    (1359, 1458),  # C7 gpu layers
    (1549, 1966),  # C8 spawn now
]

keep = set(range(1, len(lines) + 1))
for start, end in CUTS:
    for i in range(start, end + 1):
        keep.discard(i)

new_lines = [lines[i - 1] for i in sorted(keep)]

# sanity: none of the deleted symbols remain referenced in the same file
# (compile check comes later; this is a cheap textual probe)
import re

joined = "\n".join(new_lines)
for sym in (
    "_VISION_SERVER_PID", "_AV_PROBE_BUF", "set_vision_idle_callback",
    "_touch_vision_use", "should_idle_stop", "acquire_vision_lease",
    "VisionLease", "has_active_lease", "_SpawnAttempt", "_spawn_lock",
    "request_warm", "_stop_owned_vision_server", "_kill_process_tree",
    "_kill_pid", "_probe_av_latency", "_proc_cpu_seconds", "_read_log_tail",
    "_idle_stop", "_read_free_vram_gb", "_estimate_vision_footprint_gb",
    "_configured_vision_ladder", "_brain_model_paths",
    "_discover_vision_candidates", "_find_vision_model",
    "_compute_vision_gpu_layers", "_spawn_vision_server_now",
    "_VISION_VRAM_RESERVE_GB", "_VISION_CTX_SIZE", "_VISION_BATCH_SIZE",
):
    hits = [m.start() for m in re.finditer(re.escape(sym), joined)]
    if hits:
        print(f"STILL REFERENCED: {sym} x{len(hits)}")

out = JOINED = joined
PATH.write_text(out + "\n" if not out.endswith("\n") else out, encoding="utf-8")
print("OK wrote", len(new_lines), "lines (was", len(lines), ")")
