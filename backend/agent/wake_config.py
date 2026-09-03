"""
Wake Configuration - Manages wake phrase and detection settings.

Engine-neutral since the ViolaWake migration (session 278): the wake detector
is now ViolaWake (custom ONNX head + OpenWakeWord backbone), not Porcupine.
The config no longer assumes pvporcupine built-in keywords or `.ppn` files.
"""
import logging
from pathlib import Path
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

# Project-root-relative default ONNX model path (the trained Hey Iris head).
# Resolved lazily so the config works from any working directory.
_DEFAULT_MODEL_REL = Path("data") / "hey iris_237_1788045452.onnx"


class WakeConfig:
    """
    Manages wake word configuration:
    - Wake phrase (single validated "Hey Iris" model)
    - Detection sensitivity
    - Activation sound
    - Sleep timeout
    - ONNX model path (engine-neutral)
    """
    
    _instance: Optional['WakeConfig'] = None
    _initialized: bool = False
    
    # Single validated wake phrase backed by the trained ONNX model.
    # The old pvporcupine built-in keyword list (jarvis/computer/bumblebee/
    # porcupine) is gone — there is exactly one model, "Hey Iris".
    DEFAULT_WAKE_PHRASE = "Hey Iris"
    SUPPORTED_PHRASES = ["Hey Iris"]
    
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if WakeConfig._initialized:
            return
        
        self.config = {
            "wake_word_enabled": True,
            "wake_phrase": "Hey Iris",  # single validated model
            "custom_model_path": None,  # ONNX model path; None = default project-root model
            "detection_sensitivity": 0.65,  # 0.0-1.0; raised from 0.5 — catches more accent/pronunciation variations
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
        """Get detection sensitivity (0.0-1.0)"""
        return self.config["detection_sensitivity"]

    def get_custom_model_path(self) -> Optional[str]:
        """Get path to the wake word ONNX model, or None to use the default.

        Returns the configured path if set; otherwise resolves the default
        project-root-relative ONNX model path. Engine-neutral (ViolaWake).
        """
        explicit = self.config.get("custom_model_path")
        if explicit:
            return str(explicit)
        # Resolve relative to the project root (backend/agent/ -> project root)
        project_root = Path(__file__).resolve().parent.parent.parent
        return str(project_root / _DEFAULT_MODEL_REL)

    def get_model_path(self) -> str:
        """Return the resolved ONNX model path (never None)."""
        return self.get_custom_model_path() or str(_DEFAULT_MODEL_REL)
    
    def should_play_activation_sound(self) -> bool:
        """Check if activation sound is enabled"""
        return self.config["activation_sound"]
    
    def get_sleep_timeout(self) -> int:
        """Get sleep timeout in seconds"""
        return self.config["sleep_timeout"]


def get_wake_config() -> WakeConfig:
    """Get the singleton WakeConfig instance"""
    return WakeConfig()
