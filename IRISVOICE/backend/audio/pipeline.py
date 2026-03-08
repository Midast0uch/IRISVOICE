"""
AudioPipeline - Manages audio input/output streams using sounddevice
"""
import threading
import queue
import sys
import logging
from typing import Optional, Callable, List

logger = logging.getLogger(__name__)
import numpy as np
import sounddevice as sd


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
        """Start audio pipeline"""
        try:
            self._on_audio_frame = on_audio_frame
            
            # Start input stream
            self._input_stream = sd.InputStream(
                device=self.input_device,
                channels=self.channels,
                samplerate=self.sample_rate,
                callback=self._input_callback,
                blocksize=self.frame_length
            )
            
            # Start output stream
            self._output_stream = sd.OutputStream(
                device=self.output_device,
                channels=self.channels,
                samplerate=self.sample_rate,
                blocksize=self.frame_length
            )
            
            # Start streams
            self._input_stream.start()
            self._output_stream.start()
            
            self._is_running = True
            
            logger.info(f"[AudioPipeline] Started successfully with callback: {self._on_audio_frame.__name__ if self._on_audio_frame else 'None'}")
            return True
            
        except Exception as e:
            logger.error(f"[AudioPipeline] FATAL: An error occurred during audio stream startup: {e}")
            import traceback
            traceback.print_exc()
            self.cleanup()
            return False
    
    def stop(self):
        """Stop audio pipeline"""
        self._is_running = False
        self.cleanup()
        logger.info("[AudioPipeline] Stopped")
    
    def _input_callback(self, indata, frames, time, status):
        """This is called (from a separate thread) for each audio block."""
        if status:
            logger.info(status, file=sys.stderr)
        if self._is_running and self._on_audio_frame is not None:
            # The input data is a numpy array, take the first channel
            audio_frame = indata[:, 0].astype(np.float32)
            
            # Buffer audio if buffering is enabled
            with self._buffer_lock:
                if self._is_buffering:
                    self._audio_buffer.append(audio_frame)
            
            self._on_audio_frame(audio_frame)
    
    def play_audio(self, audio_data: np.ndarray):
        """Play audio through output stream"""
        logger.info(f"[AudioPipeline] play_audio called with shape: {audio_data.shape}, dtype: {audio_data.dtype}")
        
        if not self._output_stream:
            logger.warning(f"[AudioPipeline] Cannot play: output stream is not initialized (device: {self.output_device})")
            return
        
        try:
            # Convert float to int16
            pcm = (audio_data * 32767).astype(np.int16).tobytes()
            
            logger.info(f"[AudioPipeline] Writing {len(pcm)} bytes to output stream...")
            self._output_stream.write(pcm)
            logger.info("[AudioPipeline] Write complete")
        except Exception as e:
            logger.error(f"[AudioPipeline] Output error: {e}")
            import traceback
            traceback.print_exc()
    
    def clear_buffer(self):
        """Clear audio buffer"""
        with self._buffer_lock:
            self._audio_buffer.clear()
    
    def cleanup(self):
        """Release audio resources"""
        if self._input_stream:
            self._input_stream.stop()
            self._input_stream.close()
            self._input_stream = None
        
        if self._output_stream:
            self._output_stream.stop()
            self._output_stream.close()
            self._output_stream = None
    
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

        raw_devices = sd.query_devices()
        # key = first-31-chars of name (lowered), value = merged device dict
        seen: dict[str, dict] = {}

        for i in range(len(raw_devices)):
            info = sd.query_devices(i)
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
