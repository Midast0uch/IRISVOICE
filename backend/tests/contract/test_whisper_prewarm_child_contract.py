"""The Whisper import is read into the file cache by a low-priority CHILD first.

Live 2026-10-04 (after a sleep, cold HDD): the in-process faster_whisper
import ran ~7.5 min inside the backend, overlapped a developer turn and a
personal turn, and Oracle decisions on the answer path waited 34-38 s. The
idle check runs once, BEFORE the import; a turn that starts a second later
still collides. Now the boot warm-up first runs the same import in a child
process (idle CPU class, very low I/O priority, no backend locks), then waits
for idle again; the in-process import is then seconds.
"""

import inspect
import os

from backend.audio import voice_command
from backend.audio.voice_command import VoiceCommandHandler


def test_prewarm_runs_the_stubbed_import_in_a_low_priority_child(monkeypatch):
    seen = {}

    class _Proc:
        pid = 0

        def wait(self, timeout=None):
            return 0

    def _popen(args, **kw):
        seen["args"], seen["kw"] = args, kw
        return _Proc()

    monkeypatch.setattr("subprocess.Popen", _popen)
    assert VoiceCommandHandler.prewarm_files() is True
    code = seen["args"][-1]
    assert "import faster_whisper" in code
    for mod in voice_command._CT2_CONVERSION_MODULES:
        assert mod in code
    if os.name == "nt":
        assert seen["kw"]["creationflags"] & 0x00000040  # IDLE_PRIORITY_CLASS


def test_boot_warm_up_prewarms_files_before_the_in_process_import():
    from backend import main

    src = inspect.getsource(main)
    body = src[src.index("def _delayed_whisper_warm_up"):]
    assert body.index("prewarm_files()") < body.index("_handler.warm_up()")
