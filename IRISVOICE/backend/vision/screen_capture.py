"""
ScreenCapture — Efficient screenshot utilities for vision pipeline.
Uses mss for fast screen capture, with intelligent caching and downscaling.
"""
import base64
import hashlib
import io
import time
from typing import Optional, Tuple, Dict, Any

import numpy as np


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
        self._ensure_deps()

        # Check cache
        now = time.time()
        if (
            not force
            and self._last_b64
            and (now - self._last_capture_time) < self._cache_ttl
        ):
            return self._last_b64, False

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

        raw = self._mss.grab(monitor)

        if self._pil_available:
            from PIL import Image

            img = Image.frombytes("RGB", (raw.width, raw.height), raw.rgb)

            # Downscale if wider than max_width
            if img.width > self.max_width:
                ratio = self.max_width / img.width
                new_h = int(img.height * ratio)
                img = img.resize((self.max_width, new_h), Image.LANCZOS)

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

        if img_hash == self._last_hash and self._last_b64:
            self._last_capture_time = now
            return self._last_b64, False

        b64 = base64.b64encode(png_bytes).decode("utf-8")

        # Update cache
        self._last_hash = img_hash
        self._last_b64 = b64
        self._last_capture_time = now

        return b64, True

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
