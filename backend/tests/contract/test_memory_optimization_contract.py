"""Contract tests for the backend memory-optimization guards (REQ-1, REQ-5).

Pins the process-level memory-isolation contracts introduced by the
backend-memory-optimization spec:

  * REQ-5 AC5.1: ``backend/audio/tts_worker.py`` sets ``CUDA_VISIBLE_DEVICES=""``
    BEFORE any import that could transitively load torch, so the CPU-only
    Pocket-TTS worker never initialises a CUDA runtime.
  * REQ-5 AC5.3: the TTS worker trims its working set after model load.
  * REQ-1 AC1.2 / REQ-6 AC6.1: ``VoiceCommandHandler.__init__`` does NOT eagerly
    call ``warm_up()`` / ``_phonon2_warm_up()`` — Phonon-2 and faster-whisper
    load lazily on first use (JIT), eliminating the boot-time 4.2 GB footprint.
    (Parakeet was the original STT engine; it is retired, commit c9a967e0.)
  * REQ-1: ``phonon2_stream.py`` has an idle-exit watchdog (``_IDLE_EXIT_S``) so
    the fermion server is stopped after 20 min idle.

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
    # Updated 2026-11-09: Parakeet STT was deleted (commit c9a967e0; voice_command.py says
    # ParakeetTranscriber is retired), so `_ensure_loaded` no longer exists and `_phonon2_warm_up`
    # is the Phonon-2 twin of the old eager warm-up call. Same intent as before: __init__ may
    # CONSTRUCT the Phonon-2 client but must not START it (no eager server spawn).
    assert not any(
        line.strip().startswith("self._phonon2_warm_up()") for line in init_lines
    ), "VoiceCommandHandler.__init__ must not eagerly call _phonon2_warm_up()"
    assert any(
        line.strip().startswith("self._phonon2 = Phonon2StreamClient()") for line in init_lines
    ), "VoiceCommandHandler.__init__ must construct the Phonon2StreamClient"
    # Constructing the client starts nothing: its __init__ only sets state. The server is spawned
    # by begin_utterance/_ServerManager.ensure, never by the constructor.
    p2 = _read("backend/audio/phonon2_stream.py")
    c_start = p2.find("class Phonon2StreamClient")
    assert c_start != -1, "Phonon2StreamClient class not found"
    c_init = p2.find("def __init__", c_start)
    c_end = p2.find("\n    def ", c_init + 1)
    c_body = p2[c_init:c_end if c_end != -1 else len(p2)]
    for started in ("ensure(", "ensure_server(", "Thread(", ".start(", "begin_utterance(", "Popen("):
        assert started not in c_body, (
            "Phonon2StreamClient.__init__ must not start anything (found %r)" % started
        )


def test_stt_worker_idle_exit():
    """REQ-1: the STT worker (Phonon-2 fermion server) has an idle-exit watchdog.

    Renamed from test_parakeet_worker_offline_and_idle_exit (2026-11-09): backend/audio/
    parakeet_worker.py is deleted with Parakeet (commit c9a967e0). The idle exit now lives in
    phonon2_stream.py (`_IDLE_EXIT_S`, `_start_idle_watchdog_locked`). The old HF_HUB_OFFLINE,
    `shutting_down` and `_mark_idle_shutdown` checks are dropped: nothing in the Phonon-2 path
    sets or emits them (grep of backend/audio finds no HF_HUB_OFFLINE; the fermion server is a
    separate exe that the manager just terminates), so there is nothing to pin."""
    src = _read("backend/audio/phonon2_stream.py")
    assert "_IDLE_EXIT_S" in src, "phonon2_stream.py must define an idle-exit timeout"
    assert "def _start_idle_watchdog_locked" in src, "phonon2_stream.py must define the idle watchdog"
    # The idle exit must be wired, not just defined: ensure() starts the watchdog ...
    assert "self._start_idle_watchdog_locked()" in src, (
        "the idle watchdog must be started by _ServerManager.ensure"
    )
    # ... the watchdog compares idle time to the timeout and stops the server process ...
    w_start = src.find("def _start_idle_watchdog_locked")
    w_end = src.find("\n    def ", w_start + 1)
    watch = src[w_start:w_end if w_end != -1 else len(src)]
    assert "idle > _IDLE_EXIT_S" in watch, "the watchdog must compare idle time to _IDLE_EXIT_S"
    assert "proc.terminate()" in watch, "the watchdog must stop the idle server process"
    # ... and activity resets the clock so a live app is not stopped (live 2026-10-16).
    assert "def touch" in src and "self._last_activity = time.monotonic()" in src, (
        "touch() must record activity for the idle watchdog"
    )