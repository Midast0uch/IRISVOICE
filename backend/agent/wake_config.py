"""
Wake Configuration - Manages wake phrase and detection settings
"""
from typing import Optional, Dict, Any


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
    DEFAULT_WAKE_PHRASE = "Hey Computer"
    SUPPORTED_PHRASES = ["Hey Computer", "Jarvis", "Alexa", "Hey Mycroft", "Hey Jarvis"]
    
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if WakeConfig._initialized:
            return
        
        self.config = {
            "wake_phrase": self.DEFAULT_WAKE_PHRASE,
            "detection_sensitivity": 0.7,  # 0.0 to 1.0
            "activation_sound": True,
            "sleep_timeout": 60,  # seconds
        }
        
        # Callback for when config changes
        self._on_change: Optional[callable] = None
        
        WakeConfig._initialized = True
    
    def set_on_change_callback(self, callback: callable):
        """Set callback for config changes"""
        self._on_change = callback
    
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
            print(f"[WakeConfig] Updated: {kwargs}")
            # Notify callback
            if self._on_change:
                try:
                    self._on_change(self.config)
                except Exception as e:
                    print(f"[WakeConfig] Callback error: {e}")
    
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
