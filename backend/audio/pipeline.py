"""
AudioPipeline - Manages audio input/output streams using sounddevice
"""
import threading
import queue
from typing import Optional, Callable, List
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
            
            print(f"[AudioPipeline] Started successfully with callback: {self._on_audio_frame.__name__ if self._on_audio_frame else 'None'}")
            return True
            
        except Exception as e:
            print(f"[AudioPipeline] FATAL: An error occurred during audio stream startup: {e}")
            import traceback
            traceback.print_exc()
            self.cleanup()
            return False
    
    def stop(self):
        """Stop audio pipeline"""
        self._is_running = False
        self.cleanup()
        print("[AudioPipeline] Stopped")
    
    def _input_callback(self, indata, frames, time, status):
        """This is called (from a separate thread) for each audio block."""
        if status:
            print(status, file=sys.stderr)
        if self._is_running and self._on_audio_frame is not None:
            # The input data is a numpy array, take the first channel
            audio_frame = indata[:, 0].astype(np.float32)
            self._on_audio_frame(audio_frame)
    
    def play_audio(self, audio_data: np.ndarray):
        """Play audio through output stream"""
        print(f"[AudioPipeline] play_audio called with shape: {audio_data.shape}, dtype: {audio_data.dtype}")
        
        if not self._output_stream:
            print(f"[AudioPipeline] Cannot play: output stream is not initialized (device: {self.output_device})")
            return
        
        try:
            # Convert float to int16
            pcm = (audio_data * 32767).astype(np.int16).tobytes()
            
            print(f"[AudioPipeline] Writing {len(pcm)} bytes to output stream...")
            self._output_stream.write(pcm)
            print("[AudioPipeline] Write complete")
        except Exception as e:
            print(f"[AudioPipeline] Output error: {e}")
            import traceback
            traceback.print_exc()
    
    def get_buffered_audio(self) -> np.ndarray:
        """Get accumulated audio buffer"""
        with self._buffer_lock:
            if not self._audio_buffer:
                return np.array([])
            buffer = np.concatenate(self._audio_buffer)
            self._audio_buffer.clear()
            return buffer
    
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
        """List available audio devices"""
        devices = []
        
        for i in range(sd.query_devices()):
            info = sd.query_devices(i)
            devices.append({
                "index": i,
                "name": info["name"],
                "input": info["max_input_channels"] > 0,
                "output": info["max_output_channels"] > 0,
                "sample_rate": int(info["default_samplerate"])
            })
        
        return devices
