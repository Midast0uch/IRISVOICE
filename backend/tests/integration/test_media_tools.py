"""Tests for the multimedia tools (Phase 5.2 / research D2).

Heavy I/O (ffmpeg, Parakeet HTTP, vision) is mocked/injected so the logic is
verified without external services.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import backend.tools.media_tools as mt


def test_transcribe_media_chunks_and_concatenates(tmp_path, monkeypatch):
    fake_pcm = tmp_path / "a.pcm"
    fake_pcm.write_bytes(b"PCMDATA")
    monkeypatch.setattr(mt, "_chunk_audio", lambda p, c=55: [fake_pcm])

    calls = []

    def fake_transcribe(data, url):
        calls.append((data, url))
        return {"text": "hello world", "language": "en", "duration_s": 5.0}

    res = mt.transcribe_media("ignored.wav", transcribe=fake_transcribe)
    assert res["success"] is True
    assert res["text"] == "hello world"
    assert res["language"] == "en"
    assert res["duration_s"] == 5.0
    assert calls[0][0] == b"PCMDATA"
    assert calls[0][1] == mt.PARAKEET_URL


def test_transcribe_media_requires_path():
    assert mt.transcribe_media("")["success"] is False


def test_transcribe_media_handles_chunking_failure(monkeypatch):
    def boom(_p, _c=55):
        raise RuntimeError("ffmpeg missing")

    monkeypatch.setattr(mt, "_chunk_audio", boom)
    res = mt.transcribe_media("x.wav")
    assert res["success"] is False
    assert "chunking" in res["error"]


def test_analyze_video_frames_aggregates(tmp_path, monkeypatch):
    fake_frame = tmp_path / "f.png"
    fake_frame.write_bytes(b"FRAMEBYTES")
    monkeypatch.setattr(mt, "_extract_frames", lambda p, fi=1.0: [fake_frame])

    calls = []

    def fake_analyze(data, question):
        calls.append((data, question))
        return "a cat on a chair"

    res = mt.analyze_video_frames(
        "vid.mp4", question="describe", frame_interval=1.0, analyze=fake_analyze
    )
    assert res["success"] is True
    assert res["frame_count"] == 1
    assert res["answers"] == ["a cat on a chair"]
    assert "a cat on a chair" in res["summary"]
    assert calls[0][1] == "describe"


def test_analyze_video_frames_requires_path():
    assert mt.analyze_video_frames("")["success"] is False


def test_clip_video_invokes_ffmpeg(monkeypatch):
    captured = {}

    def fake_run(args, **kwargs):
        captured["args"] = list(args)
        return None

    monkeypatch.setattr(mt.subprocess, "run", fake_run)
    res = mt.clip_video("in.mp4", "00:00:01", "00:00:05", "out.mp4")
    assert res["success"] is True
    assert res["output_path"] == "out.mp4"
    assert "ffmpeg" in captured["args"][0]
    assert "out.mp4" in captured["args"]


def test_clip_video_requires_paths():
    assert mt.clip_video("", "0", "1", "")["success"] is False
