"""Loading Whisper never imports ctranslate2's converters/specs (torch, transformers).

Before: `from faster_whisper import WhisperModel` -> ctranslate2/__init__ ->
converters + specs -> `import torch`, `import transformers` (only for model
conversion). Cold on this HDD the chain ran ~19 min in the backend's warm-up
thread (stack dumps 2026-10-03 11:04 -> 11:23) and overlapped two live turns:
personal run 1 (600 s, no answer) and the developer run (226 s), while the
run after it finished took 58 s.

Now `_get_whisper` registers empty `ctranslate2.converters` / `.specs` first.
"""

import sys
import types

from backend.audio.voice_command import VoiceCommandHandler


def test_get_whisper_registers_the_conversion_stubs_before_the_import(monkeypatch):
    for name in [m for m in sys.modules if m == "ctranslate2" or m.startswith("ctranslate2.")]:
        monkeypatch.delitem(sys.modules, name)
    seen = {}

    class _Whisper:
        def __init__(self, *a, **k):
            # what the real faster_whisper import would find at this point
            seen["stubs"] = {n: sys.modules.get(n) for n in ("ctranslate2.converters",
                                                              "ctranslate2.specs")}

    monkeypatch.setitem(sys.modules, "faster_whisper", types.SimpleNamespace(WhisperModel=_Whisper))
    h = VoiceCommandHandler.__new__(VoiceCommandHandler)
    h._whisper, h._whisper_loading = None, False
    import threading

    h._whisper_lock = threading.Lock()
    assert isinstance(h._get_whisper(), _Whisper)
    for name, mod in seen["stubs"].items():
        assert isinstance(mod, types.ModuleType) and not hasattr(mod, "TransformersConverter"), name
    for name in ("ctranslate2.converters", "ctranslate2.specs"):
        monkeypatch.delitem(sys.modules, name)
