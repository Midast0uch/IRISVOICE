"""A wake-opened recording reaches the agent only if the wake clip holds the name.

Before (live 2026-10-24, headless, no UI connected): the wake head fired on TV
speech 3 s after boot (peak 0.614 vs bar 0.555). The recording it opened sent
"Now, Miss, Miss, Miss, Miss, I'll just get Tommy not settled in in the second
half." to the agent as a task (thread voice_headless): list_directory,
read_file, an episode with outcome success in data/memory.db. Nothing between
the fire and the task asked whether "Hey Iris" was said.

Now the wake entry (main._on_wake_word_async) asks for wake_confirm; the
handler transcribes the clip that made the detector fire and drops the take
unless the clip holds the name. Measured on the 316 saved fires
(logs/wake_triggers/): 12 accepted, all the owner; 0 of ~304 TV/room fires.

Run: python -m pytest backend/tests/contract/test_wake_confirm_contract.py -q
"""
from __future__ import annotations

import ast
import pathlib
import threading

import numpy as np

from backend.audio.voice_command import VoiceCommandHandler

_ROOT = pathlib.Path(__file__).resolve().parents[3]

_TV_CLIP = np.full(16000, 0.11, dtype=np.float32)    # what the detector fired on
_OWNER_CLIP = np.full(16000, 0.22, dtype=np.float32)

# Recorded transcripts (whisper tiny on the real clips / the live STT finals).
_CLIP_TEXT = {0.11: "Now, Miss, Miss, Miss, Miss, I'll just get Tommy not settled in",
              0.22: "Hey, Iris."}
_TV_REQUEST = "I'm going to push him call a play, actually. That's the cup."
_OWNER_REQUEST = "What time is it?"


class _Seg:
    def __init__(self, text):
        self.text = text


class _Whisper:
    """Transcribes a clip by its marker value; the request goes through Phonon-2."""

    def transcribe(self, audio, **_kw):
        return [_Seg(_CLIP_TEXT.get(round(float(audio[0]), 2), ""))], None


class _Phonon2:
    def __init__(self, text):
        self._text = text
        self.last_error = None

    @property
    def active(self):
        return True

    def begin_utterance(self, _cb):
        pass

    def feed_frame(self, _a):
        pass

    def finish(self, timeout=12.0):
        return self._text

    def last_timing(self):
        return {"first_partial_s": 0.5, "final_s": 0.9}

    def abort(self):
        pass


class _Engine:
    pipeline = object()

    def __init__(self, clip):
        self._clip = clip

    def register_frame_listener(self, _fn):
        pass

    def take_wake_clip(self):
        clip, self._clip = self._clip, None
        return clip


def _take(clip, request_text, wake_confirm):
    """One real start_recording -> _run_transcription take; return the transcript sent on."""
    h = VoiceCommandHandler(_Engine(clip))
    h._whisper = _Whisper()
    h._phonon2 = _Phonon2(request_text)
    h._phonon2_warm_up = lambda: None

    def _vad():
        h._raw_frames = [np.full(16000, 0.2, dtype=np.float32)]
        return True

    h._vad_wait_for_speech_then_silence = _vad
    got, done = [], threading.Event()
    h._on_command_result = lambda r: (got.append(r["transcript"]), done.set())
    h.set_active_session("voice_headless")
    kw = {"wake_confirm": True} if wake_confirm else {}
    assert h.start_recording(auto_stop=True, pre_speech_timeout_sec=8.0, play_beep=False, **kw)
    assert done.wait(10.0), "the take never reported a result"
    h._cancel_idle_timer()
    return got[0]


def test_tv_speech_after_a_false_wake_fire_never_becomes_a_task():
    assert _take(_TV_CLIP, _TV_REQUEST, wake_confirm=True) == ""


def test_a_real_hey_iris_still_sends_the_request():
    assert _take(_OWNER_CLIP, _OWNER_REQUEST, wake_confirm=True) == _OWNER_REQUEST


def test_a_wake_take_with_no_clip_is_rejected():
    assert _take(None, _TV_REQUEST, wake_confirm=True) == ""


def test_double_click_and_relisten_takes_are_not_gated():
    assert _take(None, _OWNER_REQUEST, wake_confirm=False) == _OWNER_REQUEST


def test_the_wake_word_entry_asks_for_the_confirm():
    tree = ast.parse((_ROOT / "backend" / "main.py").read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.AsyncFunctionDef) and n.name == "_on_wake_word_async")
    calls = [c for c in ast.walk(fn) if isinstance(c, ast.Call)
             and getattr(c.func, "attr", "") == "_handle_voice"]
    assert calls, "_on_wake_word_async no longer routes to _handle_voice"
    for c in calls:
        kw = {k.arg: k.value for k in c.keywords}
        assert isinstance(kw.get("wake_confirm"), ast.Constant) and kw["wake_confirm"].value is True
