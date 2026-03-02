#!/usr/bin/env python3
"""
VisionSystem - Screen monitoring and analysis for IRIS (DEPRECATED)

⚠️ DEPRECATION WARNING: This module is deprecated and will be removed in v2.2.
Use VisionService instead: backend.vision.vision_service

This module now provides a compatibility wrapper around VisionService
for backward compatibility during the migration period.

See docs/VISION_MIGRATION_GUIDE.md for migration instructions.
"""

import warnings
import asyncio
import base64
import logging
import time
from typing import Any, Callable, Dict, List, Optional
from dataclasses import dataclass
from enum import Enum
import threading

logger = logging.getLogger(__name__)

# Deprecation warning on module import
warnings.warn(
    "VisionSystem is deprecated. Use VisionService from backend.vision.vision_service instead. "
    "See docs/VISION_MIGRATION_GUIDE.md for migration instructions.",
    DeprecationWarning,
    stacklevel=2
)


class VisionModel(Enum):
    """Supported vision models"""
    MINICPM_O4_5 = "minicpm-o4.5"
    LLAVA = "llava"
    BAKLLAVA = "bakllava"


@dataclass
class VisionConfig:
    """Vision system configuration"""
    vision_enabled: bool = False
    screen_context: bool = False
    proactive_monitor: bool = False
    ollama_endpoint: str = "http://localhost:11434"
    vision_model: VisionModel = VisionModel.MINICPM_O4_5
    monitor_interval: int = 30  # seconds (5-120)


@dataclass
class ScreenAnalysis:
    """Result of screen analysis"""
    timestamp: float
    description: str
    active_app: Optional[str]
    notable_items: List[str]
    needs_help: bool
    suggestion: Optional[str]
    raw_response: str


class VisionSystem:
    """
    Vision system for screen monitoring and analysis (DEPRECATED).
    
    ⚠️ This class is deprecated. Use VisionService instead.
    
    Provides:
    - Screen capture at configurable intervals
    - Vision model analysis using Ollama
    - Proactive monitoring for context changes
    - Integration with AgentKernel for context
    
    This class now redirects to VisionService for actual functionality.
    """
    
    def __init__(self, config: Optional[VisionConfig] = None):
        warnings.warn(
            "VisionSystem is deprecated. Use VisionService instead.",
            DeprecationWarning,
            stacklevel=2
        )
        
        self.config = config or VisionConfig()
        self._screen_capture = None
        self._minicpm_client = None
        self._is_monitoring = False
        self._monitor_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._context_history: List[ScreenAnalysis] = []
        self._current_context: Optional[ScreenAnalysis] = None
        self._notification_callbacks: List[Callable[[Dict], None]] = []
        self._max_history = 20
        self._vision_service = None
        
        logger.warning(
            f"[VisionSystem] Initialized with model: {self.config.vision_model.value} "
            "(DEPRECATED - Use VisionService instead)"
        )
    
    def _get_screen_capture(self):
        """Lazy load screen capture module"""
        if self._screen_capture is None:
            try:
                from backend.vision import ScreenCapture
                self._screen_capture = ScreenCapture()
                logger.info("[VisionSystem] Screen capture loaded")
            except Exception as e:
                logger.error(f"[VisionSystem] Failed to load screen capture: {e}")
        return self._screen_capture
    
    def _get_minicpm_client(self):
        """Lazy load MiniCPM client"""
        if self._minicpm_client is None:
            try:
                from backend.vision import MiniCPMClient
                self._minicpm_client = MiniCPMClient(
                    endpoint=self.config.ollama_endpoint,
                    model=self.config.vision_model.value
                )
                logger.info(f"[VisionSystem] MiniCPM client loaded: {self.config.ollama_endpoint}")
            except Exception as e:
                logger.error(f"[VisionSystem] Failed to load MiniCPM client: {e}")
        return self._minicpm_client
    
    def update_config(self, **kwargs):
        """
        Update vision system configuration.
        
        Supported parameters:
        - vision_enabled: bool
        - screen_context: bool
        - proactive_monitor: bool
        - ollama_endpoint: str
        - vision_model: str (minicpm-o4.5, llava, bakllava)
        - monitor_interval: int (5-120 seconds)
        """
        for key, value in kwargs.items():
            if hasattr(self.config, key):
                if key == "vision_model" and isinstance(value, str):
                    # Convert string to enum
                    try:
                        value = VisionModel(value)
                    except ValueError:
                        logger.warning(f"[VisionSystem] Invalid vision model: {value}")
                        continue
                
                if key == "monitor_interval":
                    # Validate interval range
                    value = max(5, min(120, int(value)))
                
                setattr(self.config, key, value)
                logger.info(f"[VisionSystem] Config updated: {key}={value}")
        
        # Restart monitoring if interval changed and currently running
        if "monitor_interval" in kwargs and self._is_monitoring:
            self.stop_monitoring()
            self.start_monitoring()
    
    async def capture_and_analyze(self) -> Optional[ScreenAnalysis]:
        """
        Capture current screen and analyze it with vision model.
        
        Returns:
            ScreenAnalysis object with analysis results, or None if failed
        """
        if not self.config.vision_enabled:
            logger.debug("[VisionSystem] Vision not enabled")
            return None
        
        # Get screen capture
        capture = self._get_screen_capture()
        if not capture:
            logger.error("[VisionSystem] Screen capture not available")
            return None
        
        try:
            screenshot_b64, is_new = capture.capture_base64()
            if not screenshot_b64:
                logger.error("[VisionSystem] Failed to capture screenshot")
                return None
            
            # Get vision client
            client = self._get_minicpm_client()
            if not client:
                logger.error("[VisionSystem] Vision client not available")
                return None
            
            # Check if model is available
            if not client.check_availability():
                logger.error(f"[VisionSystem] Model {self.config.vision_model.value} not available")
                return None
            
            # Analyze screen
            logger.debug("[VisionSystem] Analyzing screen...")
            context = await asyncio.to_thread(
                client.detect_screen_context,
                screenshot_b64
            )
            
            # Create analysis result
            analysis = ScreenAnalysis(
                timestamp=time.time(),
                description=context.get("description", ""),
                active_app=context.get("active_app"),
                notable_items=context.get("notable_items", []),
                needs_help=context.get("needs_help", False),
                suggestion=context.get("suggestion"),
                raw_response=context.get("raw_response", "")
            )
            
            # Update current context
            self._current_context = analysis
            
            # Add to history
            self._context_history.append(analysis)
            if len(self._context_history) > self._max_history:
                self._context_history = self._context_history[-self._max_history:]
            
            logger.info(f"[VisionSystem] Screen analyzed: {analysis.description[:100]}")
            return analysis
            
        except Exception as e:
            logger.error(f"[VisionSystem] Analysis failed: {e}")
            return None
    
    def start_monitoring(self) -> bool:
        """
        Start proactive screen monitoring.
        
        Captures and analyzes screen at configured intervals.
        Fires notification callbacks when notable changes detected.
        
        Returns:
            True if monitoring started successfully, False otherwise
        """
        if not self.config.proactive_monitor:
            logger.info("[VisionSystem] Proactive monitoring not enabled")
            return False
        
        if self._is_monitoring:
            logger.info("[VisionSystem] Monitoring already running")
            return True
        
        # Check if vision model is available
        client = self._get_minicpm_client()
        if not client or not client.check_availability():
            logger.error(f"[VisionSystem] Model {self.config.vision_model.value} not available")
            return False
        
        # Start monitoring thread
        self._stop_event.clear()
        self._is_monitoring = True
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop,
            daemon=True
        )
        self._monitor_thread.start()
        
        logger.info(f"[VisionSystem] Monitoring started (interval: {self.config.monitor_interval}s)")
        return True
    
    def stop_monitoring(self):
        """Stop proactive screen monitoring"""
        if not self._is_monitoring:
            return
        
        self._stop_event.set()
        self._is_monitoring = False
        
        if self._monitor_thread:
            self._monitor_thread.join(timeout=5)
        
        logger.info("[VisionSystem] Monitoring stopped")
    
    def _monitor_loop(self):
        """Main monitoring loop running in background thread"""
        while not self._stop_event.is_set():
            try:
                # Run async analysis in thread
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                analysis = loop.run_until_complete(self.capture_and_analyze())
                loop.close()
                
                if analysis:
                    # Detect notable changes
                    notifications = self._detect_notable_changes(analysis)
                    
                    # Fire notification callbacks
                    for notification in notifications:
                        for callback in self._notification_callbacks:
                            try:
                                callback(notification)
                            except Exception as e:
                                logger.error(f"[VisionSystem] Notification callback error: {e}")
                
            except Exception as e:
                logger.error(f"[VisionSystem] Monitor loop error: {e}")
            
            # Wait for interval or stop signal
            self._stop_event.wait(timeout=self.config.monitor_interval)
    
    def _detect_notable_changes(self, new_analysis: ScreenAnalysis) -> List[Dict[str, Any]]:
        """
        Compare new analysis with previous to find notable changes.
        
        Returns list of notification dictionaries to fire.
        """
        notifications = []
        
        if not self._current_context or self._current_context == new_analysis:
            return notifications
        
        old = self._current_context
        new = new_analysis
        
        # App changed
        if old.active_app != new.active_app:
            notifications.append({
                "type": "app_change",
                "message": f"Switched to {new.active_app or 'unknown'}",
                "old_app": old.active_app,
                "new_app": new.active_app,
                "timestamp": new.timestamp
            })
        
        # Error or warning detected
        if new.notable_items:
            for item in new.notable_items:
                if isinstance(item, str) and any(
                    kw in item.lower()
                    for kw in ["error", "exception", "failed", "warning", "crash"]
                ):
                    notifications.append({
                        "type": "error_detected",
                        "message": f"I noticed something: {item}",
                        "detail": item,
                        "timestamp": new.timestamp
                    })
        
        # User needs help
        if new.needs_help and not old.needs_help:
            notifications.append({
                "type": "help_offered",
                "message": new.suggestion or "It looks like you might need help.",
                "timestamp": new.timestamp
            })
        
        return notifications
    
    def on_notification(self, callback: Callable[[Dict], None]):
        """
        Register a callback for proactive notifications.
        
        Callback receives a dict with:
        - type: str (app_change, error_detected, help_offered)
        - message: str
        - timestamp: float
        - additional fields depending on type
        """
        self._notification_callbacks.append(callback)
        logger.info(f"[VisionSystem] Notification callback registered (total: {len(self._notification_callbacks)})")
    
    def get_current_context(self) -> Optional[ScreenAnalysis]:
        """Get the most recent screen analysis"""
        return self._current_context
    
    def get_context_history(self, limit: int = 10) -> List[ScreenAnalysis]:
        """Get recent screen analysis history"""
        return self._context_history[-limit:]
    
    def get_status(self) -> Dict[str, Any]:
        """
        Get vision system status.
        
        Returns dict with:
        - vision_enabled: bool
        - screen_context: bool
        - proactive_monitor: bool
        - is_monitoring: bool
        - model: str
        - endpoint: str
        - monitor_interval: int
        - context_history_size: int
        - current_app: Optional[str]
        """
        return {
            "vision_enabled": self.config.vision_enabled,
            "screen_context": self.config.screen_context,
            "proactive_monitor": self.config.proactive_monitor,
            "is_monitoring": self._is_monitoring,
            "model": self.config.vision_model.value,
            "endpoint": self.config.ollama_endpoint,
            "monitor_interval": self.config.monitor_interval,
            "context_history_size": len(self._context_history),
            "current_app": self._current_context.active_app if self._current_context else None
        }


# Singleton instance
_vision_system: Optional[VisionSystem] = None


def get_vision_system(config: Optional[VisionConfig] = None) -> VisionSystem:
    """Get the singleton VisionSystem instance"""
    global _vision_system
    if _vision_system is None:
        _vision_system = VisionSystem(config)
    return _vision_system
