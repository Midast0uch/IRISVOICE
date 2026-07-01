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
        channels: int = 1,
        echo_cancellation: bool = True,
    ):
        self.input_device = input_device
        self.output_device = output_device
        self.sample_rate = sample_rate
        self.frame_length = frame_length
        self.channels = channels
        # The config exposes echo_cancellation=True, but PortAudio's WASAPI
        # backend on this machine does not actually provide echo cancellation
        # (the flag is a documented no-op without a communications-mode device).
        # Real echo avoidance is done in half-duplex: while TTS is playing, the
        # input callback skips STT buffering and frame-listener forwarding so
        # IRIS's own voice is not captured and fed back into STT. See
        # set_tts_active() and _input_callback().
        self.echo_cancellation = echo_cancellation
        # Half-duplex gate: when True, incoming frames are dropped (TTS is
        # playing through the headphones and would be captured by the mic).
        self._tts_active: bool = False

        # Barge-in energy callback (registered by AudioEngine). Fired ~31Hz
        # from the input callback with frame RMS while TTS is active.
        self._on_barge_in_energy: Optional[Callable[[float], None]] = None

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

        # Native low-latency player — DISABLED.
        # Causes 30-40s blocking on play_audio, audio normalization distortion,
        # and half-duplex gate lock issues. Using sd.play() instead.
        self._native_player = None
        self._native_available = False

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
                blocksize=self.frame_length,
            )
            self._input_stream.start()
            input_ok = True
            logger.info(
                "[AudioPipeline] Input stream started "
                f"(half-duplex TTS gating: {'on' if self.echo_cancellation else 'off'})"
            )
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

        logger.error(
            "[AudioPipeline] Both input and output streams failed — pipeline not running"
        )
        return False

    def stop(self):
        """Stop audio pipeline"""
        self._is_running = False
        self.cleanup()
        logger.info("[AudioPipeline] Stopped")

    def set_tts_active(self, active: bool) -> None:
        """Half-duplex gate: while TTS is playing, drop captured audio frames.

        PortAudio's WASAPI backend on this machine has no real echo
        cancellation, so when IRIS speaks through headphones the mic captures
        its own TTS output. While ``active`` is True, ``_input_callback``
        skips STT buffering and frame-listener forwarding so that feedback is
        never transcribed or buffered. Porcupine wake-word detection is gated
        separately in ``AudioEngine._process_audio_frame`` via the same flag
        propagated through ``AudioEngine.set_tts_active``.
        """
        self._tts_active = bool(active)

    def set_barge_in_energy_callback(
        self, callback: Optional[Callable[[float], None]]
    ) -> None:
        """Register callback fired ~31Hz with frame RMS while TTS is active.

        The callback runs from the PortAudio input thread and receives the
        float32 RMS of each audio frame captured during TTS playback.  The
        AudioEngine uses this to detect user speech and trigger barge-in.

        Pass None to unregister.
        """
        self._on_barge_in_energy = callback

    def _input_callback(self, indata, frames, time, status):
        """This is called (from a separate thread) for each audio block."""
        if status:
            logger.debug(f"[AudioPipeline] Input status: {status}")
        if self._is_running:
            # The input data is a numpy array, take the first channel
            audio_frame = indata[:, 0].astype(np.float32)

            # Half-duplex echo avoidance: while TTS is playing, drop the frame
            # before it reaches STT buffers or frame listeners. The primary
            # callback (AudioEngine._process_audio_frame) is still invoked so
            # the engine's own _tts_active gate can suppress wake-word
            # detection uniformly — but STT capture is blocked here.
            if self._tts_active and self.echo_cancellation:
                # Energy-based barge-in: compute RMS before dropping so the
                # AudioEngine can detect user speech over TTS playback.  The
                # callback fires at ~31Hz from the PortAudio input thread.
                if self._on_barge_in_energy is not None:
                    try:
                        _rms = float(np.sqrt(np.mean(np.square(audio_frame))))
                        self._on_barge_in_energy(_rms)
                    except Exception:
                        pass
                return

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

    def play_stream(self, audio_chunks, sample_rate: int = None,
                     playback_started_event: "threading.Event | None" = None):
        """Stream audio from an iterable of float32 chunks.

        Opens the native player ONCE, pushes every chunk without blocking
        between them (avoiding the gap/choppiness of per-chunk play_audio),
        then waits for all audio to finish before closing.

        Applies a fixed 2.5× gain to compensate for Pocket-TTS's quiet output
        (~0.03 RMS, ~0.37 peak).  Per-chunk peak normalization is NOT used
        because it would amplify near-silent lead-in chunks into loud static.

        Args:
            playback_started_event: Optional threading.Event set when the first
                chunk reaches the audio device.  Callers can wait on this to
                sync word-highlight timing with actual playback start.
        """
        sr = sample_rate if sample_rate is not None else self.sample_rate
        if self._native_available and self._native_player is not None:
            try:
                if not self._native_player.open(self.output_device or -1, sr):
                    raise RuntimeError("Native player failed to open")
                for i, audio_data in enumerate(audio_chunks):
                    audio_float = audio_data.astype(np.float32)
                    # Apply fixed 2.5× gain (Pocket-TTS output is ~0.37 peak).
                    # Clip to [-0.99, 0.99] to prevent wrap-around — do NOT use
                    # per-chunk peak normalization (amplifies silence to static).
                    audio_float = np.clip(audio_float * 2.5, -0.99, 0.99)
                    self._native_player.push_chunk(audio_float)
                    if i == 0 and playback_started_event is not None:
                        playback_started_event.set()
                self._native_player.wait_done()
                self._native_player.close()
                return
            except Exception as _native_err:
                logger.warning(
                    f"[AudioPipeline] Native stream failed ({_native_err}), falling back"
                )

        # Fallback: concatenate all chunks, apply same 2.5× gain + clip
        # as the native path for consistent volume across both paths.
        all_audio = np.concatenate(list(audio_chunks))
        audio_float = np.clip(all_audio.astype(np.float32) * 2.5, -0.99, 0.99)
        duration_ms = int(len(audio_float) / sr * 1000)
        # Signal before blocking play — sd.play starts the audio stream
        # synchronously; the driver handles buffering.
        if playback_started_event is not None:
            playback_started_event.set()
        try:
            out_dev = self.output_device
            _sd().play(audio_float, samplerate=sr, device=out_dev, blocking=True)
            logger.info(
                f"[AudioPipeline] play_stream OK: {len(audio_float)} frames @ {sr}Hz "
                f"({duration_ms}ms) → device={out_dev}"
            )
        except Exception as _play_err:
            logger.error(
                f"[AudioPipeline] play_stream FAILED on device={self.output_device}: "
                f"{_play_err}",
                exc_info=True,
            )
            # Try the default device as a last resort.
            try:
                logger.warning("[AudioPipeline] Retrying play_stream with default device")
                _sd().play(audio_float, samplerate=sr, blocking=True)
                logger.info("[AudioPipeline] play_stream OK on default device")
            except Exception as _retry_err:
                logger.error(
                    f"[AudioPipeline] play_stream FAILED on default device too: {_retry_err}",
                    exc_info=True,
                )
                raise

    def play_audio(self, audio_data: np.ndarray, sample_rate: int = None):
        """Play audio through the system default output device.

        Prefers the native C++ ring-buffer player when available for sub-5ms
        chunk-to-speaker latency. Falls back to _sd().play() if the native
        extension is not compiled or fails to open.

        Args:
            audio_data:  float32 mono PCM array
            sample_rate: actual rate of audio_data (defaults to self.sample_rate)
        """
        sr = sample_rate if sample_rate is not None else self.sample_rate
        duration_ms = int(len(audio_data) / sr * 1000)
        logger.info(
            f"[AudioPipeline] play_audio: {len(audio_data)} frames @ {sr}Hz ({duration_ms}ms) → device={self.output_device}"
        )

        try:
            audio_float = audio_data.astype(np.float32)

            # Normalise amplitude — Pocket-TTS cloned voice can be quiet (~0.37 peak).
            # Target 0.85 peak: loud and clear, safely below hard clip at 1.0.
            peak = np.max(np.abs(audio_float))
            if peak > 1e-6:
                audio_float = audio_float * (0.85 / peak)
            audio_float = np.clip(audio_float, -1.0, 1.0)

            # Native path: low-latency ring-buffer stream
            if self._native_available and self._native_player is not None:
                try:
                    if not self._native_player.open(self.output_device or -1, sr):
                        raise RuntimeError("Native player failed to open")
                    self._native_player.push_chunk(audio_float)
                    self._native_player.wait_done()
                    self._native_player.close()
                    logger.info(
                        f"[AudioPipeline] play_audio: native complete ({duration_ms}ms)"
                    )
                    return
                except Exception as _native_err:
                    logger.warning(
                        f"[AudioPipeline] Native player failed ({_native_err}), falling back to sounddevice"
                    )

            # Fallback path: sounddevice blocking playback
            _sd().play(
                audio_float, samplerate=sr, device=self.output_device, blocking=True
            )
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

    def interrupt(self):
        """Immediately stop any active TTS playback (barge-in support)."""
        if self._native_available and self._native_player is not None:
            try:
                self._native_player.interrupt()
            except Exception as exc:
                logger.warning(f"[AudioPipeline] Native interrupt error: {exc}")

    def cleanup(self):
        """Release audio resources"""
        self._frame_listeners.clear()
        if self._input_stream:
            self._input_stream.stop()
            self._input_stream.close()
            self._input_stream = None
        # Close native player if open
        if self._native_available and self._native_player is not None:
            try:
                self._native_player.close()
            except Exception as exc:
                logger.warning(f"[AudioPipeline] Native cleanup error: {exc}")

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
