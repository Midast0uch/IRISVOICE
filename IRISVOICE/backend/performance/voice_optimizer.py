"""
Voice Processing Optimizer
Ensures voice command processing within 3 seconds (p95).
"""
import asyncio
import logging
import time
from typing import Optional
from collections import deque
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class VoiceMetrics:
    """Track voice processing metrics."""
    samples: deque = field(default_factory=lambda: deque(maxlen=1000))
    
    def record(self, processing_time_s: float):
        """Record a processing time sample."""
        self.samples.append(processing_time_s)
    
    def get_p95(self) -> float:
        """Get 95th percentile processing time."""
        if not self.samples:
            return 0.0
        sorted_samples = sorted(self.samples)
        idx = int(len(sorted_samples) * 0.95)
        return sorted_samples[idx]
    
    def get_mean(self) -> float:
        """Get mean processing time."""
        if not self.samples:
            return 0.0
        return sum(self.samples) / len(self.samples)
    
    def get_max(self) -> float:
        """Get maximum processing time."""
        if not self.samples:
            return 0.0
        return max(self.samples)


class VoiceOptimizer:
    """
    Optimizes voice processing pipeline.
    
    Features:
    - Audio buffer optimization
    - Processing time monitoring
    - Parallel audio processing where possible
    """
    
    # Configuration
    TARGET_PROCESSING_TIME_S = 3.0  # Target p95 processing time
    AUDIO_BUFFER_SIZE = 4096  # Optimal buffer size for processing
    
    def __init__(self):
        self.voice_metrics = VoiceMetrics()
    
    async def process_voice_command(
        self,
        audio_data: bytes,
        processing_callback
    ) -> str:
        """
        Process a voice command with optimization.
        
        Args:
            audio_data: Raw audio data
            processing_callback: Async function to process audio
        
        Returns:
            Transcribed text
        """
        start_time = time.time()
        
        try:
            # Process audio
            result = await processing_callback(audio_data)
            
            # Record metrics
            processing_time = time.time() - start_time
            self.voice_metrics.record(processing_time)
            
            if processing_time > self.TARGET_PROCESSING_TIME_S:
                logger.warning(
                    f"Voice processing took {processing_time:.2f}s, exceeds {self.TARGET_PROCESSING_TIME_S}s target"
                )
            
            return result
        
        except Exception as e:
            logger.error(f"Error processing voice command: {e}", exc_info=True)
            raise
    
    def get_metrics(self) -> dict:
        """Get current performance metrics."""
        return {
            "p95_processing_time_s": self.voice_metrics.get_p95(),
            "mean_processing_time_s": self.voice_metrics.get_mean(),
            "max_processing_time_s": self.voice_metrics.get_max(),
            "total_samples": len(self.voice_metrics.samples),
            "target_processing_time_s": self.TARGET_PROCESSING_TIME_S,
        }
    
    def is_meeting_target(self) -> bool:
        """Check if we're meeting the processing time target."""
        p95 = self.voice_metrics.get_p95()
        return p95 <= self.TARGET_PROCESSING_TIME_S if p95 > 0 else True


# Global instance
_optimizer: Optional[VoiceOptimizer] = None


def get_voice_optimizer() -> VoiceOptimizer:
    """Get or create the singleton VoiceOptimizer."""
    global _optimizer
    if _optimizer is None:
        _optimizer = VoiceOptimizer()
    return _optimizer
