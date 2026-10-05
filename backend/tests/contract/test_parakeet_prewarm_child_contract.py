"""Boot pre-reads PARAKEET's files in a low-priority CHILD; Whisper gets no warm-up.

RETARGETED 2026-10-05 (owner decision). This file pinned the faster-whisper
boot warm-up (live 2026-10-04: a cold in-process import ran ~7.5 min and held
Oracle decisions 34-38 s, hence the child). The owner then made Whisper the
FALLBACK only: the first voice command starts Parakeet at the wake word and
waits up to 25 s for it, and the Whisper warm-up once took 22 min under disk
load while the eval gate waited on it. The same rules now hold for the job
that replaced it: a child process at idle CPU / very low I/O priority, no
backend locks, and - new - no model built, only files read.
"""

import inspect
import os

from backend.audio import parakeet_sherpa


def _run_with_fake_child(monkeypatch):
    seen = {}

    class _Proc:
        pid = 0

        def wait(self, timeout=None):
            return 0

    def _popen(args, **kw):
        seen["args"], seen["kw"] = args, kw
        return _Proc()

    monkeypatch.setattr("subprocess.Popen", _popen)
    monkeypatch.setattr(parakeet_sherpa, "model_files_present", lambda: True)
    return parakeet_sherpa.prewarm_files(), seen


def test_prewarm_reads_parakeets_files_in_a_low_priority_child(monkeypatch):
    ok, seen = _run_with_fake_child(monkeypatch)
    assert ok is True
    code = seen["args"][-1]
    assert "import sherpa_onnx" in code and "p.ENCODER" in code
    # files only: no recognizer is built, nothing stays in memory
    assert "build_recognizer" not in code and "OfflineRecognizer" not in code
    if os.name == "nt":
        assert seen["kw"]["creationflags"] & 0x00000040  # IDLE_PRIORITY_CLASS


def test_boot_pre_reads_parakeet_and_never_warms_whisper():
    from backend import main

    src = inspect.getsource(main)
    assert "_delayed_whisper_warm_up" not in src and ".warm_up()" not in src
    body = src[src.index("def _delayed_parakeet_prewarm"):]
    assert "prewarm_files()" in body[:800]
