"""
AudioPipeline - Manages audio input/output streams using PyAudio
"""
import threading
import queue
from typing import Optional, Callable, List
import numpy as np
import pyaudio


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
        
        # PyAudio instance
        self._pa = None
        
        # Streams
        self._input_stream = None
        self._output_stream = None
        
        # Callback
        self._on_audio_frame: Optional[Callable[[np.ndarray], None]] = None
        
        # State
        self._is_running = False
        self._input_thread: Optional[threading.Thread] = None
        
        # Audio buffer for speech collection
        self._audio_buffer: List[np.ndarray] = []
        self._buffer_lock = threading.Lock()
        
        # Print input devices on instantiation
        self._print_input_devices()
        
    def start(self, on_audio_frame: Callable[[np.ndarray], None]) -> bool:
        """Start audio pipeline"""
        try:
            self._pa = pyaudio.PyAudio()
            self._on_audio_frame = on_audio_frame
            
            # Open input stream
            self._input_stream = self._pa.open(
                format=pyaudio.paInt16,
                channels=self.channels,
                rate=self.sample_rate,
                input=True,
                input_device_index=self.input_device,
                frames_per_buffer=self.frame_length
            )
            
            # Open output stream
            self._output_stream = self._pa.open(
                format=pyaudio.paInt16,
                channels=self.channels,
                rate=self.sample_rate,
                output=True,
                output_device_index=self.output_device
            )
            
            # Start input thread
            self._is_running = True
            self._input_thread = threading.Thread(target=self._input_loop)
            self._input_thread.daemon = True
            self._input_thread.start()
            
            print("[AudioPipeline] Started")
            return True
            
        except Exception as e:
            print(f"[AudioPipeline] Start failed: {e}")
            self.cleanup()
            return False
    
    def stop(self):
        """Stop audio pipeline"""
        self._is_running = False
        
        if self._input_thread:
            self._input_thread.join(timeout=1.0)
        
        self.cleanup()
        print("[AudioPipeline] Stopped")
    
    def _input_loop(self):
        """Input stream processing loop"""
        while self._is_running:
            try:
                # Read audio frame
                data = self._input_stream.read(self.frame_length, exception_on_overflow=False)
                
                # Convert to numpy array
                audio_frame = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
                
                # Add to buffer
                with self._buffer_lock:
                    self._audio_buffer.append(audio_frame)
                    # Keep only last 30 seconds
                    max_frames = int(30 * self.sample_rate / self.frame_length)
                    if len(self._audio_buffer) > max_frames:
                        self._audio_buffer = self._audio_buffer[-max_frames:]
                
                # Call callback
                if self._on_audio_frame:
                    self._on_audio_frame(audio_frame)
                    
            except Exception as e:
                print(f"[AudioPipeline] Input error: {e}")
                break
    
    def play_audio(self, audio_data: np.ndarray):
        """Play audio through output stream"""
        if not self._output_stream:
            print("[AudioPipeline] Cannot play: output stream is not initialized")
            return
        
        try:
            # Convert float to int16
            pcm = (audio_data * 32767).astype(np.int16).tobytes()
            
            # Check if stream is active
            if not self._output_stream.is_active():
                print("[AudioPipeline] Output stream is not active, starting it...")
                self._output_stream.start_stream()
            
            print(f"[AudioPipeline] Writing {len(pcm)} bytes to output stream...")
            self._output_stream.write(pcm)
            print("[AudioPipeline] Write complete")
        except Exception as e:
            print(f"[AudioPipeline] Output error: {e}")
    
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
            self._input_stream.stop_stream()
            self._input_stream.close()
            self._input_stream = None
        
        if self._output_stream:
            self._output_stream.stop_stream()
            self._output_stream.close()
            self._output_stream = None
        
        if self._pa:
            self._pa.terminate()
            self._pa = None
    
    def _print_input_devices(self):
        """Print all available input devices to console"""
        pa = pyaudio.PyAudio()
        print("[AudioPipeline] Input devices:")
        for i in range(pa.get_device_count()):
            info = pa.get_device_info_by_index(i)
            if info["maxInputChannels"] > 0:
                print(f"  [{i}] {info['name']}")
        print(f"[AudioPipeline] Using input device index: {self.input_device or 'Default'}")
        pa.terminate()
    
    @staticmethod
    def list_devices() -> List[dict]:
        """List available audio devices"""
        pa = pyaudio.PyAudio()
        devices = []
        
        for i in range(pa.get_device_count()):
            info = pa.get_device_info_by_index(i)
            devices.append({
                "index": i,
                "name": info["name"],
                "input": info["maxInputChannels"] > 0,
                "output": info["maxOutputChannels"] > 0,
                "sample_rate": int(info["defaultSampleRate"])
            })
        
        pa.terminate()
        return devices
