#!/usr/bin/env python3
"""
VisionService - Consolidated Vision Model Service with 4-Bit Quantization

Provides:
- 4-bit quantized model loading (60-70% VRAM reduction)
- User-controlled lazy loading (load only when enabled)
- Unified interface for all vision operations
- Proper cleanup and VRAM management

Memory Usage:
- Without quantization (FP16): ~8-12 GB VRAM
- With 4-bit quantization: ~3-4 GB VRAM
- When disabled: ~0 GB VRAM

Requirements: 1.1, 1.2, 1.3, 1.4, 2.2, 2.3, 2.4
"""

import logging
import os
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Union

import torch
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class VisionServiceState(str, Enum):
    """Vision service states"""
    DISABLED = "disabled"
    LOADING = "loading"
    ENABLED = "enabled"
    ERROR = "error"


class VisionServiceStatus(BaseModel):
    """Status model for vision service"""
    status: VisionServiceState = VisionServiceState.DISABLED
    vram_usage_mb: Optional[int] = None
    load_progress_percent: Optional[int] = None
    error_message: Optional[str] = None
    last_used: Optional[datetime] = None
    model_name: str = "minicpm-o4.5"
    quantization_enabled: bool = True


class VisionAnalyzeRequest(BaseModel):
    """Request for screen analysis"""
    image_base64: str = Field(..., min_length=100, description="Base64 encoded image")
    prompt: str = Field(default="Describe what you see in this image.", min_length=1)


class VisionAnalyzeResponse(BaseModel):
    """Response from screen analysis"""
    success: bool
    description: Optional[str] = None
    error: Optional[str] = None
    processing_time_ms: Optional[int] = None


class VisionService:
    """
    Consolidated vision service with 4-bit quantization and lazy loading.
    
    This service replaces:
    - MiniCPMClient (Ollama-based)
    - VisionSystem (wrapper)
    - VisionModelClient (automation)
    - GUIToolkit (local loader)
    
    Features:
    - 4-bit quantization reduces VRAM from 8-12GB to 3-4GB
    - Lazy loading: model only loads when user enables it
    - Proper cleanup: unloads model and frees VRAM on disable
    - Singleton pattern: one instance across the application
    """
    
    _instance: Optional["VisionService"] = None
    _initialized: bool = False
    
    # Model configuration
    DEFAULT_MODEL_PATH = "./models/MiniCPM-V-2_6"
    DEFAULT_MODEL_NAME = "minicpm-o4.5"
    
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(
        self,
        model_path: Optional[str] = None,
        enable_quantization: bool = True,
        device: Optional[str] = None
    ):
        if VisionService._initialized:
            return
        
        self.model_path = model_path or self.DEFAULT_MODEL_PATH
        self.enable_quantization = enable_quantization
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        
        # Model components (lazy loaded)
        self._model = None
        self._tokenizer = None
        
        # State tracking
        self._status = VisionServiceStatus(
            status=VisionServiceState.DISABLED,
            quantization_enabled=enable_quantization
        )
        
        # Quantization config (4-bit)
        self._quant_config = None
        if enable_quantization:
            try:
                from transformers import BitsAndBytesConfig
                self._quant_config = BitsAndBytesConfig(
                    load_in_4bit=True,
                    bnb_4bit_compute_dtype=torch.float16,
                    bnb_4bit_use_double_quant=True,  # Nested quantization
                    bnb_4bit_quant_type="nf4"  # Normalized float 4
                )
                logger.info("[VisionService] 4-bit quantization enabled")
            except ImportError:
                logger.warning("[VisionService] bitsandbytes not available, falling back to standard loading")
                self.enable_quantization = False
                self._status.quantization_enabled = False
        
        VisionService._initialized = True
        logger.info(f"[VisionService] Initialized (device={self.device}, quantization={enable_quantization})")
    
    @property
    def status(self) -> VisionServiceStatus:
        """Get current service status"""
        # Update VRAM usage if enabled
        if self._status.status == VisionServiceState.ENABLED and torch.cuda.is_available():
            self._status.vram_usage_mb = torch.cuda.memory_allocated() // (1024 * 1024)
        return self._status
    
    async def enable(self) -> bool:
        """
        Enable vision service by loading the model.
        
        This is called when the user explicitly enables vision in the UI.
        Uses lazy loading - model is not loaded until this is called.
        
        Returns:
            True if successfully enabled, False otherwise
        """
        if self._status.status == VisionServiceState.ENABLED:
            logger.info("[VisionService] Already enabled")
            return True
        
        if self._status.status == VisionServiceState.LOADING:
            logger.info("[VisionService] Already loading")
            return False
        
        self._status.status = VisionServiceState.LOADING
        self._status.load_progress_percent = 0
        logger.info("[VisionService] Loading model...")
        
        try:
            # Check if model exists locally
            if not os.path.exists(self.model_path):
                error_msg = f"Model not found at {self.model_path}"
                logger.error(f"[VisionService] {error_msg}")
                self._status.status = VisionServiceState.ERROR
                self._status.error_message = error_msg
                return False
            
            self._status.load_progress_percent = 10
            
            # Import transformers here to avoid slow startup
            from transformers import AutoModel, AutoTokenizer
            
            self._status.load_progress_percent = 20
            
            # Load tokenizer
            logger.info("[VisionService] Loading tokenizer...")
            self._tokenizer = AutoTokenizer.from_pretrained(
                self.model_path,
                trust_remote_code=True
            )
            
            self._status.load_progress_percent = 40
            
            # Load model with quantization
            logger.info("[VisionService] Loading model (this may take 30-60 seconds)...")
            
            load_kwargs = {
                "trust_remote_code": True,
                "device_map": "auto" if self.device == "cuda" else None,
                "torch_dtype": torch.float16 if self.device == "cuda" else torch.float32,
            }
            
            # Add quantization config if enabled
            if self.enable_quantization and self._quant_config:
                load_kwargs["quantization_config"] = self._quant_config
                logger.info("[VisionService] Using 4-bit quantization")
            
            self._model = AutoModel.from_pretrained(
                self.model_path,
                **load_kwargs
            )
            
            self._status.load_progress_percent = 90
            
            # Move to device if not using device_map
            if self.device == "cpu":
                self._model = self._model.to(self.device)
            
            self._model.eval()  # Set to evaluation mode
            
            self._status.load_progress_percent = 100
            self._status.status = VisionServiceState.ENABLED
            self._status.last_used = datetime.now()
            
            # Log VRAM usage
            if torch.cuda.is_available():
                vram_mb = torch.cuda.memory_allocated() // (1024 * 1024)
                logger.info(f"[VisionService] Enabled successfully (VRAM: {vram_mb} MB)")
            else:
                logger.info("[VisionService] Enabled successfully (CPU mode)")
            
            return True
            
        except Exception as e:
            error_msg = f"Failed to load model: {str(e)}"
            logger.error(f"[VisionService] {error_msg}", exc_info=True)
            self._status.status = VisionServiceState.ERROR
            self._status.error_message = error_msg
            self._status.load_progress_percent = 0
            return False
    
    async def disable(self) -> bool:
        """
        Disable vision service by unloading the model.
        
        This frees all VRAM/memory used by the model.
        
        Returns:
            True if successfully disabled
        """
        logger.info("[VisionService] Disabling and unloading model...")
        
        # Unload model
        if self._model:
            del self._model
            self._model = None
        
        if self._tokenizer:
            del self._tokenizer
            self._tokenizer = None
        
        # Force garbage collection and CUDA cache clear
        import gc
        gc.collect()
        
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.synchronize()
            
            # Log freed memory
            vram_mb = torch.cuda.memory_allocated() // (1024 * 1024)
            logger.info(f"[VisionService] VRAM after cleanup: {vram_mb} MB")
        
        # Reset status
        self._status = VisionServiceStatus(
            status=VisionServiceState.DISABLED,
            quantization_enabled=self.enable_quantization
        )
        
        logger.info("[VisionService] Disabled successfully")
        return True
    
    async def analyze_screen(
        self,
        image_base64: str,
        prompt: str = "Describe what you see in this image."
    ) -> VisionAnalyzeResponse:
        """
        Analyze a screen/image using the vision model.
        
        Args:
            image_base64: Base64 encoded image
            prompt: Analysis prompt
            
        Returns:
            VisionAnalyzeResponse with results or error
        """
        import time
        start_time = time.time()
        
        # Check if enabled
        if self._status.status != VisionServiceState.ENABLED:
            return VisionAnalyzeResponse(
                success=False,
                error="Vision service is not enabled. Please enable it in settings."
            )
        
        try:
            # Decode base64 image
            import base64
            from PIL import Image
            import io
            
            image_data = base64.b64decode(image_base64)
            image = Image.open(io.BytesIO(image_data))
            
            # Prepare conversation
            msgs = [{'role': 'user', 'content': [image, prompt]}]
            
            # Run inference
            with torch.no_grad():
                result = self._model.chat(
                    image=image,
                    msgs=msgs,
                    tokenizer=self._tokenizer,
                    sampling=True,
                    temperature=0.7
                )
            
            processing_time = int((time.time() - start_time) * 1000)
            self._status.last_used = datetime.now()
            
            return VisionAnalyzeResponse(
                success=True,
                description=result,
                processing_time_ms=processing_time
            )
            
        except Exception as e:
            logger.error(f"[VisionService] Analysis error: {e}", exc_info=True)
            return VisionAnalyzeResponse(
                success=False,
                error=str(e)
            )
    
    async def detect_gui_element(
        self,
        image_base64: str,
        description: str
    ) -> Dict[str, Any]:
        """
        Detect a GUI element by description.
        
        Args:
            image_base64: Base64 encoded screenshot
            description: Description of element to find
            
        Returns:
            Dict with coordinates and confidence
        """
        if self._status.status != VisionServiceState.ENABLED:
            return {
                "success": False,
                "error": "Vision service is not enabled"
            }
        
        try:
            prompt = f"Find the coordinates of this element: {description}. Return as JSON with x, y, width, height."
            result = await self.analyze_screen(image_base64, prompt)
            
            if not result.success:
                return {"success": False, "error": result.error}
            
            # Parse coordinates from response
            # This is simplified - actual implementation would parse JSON from model output
            return {
                "success": True,
                "description": result.description,
                "processing_time_ms": result.processing_time_ms
            }
            
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def is_available(self) -> bool:
        """Check if vision service is available (model exists)"""
        return os.path.exists(self.model_path)
    
    def get_status_dict(self) -> Dict[str, Any]:
        """Get status as dictionary for JSON serialization"""
        return {
            "status": self._status.status.value,
            "vram_usage_mb": self._status.vram_usage_mb,
            "load_progress_percent": self._status.load_progress_percent,
            "error_message": self._status.error_message,
            "last_used": self._status.last_used.isoformat() if self._status.last_used else None,
            "model_name": self._status.model_name,
            "quantization_enabled": self._status.quantization_enabled,
            "is_available": self.is_available()
        }


# Global singleton instance
_vision_service: Optional[VisionService] = None


def get_vision_service(
    model_path: Optional[str] = None,
    enable_quantization: bool = True
) -> VisionService:
    """
    Get the singleton VisionService instance.
    
    Args:
        model_path: Path to model (optional)
        enable_quantization: Whether to use 4-bit quantization
        
    Returns:
        VisionService instance
    """
    global _vision_service
    if _vision_service is None:
        _vision_service = VisionService(
            model_path=model_path,
            enable_quantization=enable_quantization
        )
    return _vision_service


def reset_vision_service():
    """Reset the singleton (mainly for testing)"""
    global _vision_service
    _vision_service = None
    VisionService._instance = None
    VisionService._initialized = False
