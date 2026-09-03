"""MediaSource — the entry point of the media pipeline "black box".

Point IRIS at ANY media and get a local file path back:
  - local file path  -> passed through (validated to exist)
  - http(s) URL      -> downloaded to a temp file (yt-dlp for YouTube,
                        urllib for direct links)

The analysis tools (transcribe_media / analyze_video_frames / clip_video)
only understand local files, so every media request funnels through
``resolve_media_source`` first. This is what makes "point vision + Parakeet
at any media" work — the source is normalized before analysis.
"""
from __future__ import annotations

import logging
import os
import tempfile
import urllib.parse
import urllib.request

logger = logging.getLogger(__name__)

_YT_DLP_AVAILABLE = False
try:
    import yt_dlp  # type: ignore

    _YT_DLP_AVAILABLE = True
except Exception:  # pragma: no cover - optional dependency
    pass


class MediaSource:
    """Normalizes a media reference (local path or URL) to a local file path."""

    def __init__(self, uri: str):
        self.uri = uri
        self.local_path: str | None = None

    def is_url(self) -> bool:
        return urllib.parse.urlparse(self.uri).scheme in ("http", "https")

    def resolve(self) -> str:
        """Return a local filesystem path for this media source.

        Local paths are validated and passed through. URLs are downloaded to a
        temp file. Raises FileNotFoundError / RuntimeError on failure.
        """
        if not self.is_url():
            if not os.path.exists(self.uri):
                raise FileNotFoundError(f"media source not found: {self.uri}")
            self.local_path = self.uri
            return self.local_path
        self.local_path = self._download(self.uri)
        return self.local_path

    def _download(self, url: str) -> str:
        if _YT_DLP_AVAILABLE and ("youtube.com" in url or "youtu.be" in url):
            return self._download_yt(url)
        suffix = os.path.splitext(urllib.parse.urlparse(url).path)[1] or ".tmp"
        fd, path = tempfile.mkstemp(suffix=suffix, prefix="iris_media_")
        os.close(fd)
        try:
            urllib.request.urlretrieve(url, path)
        except Exception as exc:  # noqa: BLE001
            os.unlink(path)
            raise RuntimeError(f"download failed: {exc}") from exc
        return path

    def _download_yt(self, url: str) -> str:
        out_tmpl = os.path.join(tempfile.gettempdir(), "iris_media_%(id)s.%(ext)s")
        ydl_opts = {
            "outtmpl": out_tmpl,
            "format": "best[ext=mp4]/best",
            "quiet": True,
        }
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:  # type: ignore[attr-defined]
                ydl.download([url])
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"yt-dlp download failed: {exc}") from exc
        matches = [
            os.path.join(tempfile.gettempdir(), f)
            for f in os.listdir(tempfile.gettempdir())
            if f.startswith("iris_media_") and not f.endswith(".part")
        ]
        if not matches:
            raise RuntimeError("yt-dlp produced no output file")
        return sorted(matches, key=os.path.getmtime)[-1]

    def cleanup(self) -> None:
        """Remove a downloaded temp file (call after use for URL sources)."""
        if self.local_path and self.is_url() and os.path.exists(self.local_path):
            try:
                os.unlink(self.local_path)
            except Exception:  # noqa: BLE001
                pass


def resolve_media_source(uri: str) -> str:
    """Convenience wrapper: resolve a URI/path to a local file path."""
    return MediaSource(uri).resolve()
