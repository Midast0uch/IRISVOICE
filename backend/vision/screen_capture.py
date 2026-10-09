"""
ScreenCapture — Efficient screenshot utilities for vision pipeline.
Uses mss for fast screen capture, with intelligent caching and downscaling.
"""
import base64
import hashlib
import io
import os
import time
from dataclasses import dataclass
from typing import Optional, Tuple, Dict, Any

import numpy as np

# Optional disk persistence for every captured screenshot (2026-08-12).
# Off by default so the hot path stays in-memory; set IRIS_SAVE_SCREENSHOTS=1
# to keep a copy of every capture in <workspace>/screenshots/ (the canonical
# folder AGENTS.md mandates for this project — gitignored). Path is overridable
# via IRIS_SCREENSHOT_DIR. Best-effort: a write failure must never break a
# capture.
_SAVE_SCREENSHOTS = os.environ.get("IRIS_SAVE_SCREENSHOTS", "0") == "1"
_SCREENSHOT_DIR = os.environ.get("IRIS_SCREENSHOT_DIR", "") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "screenshots",
)


def _save_screenshot_to_disk(png_bytes: bytes) -> Optional[str]:
    """Persist a screenshot PNG to the screenshots dir (best-effort)."""
    if not _SAVE_SCREENSHOTS:
        return None
    try:
        os.makedirs(_SCREENSHOT_DIR, exist_ok=True)
        ts = time.strftime("%Y%m%d-%H%M%S")
        path = os.path.join(_SCREENSHOT_DIR, f"screen-{ts}.png")
        with open(path, "wb") as f:
            f.write(png_bytes)
        return path
    except Exception:
        return None  # never break a capture on a write failure


@dataclass(frozen=True)
class CapturedFrame:
    """One capture with its GEOMETRY (REQ-5 AC5.4/AC5.5,
    specs/oracle-native-decision-surface AC13.1).

    Any consumer that maps an image-space point back to a screen pixel
    depends on BOTH numbers, measured not guessed:

        screen_x = origin[0] + image_x / scale
        screen_y = origin[1] + image_y / scale

    ``scale`` is image px per SCREEN px (1.0 when no downscale ran, <
    1.0 when the image was resized to ``max_width``). ``origin`` is the
    captured monitor/region's (left, top) in screen pixels - physical pixels
    are what mss returns, and NO display-scaling (DPR) assumption is made
    (AC5.5). ``capture_base64`` keeps its historical 2-tuple for its existing
    callers; this dataclass is the additive shape (AC13.1).
    """

    b64: str
    is_new: bool
    scale: float
    origin: Tuple[int, int]


class ScreenCapture:
    """
    Manages screen capture for the vision pipeline.
    Features:
    - Fast capture via mss
    - Automatic downscaling for model input
    - Change detection (pixel diff hashing)
    - Base64 encoding for API transport
    """

    _instance: Optional["ScreenCapture"] = None
    _initialized: bool = False

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, max_width: int = 1280, quality: int = 85):
        if ScreenCapture._initialized:
            return

        self.max_width = max_width
        self.quality = quality

        # Lazy-loaded dependencies
        self._mss = None
        self._pil_available = False

        # Cache to avoid duplicate screenshots
        self._last_hash: Optional[str] = None
        self._last_b64: Optional[str] = None
        self._last_capture_time: float = 0
        self._last_scale: float = 1.0     # geometry of the cached frame (AC5.4)
        self._last_origin: Tuple[int, int] = (0, 0)
        self._cache_ttl: float = 0.5  # seconds

        ScreenCapture._initialized = True

    def _ensure_deps(self):
        """Lazy-load dependencies on first use."""
        if self._mss is None:
            try:
                import mss
                self._mss = mss.mss()
            except ImportError:
                raise RuntimeError("mss is required: pip install mss")
        try:
            from PIL import Image  # noqa: F401
            self._pil_available = True
        except ImportError:
            self._pil_available = False

    def capture_base64(
        self,
        monitor_index: int = 0,
        force: bool = False,
        region: Optional[Tuple[int, int, int, int]] = None,
    ) -> Tuple[str, bool]:
        """
        Capture screen and return as base64 PNG string.

        Args:
            monitor_index: Which monitor to capture (0 = all combined)
            force: Skip cache and capture fresh
            region: Optional (left, top, width, height) crop region

        Returns:
            Tuple of (base64_string, is_new_capture)
            is_new_capture is False if the cached version was returned
        """
        frame = self.capture_frame(
            monitor_index=monitor_index, force=force, region=region)
        return frame.b64, frame.is_new

    def capture_frame(
        self,
        monitor_index: int = 0,
        force: bool = False,
        region: Optional[Tuple[int, int, int, int]] = None,
    ) -> CapturedFrame:
        """Capture and return the frame WITH its geometry (AC5.4).

        Same capture/cache/downscale behaviour as ``capture_base64`` - the
        scale factor between image pixels and screen pixels is MEASURED at
        resize time and returned (it used to be computed at the resize and
        dropped), along with the captured region's screen origin. Both are
        what a future image-point -> screen-pixel mapper needs (AC5.5: no DPR
        assumption; mss pixels are physical).
        """
        self._ensure_deps()

        # Check cache
        now = time.time()
        if (
            not force
            and self._last_b64
            and (now - self._last_capture_time) < self._cache_ttl
        ):
            return CapturedFrame(
                self._last_b64, False, self._last_scale, self._last_origin)

        # Capture
        if region:
            monitor = {
                "left": region[0],
                "top": region[1],
                "width": region[2],
                "height": region[3],
            }
        else:
            monitor = self._mss.monitors[monitor_index]

        origin = (int(monitor["left"]), int(monitor["top"]))
        raw = self._mss.grab(monitor)
        scale = 1.0

        if self._pil_available:
            from PIL import Image

            img = Image.frombytes("RGB", (raw.width, raw.height), raw.rgb)

            # Downscale if wider than max_width
            if img.width > self.max_width:
                ratio = self.max_width / img.width
                new_h = int(img.height * ratio)
                img = img.resize((self.max_width, new_h), Image.LANCZOS)
                scale = ratio  # measured: image px per screen px (AC5.4)

            # Encode to PNG bytes
            buf = io.BytesIO()
            img.save(buf, format="PNG", optimize=True)
            png_bytes = buf.getvalue()
        else:
            # Fallback: raw PNG bytes via mss (no resize)
            from mss.tools import to_png
            png_bytes = to_png(raw.rgb, raw.size)

        # Hash for change detection
        img_hash = hashlib.md5(png_bytes).hexdigest()

        # Optional disk persistence (IRIS_SAVE_SCREENSHOTS=1) — best-effort,
        # off the hot path, never raises.
        _save_screenshot_to_disk(png_bytes)

        if img_hash == self._last_hash and self._last_b64:
            self._last_capture_time = now
            return CapturedFrame(self._last_b64, False, scale, origin)

        b64 = base64.b64encode(png_bytes).decode("utf-8")

        # Update cache
        self._last_hash = img_hash
        self._last_b64 = b64
        self._last_capture_time = now
        self._last_scale = scale
        self._last_origin = origin

        return CapturedFrame(b64, True, scale, origin)

    def capture_pil(
        self,
        monitor_index: int = 0,
        region: Optional[Tuple[int, int, int, int]] = None,
    ):
        """Capture screen and return as PIL Image."""
        self._ensure_deps()
        if not self._pil_available:
            raise RuntimeError("Pillow is required: pip install Pillow")

        from PIL import Image

        if region:
            monitor = {
                "left": region[0],
                "top": region[1],
                "width": region[2],
                "height": region[3],
            }
        else:
            monitor = self._mss.monitors[monitor_index]

        raw = self._mss.grab(monitor)
        img = Image.frombytes("RGB", (raw.width, raw.height), raw.rgb)

        if img.width > self.max_width:
            ratio = self.max_width / img.width
            new_h = int(img.height * ratio)
            img = img.resize((self.max_width, new_h), Image.LANCZOS)

        return img

    def has_screen_changed(self) -> bool:
        """Check if the screen content has changed since last capture."""
        _, is_new = self.capture_base64(force=True)
        return is_new

    def get_status(self) -> Dict[str, Any]:
        """Get capture module status."""
        return {
            "initialized": self._mss is not None,
            "max_width": self.max_width,
            "pil_available": self._pil_available,
            "last_capture_time": self._last_capture_time,
            "cache_ttl": self._cache_ttl,
        }

    def cleanup(self):
        """Release resources."""
        if self._mss:
            self._mss.close()
            self._mss = None
        self._last_b64 = None
        self._last_hash = None


def get_screen_capture() -> ScreenCapture:
    """Get the singleton ScreenCapture instance."""
    return ScreenCapture()
