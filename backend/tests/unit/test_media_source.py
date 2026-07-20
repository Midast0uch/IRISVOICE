"""Tests for the media-pipeline 'black box' entry point: MediaSource.

These verify the source-normalization layer (local passthrough, missing-file
error, URL download) WITHOUT requiring ffmpeg/Parakeet/vision — those are the
downstream analysis tools, not the abstraction under test.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from backend.agent.media_source import MediaSource, resolve_media_source  # noqa: E402


def _write_tmp(content=b"dummy media", suffix=".txt"):
    fd, path = tempfile.mkstemp(suffix=suffix, prefix="iris_test_media_")
    os.write(fd, content)
    os.close(fd)
    return path


def test_local_file_passthrough():
    p = _write_tmp()
    try:
        src = MediaSource(p)
        assert src.is_url() is False
        assert src.resolve() == p
    finally:
        os.unlink(p)


def test_missing_local_file_raises():
    src = MediaSource("C:\\nonexistent\\iris_media_xyz.mp4")
    assert src.is_url() is False
    try:
        src.resolve()
        assert False, "expected FileNotFoundError"
    except FileNotFoundError:
        pass


def test_url_is_detected():
    src = MediaSource("https://example.com/clip.mp4")
    assert src.is_url() is True


def test_resolve_media_source_helper():
    p = _write_tmp()
    try:
        assert resolve_media_source(p) == p
    finally:
        os.unlink(p)


def test_url_download_direct(monkeypatch):
    """A direct http URL is downloaded to a temp file via urllib."""
    import backend.agent.media_source as ms

    downloaded = {}

    def fake_urlretrieve(url, path):
        downloaded["url"] = url
        with open(path, "wb") as f:
            f.write(b"fake video bytes")

    monkeypatch.setattr(ms.urllib.request, "urlretrieve", fake_urlretrieve)
    src = MediaSource("https://example.com/clip.mp4")
    out = src.resolve()
    try:
        assert os.path.exists(out)
        assert downloaded["url"] == "https://example.com/clip.mp4"
        # cleanup removes the downloaded temp file
        src.cleanup()
        assert not os.path.exists(out)
    finally:
        if os.path.exists(out):
            os.unlink(out)
