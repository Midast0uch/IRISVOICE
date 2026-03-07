"""
Wake Configuration - Manages wake phrase and detection settings
"""
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class WakeConfig:
    """
    Manages wake word configuration:
    - Custom wake phrases
    - Detection sensitivity
    - Activation sound
    - Sleep timeout
    """
    
    _instance: Optional['WakeConfig'] = None
    _initialized: bool = False
    
    # OpenWakeWord supported phrases (local, no API key needed)
    DEFAULT_WAKE_PHRASE = "jarvis"
    SUPPORTED_PHRASES = ["jarvis", "hey computer", "computer", "bumblebee", "porcupine"]
    
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if WakeConfig._initialized:
            return
        
        self.config = {
            "wake_word_enabled": True,  # Enabled for testing
            "wake_phrase": "Jarvis",  # Default to Jarvis
            "detection_sensitivity": 0.2,  # Balanced sensitivity for "Hey Jarvis"
            "activation_sound": True,
            "sleep_timeout": 60,  # seconds
        }
        
        # Callback for when config changes
        self._on_change: Optional[callable] = None

        # Multi-callback list for register_change_callback()
        self._change_callbacks = []

        WakeConfig._initialized = True
    
    def set_on_change_callback(self, callback: callable):
        """Set callback for config changes"""
        self._on_change = callback

    def register_change_callback(self, callback) -> None:
        """Register a callback to fire when wake phrase or sensitivity changes."""
        if not hasattr(self, '_change_callbacks'):
            self._change_callbacks = []
        if callback not in self._change_callbacks:
            self._change_callbacks.append(callback)
    
    def update_config(self, **kwargs) -> None:
        """Update wake configuration"""
        changed = False
        for key, value in kwargs.items():
            if key in self.config:
                # Validate values
                if key == "detection_sensitivity":
                    value = max(0.0, min(1.0, float(value)))
                elif key == "sleep_timeout":
                    value = max(5, min(300, int(value)))
                
                if self.config[key] != value:
                    self.config[key] = value
                    changed = True
        
        if changed:
            logger.info(f"[WakeConfig] Updated: {kwargs}")
            # Notify legacy single callback
            if self._on_change:
                try:
                    self._on_change(self.config)
                except Exception as e:
                    logger.error(f"[WakeConfig] Callback error: {e}")
            # Fire all registered change callbacks
            for cb in getattr(self, '_change_callbacks', []):
                try:
                    cb()
                except Exception as e:
                    logger.warning(f"[WakeConfig] Change callback error: {e}")
    
    def get_config(self) -> Dict[str, Any]:
        """Get current wake configuration"""
        return self.config.copy()
    
    def get_wake_phrase(self) -> str:
        """Get current wake phrase"""
        return self.config["wake_phrase"]
    
    def get_sensitivity(self) -> float:
        """Get detection sensitivity"""
        return self.config["detection_sensitivity"]
    
    def should_play_activation_sound(self) -> bool:
        """Check if activation sound is enabled"""
        return self.config["activation_sound"]
    
    def get_sleep_timeout(self) -> int:
        """Get sleep timeout in seconds"""
        return self.config["sleep_timeout"]


def get_wake_config() -> WakeConfig:
    """Get the singleton WakeConfig instance"""
    return WakeConfig()
