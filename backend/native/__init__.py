"""
Native C++ audio playback layer — optional acceleration for TTS output.

Graceful fallback: if the compiled extension is not available, this module
silently exports None and the AudioPipeline continues using sounddevice.
"""

try:
    from .iris_audio import IrisAudioPlayer
    NATIVE_AVAILABLE = True
except ImportError:
    NATIVE_AVAILABLE = False
    IrisAudioPlayer = None

__all__ = ["IrisAudioPlayer", "NATIVE_AVAILABLE"]
