"""Multimedia tools (Phase 5.2 / research D2).

Three tools that let the agent operate on audio/video:
  - transcribe_media:     chunk audio -> Parakeet /transcribe (localhost:8765) -> text
  - analyze_video_frames: extract frames -> vision analyze_screen per frame -> summary
  - clip_video:           ffmpeg trim wrapper

All heavy I/O (HTTP to Parakeet, ffmpeg subprocess, vision calls) is isolated
behind small injectable helpers so the logic is unit-testable without a live
Parakeet server, ffmpeg binary, or vision model.
"""
from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from typing import Callable, Dict, List, Optional

import httpx

# Parakeet transcribe service (standalone FastAPI, see backend/audio/parakeet_service.py)
PARAKEET_URL = "http://localhost:8765/transcribe"
MAX_CHUNK_SECONDS = 55  # service caps a single request at 60s


# ── ffmpeg helpers ────────────────────────────────────────────────────────────
def _probe_duration(audio_path: str) -> Optional[float]:
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "json", audio_path],
            capture_output=True, text=True, check=True,
        )
        return float(json.loads(out.stdout)["format"]["duration"])
    except Exception:
        return None


def _convert_to_pcm(audio_path: str) -> Path:
    out = Path(tempfile.mktemp(suffix=".pcm"))
    subprocess.run(
        ["ffmpeg", "-y", "-i", audio_path, "-ac", "1", "-ar", "16000",
         "-f", "s16le", str(out)],
        check=True, capture_output=True,
    )
    return out


def _chunk_audio(audio_path: str, chunk_seconds: int = MAX_CHUNK_SECONDS) -> List[Path]:
    """Split audio into <= chunk_seconds mono-16k int16 PCM chunks via ffmpeg."""
    dur = _probe_duration(audio_path)
    if dur is None:
        return [_convert_to_pcm(audio_path)]
    chunks: List[Path] = []
    start = 0.0
    while start < dur:
        out = Path(tempfile.mktemp(suffix=".pcm"))
        subprocess.run(
            ["ffmpeg", "-y", "-ss", str(start), "-t", str(chunk_seconds),
             "-i", audio_path, "-ac", "1", "-ar", "16000", "-f", "s16le", str(out)],
            check=True, capture_output=True,
        )
        chunks.append(out)
        start += chunk_seconds
    return chunks


def _extract_frames(video_path: str, frame_interval: float = 1.0) -> List[Path]:
    """Extract one frame every `frame_interval` seconds via ffmpeg."""
    dur = _probe_duration(video_path) or 0.0
    frames: List[Path] = []
    t = 0.0
    while t < dur:
        out = Path(tempfile.mktemp(suffix=".png"))
        subprocess.run(
            ["ffmpeg", "-y", "-ss", str(t), "-i", video_path, "-frames:v", "1",
             "-q:v", "2", str(out)],
            check=True, capture_output=True,
        )
        if out.exists() and out.stat().st_size > 0:
            frames.append(out)
        t += frame_interval
    if not frames:  # fallback: first frame
        out = Path(tempfile.mktemp(suffix=".png"))
        subprocess.run(
            ["ffmpeg", "-y", "-i", video_path, "-frames:v", "1", "-q:v", "2", str(out)],
            check=True, capture_output=True,
        )
        if out.exists():
            frames.append(out)
    return frames


# ── Parakeet client ───────────────────────────────────────────────────────────
def _transcribe_chunk(chunk_bytes: bytes, url: str = PARAKEET_URL) -> Dict:
    """POST one PCM chunk to Parakeet; returns parsed JSON."""
    resp = httpx.post(
        url, content=chunk_bytes,
        headers={"Content-Type": "application/octet-stream"}, timeout=60,
    )
    resp.raise_for_status()
    return resp.json()


# ── Vision default ────────────────────────────────────────────────────────────
def _default_analyze(frame_bytes: bytes, question: str) -> str:
    """T17: resolve the vision hierarchy (brain -> tool -> VL fallback)
    instead of always constructing LFMVLProvider directly. VisionModelUnavailable
    (REQ-3 AC4, fail loudly) propagates — analyze_video_frames' own try/except
    already turns any exception here into a clean {"success": False, "error": ...}
    result, so no extra handling is needed at this layer."""
    from backend.agent.inference.router import resolve_vision_client
    _resolution, provider = resolve_vision_client()
    return provider.analyze_screen(frame_bytes, question)


# ── Public tools ──────────────────────────────────────────────────────────────
def transcribe_media(
    audio_path: str,
    chunk_seconds: int = MAX_CHUNK_SECONDS,
    transcribe: Callable[[bytes, str], Dict] = _transcribe_chunk,
    url: str = PARAKEET_URL,
) -> Dict:
    """Transcribe an audio/video file via Parakeet, chunking long audio.

    Returns {"success": True, "text": ..., "language": ..., "duration_s": ...}
    or {"success": False, "error": ...}.
    """
    if not audio_path:
        return {"success": False, "error": "audio_path is required"}
    try:
        chunks = _chunk_audio(audio_path, chunk_seconds)
    except Exception as e:
        return {"success": False, "error": f"audio chunking failed: {e}"}
    parts: List[str] = []
    total_dur = 0.0
    lang = None
    try:
        for c in chunks:
            data = c.read_bytes()
            try:
                res = transcribe(data, url)
            finally:
                c.unlink(missing_ok=True)
            if not res.get("text"):
                continue
            parts.append(res["text"])
            total_dur += res.get("duration_s", 0) or 0
            lang = lang or res.get("language")
    except Exception as e:
        return {"success": False, "error": f"transcription failed: {e}"}
    return {
        "success": True,
        "text": " ".join(p.strip() for p in parts if p.strip()),
        "language": lang,
        "duration_s": total_dur,
    }


def analyze_video_frames(
    video_path: str,
    question: str = "What is happening in this frame?",
    frame_interval: float = 1.0,
    analyze: Optional[Callable[[bytes, str], str]] = None,
) -> Dict:
    """Extract frames and run vision analysis on each; aggregate answers."""
    if not video_path:
        return {"success": False, "error": "video_path is required"}
    if analyze is None:
        analyze = _default_analyze
    try:
        frames = _extract_frames(video_path, frame_interval)
    except Exception as e:
        return {"success": False, "error": f"frame extraction failed: {e}"}
    if not frames:
        return {"success": False, "error": "no frames extracted"}
    answers: List[str] = []
    try:
        for f in frames:
            data = f.read_bytes()
            try:
                ans = analyze(data, question)
                if ans:
                    answers.append(ans)
            finally:
                f.unlink(missing_ok=True)
    except Exception as e:
        return {"success": False, "error": f"frame analysis failed: {e}"}
    return {
        "success": True,
        "frame_count": len(frames),
        "answers": answers,
        "summary": "\n".join(f"[{i + 1}] {a}" for i, a in enumerate(answers)),
    }


def clip_video(video_path: str, start: str, end: str, output_path: str) -> Dict:
    """Trim a video using ffmpeg (start/end as HH:MM:SS or seconds)."""
    if not video_path or not output_path:
        return {"success": False, "error": "video_path and output_path are required"}
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-ss", str(start), "-to", str(end),
             "-i", video_path, "-c", "copy", output_path],
            check=True, capture_output=True,
        )
        return {"success": True, "output_path": output_path}
    except Exception as e:
        return {"success": False, "error": f"clip failed: {e}"}
