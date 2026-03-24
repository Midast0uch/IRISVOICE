"""
MiniCPM Client (Deprecated)

⚠️ DEPRECATION WARNING: This module is deprecated and will be removed in v2.2.
Use VisionService instead: backend.vision.vision_service

This module now provides a compatibility wrapper around VisionService
for backward compatibility during the migration period.
"""

import warnings
import asyncio
import logging
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)

# Deprecation warning on module import
warnings.warn(
    "MiniCPMClient is deprecated. Use VisionService from backend.vision.vision_service instead. "
    "See docs/VISION_MIGRATION_GUIDE.md for migration instructions.",
    DeprecationWarning,
    stacklevel=2
)


class MiniCPMClient:
    """
    Deprecated MiniCPM client wrapper.
    
    This class now redirects all operations to the new VisionService.
    It exists only for backward compatibility and will be removed in v2.2.
    
    Migration:
        Before: from backend.vision import MiniCPMClient
        After:  from backend.vision.vision_service import get_vision_service
    """
    
    def __init__(self, endpoint: str = "http://localhost:11434", model: str = "minicpm-o4.5"):
        """
        Initialize MiniCPMClient (deprecated).
        
        Args:
            endpoint: Ignored - VisionService uses local model
            model: Model name for reference
        """
        warnings.warn(
            "MiniCPMClient is deprecated. Use VisionService instead.",
            DeprecationWarning,
            stacklevel=2
        )
        
        self._endpoint = endpoint
        self._model = model
        self._vision_service = None
        
        logger.info("[MiniCPMClient] Initialized (deprecated, uses VisionService internally)")
    
    def _get_service(self):
        """Lazy-load VisionService."""
        if self._vision_service is None:
            from backend.vision.vision_service import get_vision_service
            self._vision_service = get_vision_service()
        return self._vision_service
    
    def check_availability(self) -> bool:
        """
        Check if vision service is available (deprecated).
        
        Returns:
            True if VisionService is enabled and available
        """
        warnings.warn(
            "MiniCPMClient.check_availability() is deprecated. "
            "Use VisionService.get_status_dict() instead.",
            DeprecationWarning,
            stacklevel=2
        )
        
        try:
            service = self._get_service()
            status = service.get_status_dict()
            return status["status"] == "enabled" and status["is_available"]
        except Exception as e:
            logger.error(f"[MiniCPMClient] Availability check failed: {e}")
            return False
    
    def analyze(self, image_b64: str, prompt: str = "Describe what you see") -> Dict[str, Any]:
        """
        Analyze an image (deprecated).
        
        Args:
            image_b64: Base64-encoded image
            prompt: Analysis prompt
            
        Returns:
            Dict with analysis results
        """
        warnings.warn(
            "MiniCPMClient.analyze() is deprecated. "
            "Use VisionService.analyze() instead.",
            DeprecationWarning,
            stacklevel=2
        )
        
        try:
            service = self._get_service()
            
            # Ensure service is enabled
            if service.get_status_dict()["status"] != "enabled":
                # Try to enable
                loop = asyncio.get_event_loop()
                enabled = loop.run_until_complete(service.enable())
                if not enabled:
                    return {"error": "Vision service could not be enabled"}
            
            # Run analysis
            loop = asyncio.get_event_loop()
            result = loop.run_until_complete(service.analyze(image_b64, prompt))
            
            return {"response": result, "success": True}
            
        except Exception as e:
            logger.error(f"[MiniCPMClient] Analysis failed: {e}")
            return {"error": str(e), "success": False}
    
    def chat(
        self,
        messages: List[Dict[str, str]],
        images: Optional[List[str]] = None,
        temperature: float = 0.7
    ) -> Dict[str, Any]:
        """
        Chat with vision (deprecated).
        
        Args:
            messages: List of message dicts with 'role' and 'content'
            images: Optional list of base64-encoded images
            temperature: Sampling temperature
            
        Returns:
            Dict with response
        """
        warnings.warn(
            "MiniCPMClient.chat() is deprecated. "
            "Use VisionService.chat() instead.",
            DeprecationWarning,
            stacklevel=2
        )
        
        try:
            service = self._get_service()
            
            # Ensure service is enabled
            if service.get_status_dict()["status"] != "enabled":
                loop = asyncio.get_event_loop()
                enabled = loop.run_until_complete(service.enable())
                if not enabled:
                    return {"error": "Vision service could not be enabled"}
            
            # Run chat
            loop = asyncio.get_event_loop()
            result = loop.run_until_complete(
                service.chat(messages=messages, images=images, temperature=temperature)
            )
            
            return {"response": result, "success": True}
            
        except Exception as e:
            logger.error(f"[MiniCPMClient] Chat failed: {e}")
            return {"error": str(e), "success": False}
    
    def detect_screen_context(self, image_b64: str) -> Dict[str, Any]:
        """
        Detect screen context (deprecated).
        
        Args:
            image_b64: Base64-encoded screenshot
            
        Returns:
            Dict with context analysis
        """
        warnings.warn(
            "MiniCPMClient.detect_screen_context() is deprecated. "
            "Use VisionService.analyze() with appropriate prompt instead.",
            DeprecationWarning,
            stacklevel=2
        )
        
        prompt = """Analyze this screen. What app is active? 
        Are there any errors or notable items? 
        Is the user potentially stuck or needing help?"""
        
        result = self.analyze(image_b64, prompt)
        
        if result.get("success"):
            # Parse the response into the expected format
            return self._parse_context_response(result["response"])
        else:
            return {
                "active_app": "unknown",
                "notable_items": [],
                "needs_help": False,
                "error": result.get("error")
            }
    
    def _parse_context_response(self, response: str) -> Dict[str, Any]:
        """Parse analysis response into context format."""
        context = {
            "active_app": "unknown",
            "notable_items": [],
            "needs_help": False,
            "suggestion": None,
            "raw_analysis": response
        }
        
        response_lower = response.lower()
        
        # Try to extract app name
        app_indicators = ["active app:", "application:", "window:", "in ", "using "]
        for indicator in app_indicators:
            if indicator in response_lower:
                idx = response_lower.find(indicator)
                if idx >= 0:
                    end = min(idx + len(indicator) + 30, len(response))
                    context["active_app"] = response[idx:end].strip()
                    break
        
        # Check for errors
        error_keywords = ["error", "exception", "failed", "warning", "crash"]
        for keyword in error_keywords:
            if keyword in response_lower:
                sentences = response.split('.')
                for sent in sentences:
                    if keyword in sent.lower():
                        context["notable_items"].append(sent.strip())
                        break
        
        # Check if needs help
        help_indicators = ["help", "stuck", "confused", "unclear"]
        for indicator in help_indicators:
            if indicator in response_lower:
                context["needs_help"] = True
                break
        
        return context
    
    def get_status(self) -> Dict[str, Any]:
        """
        Get client status (deprecated).
        
        Returns:
            Dict with status information
        """
        warnings.warn(
            "MiniCPMClient.get_status() is deprecated. "
            "Use VisionService.get_status_dict() instead.",
            DeprecationWarning,
            stacklevel=2
        )
        
        try:
            service = self._get_service()
            status = service.get_status_dict()
            return {
                "available": status["is_available"],
                "enabled": status["status"] == "enabled",
                "model": status["model_name"],
                "vram_usage_mb": status["vram_usage_mb"],
                "quantization": status["quantization_enabled"],
                "deprecated": True,
                "migration_note": "Use VisionService instead"
            }
        except Exception as e:
            return {
                "available": False,
                "error": str(e),
                "deprecated": True
            }
    
    def update_config(self, **kwargs):
        """
        Update configuration (deprecated, no-op).
        
        This method is a no-op since VisionService manages its own config.
        """
        warnings.warn(
            "MiniCPMClient.update_config() is deprecated and has no effect. "
            "Configure VisionService directly instead.",
            DeprecationWarning,
            stacklevel=2
        )
        logger.warning("[MiniCPMClient] update_config() is deprecated and has no effect")


# Singleton instance for backward compatibility
_client_instance: Optional[MiniCPMClient] = None

def get_minicpm_client() -> MiniCPMClient:
    """Get or create the singleton MiniCPMClient instance (deprecated)."""
    global _client_instance
    if _client_instance is None:
        _client_instance = MiniCPMClient()
    return _client_instance


# Maintain backward compatibility for imports
__all__ = ["MiniCPMClient", "get_minicpm_client"]
