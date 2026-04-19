"""
AudioPipeline - Manages audio input/output streams using sounddevice
"""
import threading
import queue
import logging
from typing import Optional, Callable, List

logger = logging.getLogger(__name__)
import numpy as np

# sounddevice (PortAudio) is imported lazily inside methods to avoid loading the
# PortAudio DLL at backend startup. On Windows, PortAudio can take 200-2000 ms
# to initialize when there are many audio devices, USB audio, or Bluetooth audio.
# The import cost is only paid when the audio pipeline first starts (user action).
def _sd():
    """Lazy accessor for sounddevice — loads PortAudio on first audio use."""
    import sounddevice as _sounddevice
    return _sounddevice


class AudioPipeline:
    """
    Manages real-time audio I/O:
    - Input stream from microphone
    - Output stream to speakers
    - Audio buffering for inference
    """
    
    def __init__(
        self,
        input_device: Optional[int] = None,
        output_device: Optional[int] = None,
        sample_rate: int = 16000,
        frame_length: int = 512,
        channels: int = 1
    ):
        self.input_device = input_device
        self.output_device = output_device
        self.sample_rate = sample_rate
        self.frame_length = frame_length
        self.channels = channels
        
        # Streams
        self._input_stream = None
        self._output_stream = None
        
        # Callback
        self._on_audio_frame: Optional[Callable[[np.ndarray], None]] = None
        
        # State
        self._is_running = False
        
        # Audio buffer for speech collection
        self._audio_buffer: List[np.ndarray] = []
        self._buffer_lock = threading.Lock()
        
        # Frame listeners for unified audio access
        self._frame_listeners: List[Callable[[np.ndarray], None]] = []
        self._is_buffering = False
        
    def start_buffering(self):
        """Starts collecting audio frames into the buffer."""
        with self._buffer_lock:
            self._audio_buffer = []
            self._is_buffering = True
            logger.info("[AudioPipeline] Started buffering audio.")

    def stop_buffering(self) -> np.ndarray:
        """Stops collecting audio frames and returns the buffered audio."""
        with self._buffer_lock:
            self._is_buffering = False
            logger.info("[AudioPipeline] Stopped buffering audio.")
            if not self._audio_buffer:
                return np.array([], dtype=np.float32)
            return np.concatenate(self._audio_buffer)

    def get_buffered_audio(self) -> np.ndarray:
        """Returns the currently buffered audio without stopping the buffering."""
        with self._buffer_lock:
            if not self._audio_buffer:
                return np.array([], dtype=np.float32)
            return np.concatenate(self._audio_buffer)
        
    def add_frame_listener(self, callback: Callable[[np.ndarray], None]):
        """Add a listener for raw audio frames."""
        self._frame_listeners.append(callback)
        
        # Don't print devices on instantiation - slows down startup
        # self._print_input_devices()
        
    def start(self, on_audio_frame: Callable[[np.ndarray], None]) -> bool:
        """Start audio pipeline.

        Input and output streams are started independently so a bad microphone
        device doesn't prevent TTS/beep playback from working.
        """
        self._on_audio_frame = on_audio_frame
        input_ok = False
        output_ok = False

        # --- Input stream (microphone / Porcupine) ---
        try:
            self._input_stream = _sd().InputStream(
                device=self.input_device,
                channels=self.channels,
                samplerate=self.sample_rate,
                callback=self._input_callback,
                blocksize=self.frame_length
            )
            self._input_stream.start()
            input_ok = True
        except Exception as e:
            logger.error(f"[AudioPipeline] Input stream failed: {e}")
            self._input_stream = None

        # --- Output stream (TTS / beep playback) ---
        # Output: use _sd().play() per-chunk instead of a persistent OutputStream.
        # _sd().play() handles device format (mono→stereo), sample rate conversion,
        # and internal buffering automatically — no persistent stream needed.
        # Mark output_ok=True unconditionally; actual device errors surface at play time.
        output_ok = True
        self._output_stream = None  # not used — kept for compatibility checks

        if input_ok or output_ok:
            self._is_running = True
            logger.info(
                f"[AudioPipeline] Started — input={'ok' if input_ok else 'FAILED'}, "
                f"output={'ok' if output_ok else 'FAILED'}"
            )
            return True

        logger.error("[AudioPipeline] Both input and output streams failed — pipeline not running")
        return False
    
    def stop(self):
        """Stop audio pipeline"""
        self._is_running = False
        self.cleanup()
        logger.info("[AudioPipeline] Stopped")
    
    def _input_callback(self, indata, frames, time, status):
        """This is called (from a separate thread) for each audio block."""
        if status:
            logger.debug(f"[AudioPipeline] Input status: {status}")
        if self._is_running:
            # The input data is a numpy array, take the first channel
            audio_frame = indata[:, 0].astype(np.float32)

            # Buffer audio if buffering is enabled
            with self._buffer_lock:
                if self._is_buffering:
                    self._audio_buffer.append(audio_frame)

            # Primary callback (e.g. AudioEngine._process_audio_frame)
            if self._on_audio_frame is not None:
                self._on_audio_frame(audio_frame)

            # Notify all registered frame listeners (e.g. VoiceCommandHandler._capture_frame)
            for listener in self._frame_listeners:
                try:
                    listener(audio_frame)
                except Exception as exc:
                    logger.error(f"[AudioPipeline] Frame listener error: {exc}")
    
    def play_audio(self, audio_data: np.ndarray, sample_rate: int = None):
        """Play audio through the system default output device using _sd().play().

        Uses _sd().play() instead of a persistent OutputStream.write() because:
        - _sd().play() handles mono→stereo upmix, device sample-rate conversion in one step
        - No persistent stream state to manage or get out of sync
        - Blocking=True keeps the threading model simple and gap-free

        Args:
            audio_data:  float32 mono PCM array
            sample_rate: actual rate of audio_data (defaults to self.sample_rate)
        """
        sr = sample_rate if sample_rate is not None else self.sample_rate
        duration_ms = int(len(audio_data) / sr * 1000)
        logger.info(f"[AudioPipeline] play_audio: {len(audio_data)} frames @ {sr}Hz ({duration_ms}ms) → device={self.output_device}")

        try:
            audio_float = audio_data.astype(np.float32)

            # Normalise amplitude — F5-TTS cloned voice can be quiet (~0.05 peak).
            # Target 0.85 peak: loud and clear, safely below hard clip at 1.0.
            peak = np.max(np.abs(audio_float))
            if peak > 1e-6:
                audio_float = audio_float * (0.85 / peak)
            audio_float = np.clip(audio_float, -1.0, 1.0)

            _sd().play(audio_float, samplerate=sr, device=self.output_device, blocking=True)
            logger.info(f"[AudioPipeline] play_audio: complete ({duration_ms}ms)")
        except Exception as e:
            logger.error(f"[AudioPipeline] Output error: {e}")
    
    def clear_buffer(self):
        """Clear audio buffer"""
        with self._buffer_lock:
            self._audio_buffer.clear()
    
    def remove_frame_listener(self, callback: Callable[[np.ndarray], None]) -> None:
        """Remove a previously registered frame listener."""
        try:
            self._frame_listeners.remove(callback)
        except ValueError:
            pass

    def cleanup(self):
        """Release audio resources"""
        self._frame_listeners.clear()
        if self._input_stream:
            self._input_stream.stop()
            self._input_stream.close()
            self._input_stream = None
        # _output_stream is always None — playback uses _sd().play() per chunk
    
    @staticmethod
    def list_devices() -> List[dict]:
        """List available audio devices, deduplicated across host APIs.

        On Windows, sounddevice (PortAudio) enumerates every physical device
        once per host API (MME, DirectSound, WASAPI, WDM-KS).  This results
        in the same speaker/microphone appearing 3-4 times.  Additionally,
        the MME host API truncates names to ~31 characters while WASAPI and
        WDM show the full name, so exact string matching is insufficient.

        Strategy:
        - Build a list of all devices.
        - For each new device, check if any already-seen device shares the
          same first 31 characters (the MME truncation boundary).  If so,
          merge capabilities and keep the longer (more descriptive) name.
        - Skip system virtual devices (Sound Mapper, Primary Sound Driver)
          that duplicate real defaults.
        """
        _SKIP_PREFIXES = (
            "Microsoft Sound Mapper",
            "Primary Sound Capture Driver",
            "Primary Sound Driver",
        )

        raw_devices = _sd().query_devices()
        # key = first-31-chars of name (lowered), value = merged device dict
        seen: dict[str, dict] = {}

        for i in range(len(raw_devices)):
            info = _sd().query_devices(i)
            name: str = info["name"]
            is_input = info["max_input_channels"] > 0
            is_output = info["max_output_channels"] > 0

            # Skip Windows virtual / mapper devices — they just duplicate the
            # user's default device under a generic name.
            if any(name.startswith(prefix) for prefix in _SKIP_PREFIXES):
                continue

            # Dedup key: first 31 chars lowered (MME truncation boundary)
            key = name[:31].lower().rstrip()

            if key in seen:
                existing = seen[key]
                existing["input"] = existing["input"] or is_input
                existing["output"] = existing["output"] or is_output
                # Keep the longer (more descriptive) version of the name
                if len(name) > len(existing["name"]):
                    existing["name"] = name
                    existing["index"] = i  # prefer the longer-name entry's index
            else:
                seen[key] = {
                    "index": i,
                    "name": name,
                    "input": is_input,
                    "output": is_output,
                    "sample_rate": int(info["default_samplerate"]),
                }

        return list(seen.values())
