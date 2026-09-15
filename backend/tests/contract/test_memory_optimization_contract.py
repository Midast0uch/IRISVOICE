"""Contract tests for the backend memory-optimization guards (REQ-1, REQ-5).

Pins the process-level memory-isolation contracts introduced by the
backend-memory-optimization spec:

  * REQ-5 AC5.1: ``backend/audio/tts_worker.py`` sets ``CUDA_VISIBLE_DEVICES=""``
    BEFORE any import that could transitively load torch, so the CPU-only
    Pocket-TTS worker never initialises a CUDA runtime.
  * REQ-5 AC5.3: the TTS worker trims its working set after model load.
  * REQ-1 AC1.2 / REQ-6 AC6.1: ``VoiceCommandDetector.__init__`` does NOT eagerly
    call ``warm_up()`` / ``_parakeet_warm_up()`` — Parakeet and faster-whisper
    load lazily on first use (JIT), eliminating the boot-time 4.2 GB footprint.
  * REQ-1: ``parakeet_worker.py`` runs offline (``HF_HUB_OFFLINE=1``) and has an
    idle-exit watchdog so the parent can reclaim VRAM/RAM after 20 min idle.

These are source-level contract pins: spawning the real workers would load
multi-GB models, which is exactly what the spec forbids at boot. The assertions
guard the exact code shapes that deliver the memory contract.
"""

from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _read(rel: str) -> str:
    return (_REPO_ROOT / rel).read_text(encoding="utf-8", errors="replace")


def test_tts_worker_masks_cuda_before_torch_import():
    """REQ-5 AC5.1: CUDA_VISIBLE_DEVICES='' is set before any torch import."""
    src = _read("backend/audio/tts_worker.py")
    # The mask must appear before the first torch/pocket_tts import.
    mask_pos = src.find('os.environ["CUDA_VISIBLE_DEVICES"] = ""')
    assert mask_pos != -1, "tts_worker.py must set CUDA_VISIBLE_DEVICES=''"
    torch_import = src.find("import torch")
    pocket_import = src.find("from pocket_tts")
    for imp in (torch_import, pocket_import):
        if imp != -1:
            assert mask_pos < imp, (
                "CUDA_VISIBLE_DEVICES mask must precede the torch/pocket_tts import"
            )


def test_tts_worker_trims_working_set_after_load():
    """REQ-5 AC5.3: the TTS worker compacts its working set post-load."""
    src = _read("backend/audio/tts_worker.py")
    assert "trim_working_set" in src, "tts_worker.py must call trim_working_set()"
    assert "EmptyWorkingSet" in _read("backend/utils/memory_trim.py")


def test_trim_working_set_actually_trims():
    """Session-331 PROVEN-FAILABLE behavioral pin for the trim defect.

    The old contract test only asserted the string ``EmptyWorkingSet`` existed
    in ``memory_trim.py`` — so a SILENT no-op passed. It was: the trim called
    ``EmptyWorkingSet(GetCurrentProcess())`` with the PSEUDO-handle (-1), which
    lacks ``PROCESS_SET_QUOTA``, so the call returned 0 and reclaimed nothing.
    Measured: a 617 MB resident process stayed at 647 MB; with a REAL handle it
    dropped to 1.7 MB.

    This test allocates a large resident buffer, calls the REAL
    ``trim_working_set()``, and asserts the resident set actually shrank — which
    FAILS on the pseudo-handle version and PASSES on the real-handle fix.
    Windows-only (the function is a documented no-op elsewhere)."""
    import sys

    if sys.platform != "win32":
        import pytest

        pytest.skip("working-set trim is Windows-only")

    import psutil

    from backend.utils.memory_trim import trim_working_set

    proc = psutil.Process()
    # Allocate ~400 MB and TOUCH every page so it is genuinely resident.
    blob = bytearray(400 * 1024 * 1024)
    for i in range(0, len(blob), 4096):
        blob[i] = 1
    before_mb = proc.memory_info().rss / (1024 ** 2)
    assert before_mb > 300, f"test setup failed to allocate resident memory ({before_mb:.0f} MB)"

    trim_working_set()

    after_mb = proc.memory_info().rss / (1024 ** 2)
    # A working trim returns most of the touched pages. A no-op leaves them all.
    assert after_mb < before_mb - 200, (
        f"trim_working_set() did not trim (before={before_mb:.0f} MB, "
        f"after={after_mb:.0f} MB) — is it using the pseudo-handle again?"
    )
    _ = blob  # keep the allocation alive so it is not GC'd mid-assertion


def test_voice_command_init_does_not_eagerly_warm_up():
    """REQ-1 AC1.2 / REQ-6 AC6.1: no eager warm_up in VoiceCommandDetector.__init__."""
    src = _read("backend/audio/voice_command.py")
    # Locate the VoiceCommandHandler class's __init__ specifically — the file
    # also contains ParakeetTranscriber.__init__ earlier, which is unrelated.
    cls_pos = src.find("class VoiceCommandHandler")
    assert cls_pos != -1, "VoiceCommandHandler class not found"
    init_start = src.find("def __init__", cls_pos)
    assert init_start != -1, "VoiceCommandHandler.__init__ not found"
    # Scope the scan to the __init__ BODY only: end at the next same-indent
    # method. (A whole-file scan false-positives on the legitimate lazy
    # first-utterance call in _start_recording_locked, REQ-1 AC1.3.)
    init_end = src.find("\n    def ", init_start)
    init_body = src[init_start:init_end if init_end != -1 else len(src)]
    init_lines = init_body.splitlines()
    # Check for actual CALL statements (lines starting with the call), ignoring
    # comment lines that merely explain the removal.
    eager_calls = [
        line.strip()
        for line in init_lines
        if line.strip().startswith("self.warm_up()")
        or line.strip().startswith("self._parakeet_warm_up()")
    ]
    assert not eager_calls, (
        "VoiceCommandHandler.__init__ must not eagerly call warm-up: %r" % eager_calls
    )
    # The lazy spawn path must still exist for first-utterance Parakeet launch.
    assert "def _ensure_loaded" in src, "ParakeetTranscriber._ensure_loaded must exist"


def test_parakeet_worker_offline_and_idle_exit():
    """REQ-1: parakeet_worker runs offline and has an idle-exit watchdog."""
    src = _read("backend/audio/parakeet_worker.py")
    assert 'HF_HUB_OFFLINE' in src, "parakeet_worker.py must set HF_HUB_OFFLINE"
    assert "_IDLE_TIMEOUT_S" in src, "parakeet_worker.py must define an idle timeout"
    assert "shutting_down" in src, "parakeet_worker.py must emit a clean idle shutdown"
    # The parent must treat an idle exit as a clean stop, not a crash.
    vc = _read("backend/audio/voice_command.py")
    assert "_mark_idle_shutdown" in vc, (
        "voice_command.py must handle worker idle-exit as a clean stop"
    )