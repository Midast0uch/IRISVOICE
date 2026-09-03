#!/usr/bin/env python3
"""
Model Router

This module provides a router to select the appropriate model based on required capabilities.
"""

import os
import logging
import yaml
from enum import Enum
from typing import List, Optional, Dict, Any

logger = logging.getLogger(__name__)
from .model_wrapper import ModelWrapper

TORCH_AVAILABLE = False  # checked lazily on first GPU-memory query


class InferenceMode(Enum):
    """Inference mode for model loading."""
    UNINITIALIZED = "uninitialized"
    LOCAL = "local"
    VPS = "vps"
    OPENAI = "openai"


class ModelRouter:
    """Routes requests to the appropriate model based on capabilities."""

    def __init__(self, config_path: str = "./backend/agent/agent_config.yaml", inference_mode: InferenceMode = InferenceMode.UNINITIALIZED):
        self.config_path = config_path
        self.models: Dict[str, ModelWrapper] = {}
        self.inference_mode = inference_mode
        
        # Only load models if inference mode is LOCAL
        if inference_mode == InferenceMode.LOCAL:
            logger.info("[ModelRouter] Inference mode set to LOCAL - loading models...")
            self._load_config()
        else:
            logger.info(f"[ModelRouter] Inference mode set to {inference_mode.value} - models will NOT be loaded automatically")
            logger.info("[ModelRouter] Models will be loaded only when user selects Local Model inference mode")
    
    def _log_gpu_memory(self, operation: str) -> None:
        """
        Log GPU memory usage before/after operations.
        
        Args:
            operation: Description of the operation (e.g., "before loading", "after loading")
        """
        try:
            import torch
        except ImportError:
            return

        if torch.cuda.is_available():
            for i in range(torch.cuda.device_count()):
                allocated = torch.cuda.memory_allocated(i) / (1024 ** 3)  # Convert to GB
                reserved = torch.cuda.memory_reserved(i) / (1024 ** 3)  # Convert to GB
                total = torch.cuda.get_device_properties(i).total_memory / (1024 ** 3)  # Convert to GB
                logger.info(
                    f"[ModelRouter] GPU {i} memory {operation}: "
                    f"Allocated={allocated:.2f}GB, Reserved={reserved:.2f}GB, Total={total:.2f}GB"
                )
        else:
            logger.info(f"[ModelRouter] GPU memory {operation}: CUDA not available")

    def _load_config(self):
        """Loads model configurations from the YAML file and initializes ModelWrapper instances."""
        if not os.path.exists(self.config_path):
            raise FileNotFoundError(f"Agent configuration file not found at: {self.config_path}")

        with open(self.config_path, 'r') as file:
            config = yaml.safe_load(file)

        for model_config in config.get("models", []):
            model_id = model_config.get("id")
            model_path = model_config.get("path")
            capabilities = model_config.get("capabilities", [])
            constraints = model_config.get("constraints")

            # Skip models that don't have a local path (like the vision model)
            if model_path is None:
                logger.info(f"[{model_id}] Skipping model initialization as path is null.")
                continue

            try:
                self.models[model_id] = ModelWrapper(
                    model_id=model_id,
                    model_path=model_path,
                    capabilities=capabilities,
                    constraints=constraints
                )
                logger.info(f"[{model_id}] Initialized successfully.")
            except Exception as e:
                logger.error(f"[{model_id}] Failed to initialize: {e}")
                # Consider raising the exception or handling it more gracefully

    def set_inference_mode(self, mode: InferenceMode) -> bool:
        """
        Set the inference mode and load/unload models accordingly.
        
        Args:
            mode: The inference mode to set (UNINITIALIZED, LOCAL, VPS, OPENAI)
            
        Returns:
            True if mode was set successfully, False otherwise
        """
        logger.info(f"[ModelRouter] Setting inference mode to {mode.value}")
        
        # If switching from LOCAL to another mode, unload models
        if self.inference_mode == InferenceMode.LOCAL and mode != InferenceMode.LOCAL:
            logger.info("[ModelRouter] Switching from LOCAL mode - unloading models...")
            self.unload_models()
        
        # If switching to LOCAL mode, load models
        if mode == InferenceMode.LOCAL and self.inference_mode != InferenceMode.LOCAL:
            logger.info("[ModelRouter] Switching to LOCAL mode - loading models...")
            
            # Log GPU memory before loading
            self._log_gpu_memory("before loading")
            
            try:
                self._load_config()
                
                # Log GPU memory after loading
                self._log_gpu_memory("after loading")
                
                logger.info("[ModelRouter] Models loaded successfully for LOCAL mode")
            except Exception as e:
                logger.error(f"[ModelRouter] Failed to load models: {e}")
                return False
        
        self.inference_mode = mode
        logger.info(f"[ModelRouter] Inference mode set to {mode.value}")
        return True
    
    def load_models(self) -> bool:
        """
        Load local models into GPU RAM.
        
        Returns:
            True if models were loaded successfully, False otherwise
        """
        if self.inference_mode == InferenceMode.LOCAL and len(self.models) > 0:
            logger.info("[ModelRouter] Models already loaded")
            return True
        
        logger.info("[ModelRouter] Loading local models into GPU RAM...")
        
        # Log GPU memory before loading
        self._log_gpu_memory("before loading")
        
        try:
            self._load_config()
            self.inference_mode = InferenceMode.LOCAL
            
            # Log GPU memory after loading
            self._log_gpu_memory("after loading")
            
            logger.info(f"[ModelRouter] Successfully loaded {len(self.models)} models")
            return True
        except Exception as e:
            logger.error(f"[ModelRouter] Failed to load models: {e}")
            return False
    
    def unload_models(self) -> bool:
        """
        Unload local models from GPU RAM.
        
        Returns:
            True if models were unloaded successfully, False otherwise
        """
        if len(self.models) == 0:
            logger.info("[ModelRouter] No models to unload")
            return True
        
        logger.info(f"[ModelRouter] Unloading {len(self.models)} models from GPU RAM...")
        
        # Log GPU memory before unloading
        self._log_gpu_memory("before unloading")
        
        try:
            # Clear the models dictionary to release references
            self.models.clear()
            
            # Force garbage collection to free GPU memory
            try:
                import torch
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except ImportError:
                pass
            
            # Log GPU memory after unloading
            self._log_gpu_memory("after unloading")
            
            logger.info("[ModelRouter] Models unloaded successfully")
            return True
        except Exception as e:
            logger.error(f"[ModelRouter] Failed to unload models: {e}")
            return False

    def get_model(self, capability: str) -> Optional[ModelWrapper]:
        """Retrieves a model that has the specified capability."""
        for model in self.models.values():
            if model.has_capability(capability):
                return model
        return None

    def get_models_by_capability(self, capability: str) -> List[ModelWrapper]:
        """Retrieves all models that have the specified capability."""
        return [model for model in self.models.values() if model.has_capability(capability)]

    def list_available_capabilities(self) -> List[str]:
        """Lists all unique capabilities available across all loaded models."""
        capabilities = set()
        for model in self.models.values():
            capabilities.update(model.capabilities)
        return list(capabilities)

    def get_all_models_status(self) -> Dict[str, Dict[str, Any]]:
        """Get status of all models (without loading them)."""
        status = {}
        for model_id, model in self.models.items():
            status[model_id] = model.get_status()
        return status

    def check_all_models_health(self, load_if_needed: bool = False) -> Dict[str, Dict[str, Any]]:
        """Check health of all models.
        
        Args:
            load_if_needed: If True, load models before checking health.
        """
        health = {}
        for model_id, model in self.models.items():
            health[model_id] = model.health_check(load_if_needed=load_if_needed)
        return health

    def get_loaded_models(self) -> Dict[str, ModelWrapper]:
        """Get only the models that are currently loaded."""
        return {k: v for k, v in self.models.items() if v.is_loaded()}

    def is_ready(self) -> bool:
        """Check if at least one model is available."""
        return len(self.models) > 0

    def route_message(self, message: str, context: Optional[Dict[str, Any]] = None) -> str:
        """Route a message to the appropriate model based on task type.
        
        Args:
            message: The message/query to route
            context: Optional context dictionary with hints about task type
                    - requires_reasoning: bool - if True, route to reasoning model
                    - requires_tools: bool - if True, route to execution model
        
        Returns:
            The model_id to use for this message
            
        Routing Logic:
            - Tool execution requests → execution model (lfm2.5-1.2b-instruct)
            - Planning and reasoning → reasoning model (lfm2-8b)
            - Simple queries → reasoning model (lfm2-8b)
        """
        context = context or {}
        
        # Check explicit context hints first
        if context.get("requires_tools", False):
            # Route to execution model
            model = self.get_model("tool_execution")
            if model:
                return model.model_id
        
        if context.get("requires_reasoning", False):
            # Route to reasoning model
            model = self.get_model("reasoning")
            if model:
                return model.model_id
        
        # Detect tool execution patterns in the message
        if self._is_tool_execution(message):
            model = self.get_model("tool_execution")
            if model:
                return model.model_id
        
        # Default to reasoning model for planning and general queries
        model = self.get_model("reasoning")
        if model:
            return model.model_id
        
        # Fallback: return any available model
        if self.models:
            return list(self.models.keys())[0]
        
        raise RuntimeError("No models available for routing")
    
    def _is_tool_execution(self, message: str) -> bool:
        """Detect if a message requires tool execution.
        
        Looks for patterns that indicate tool/action execution:
        - Tool call syntax
        - Action keywords
        - Execution commands
        """
        message_lower = message.lower()
        
        # Tool execution indicators
        tool_indicators = [
            "execute",
            "run",
            "call",
            "invoke",
            "perform",
            "action:",
            "tool:",
            "function:",
            "<tool>",
            "</tool>",
            "use tool",
            "apply",
        ]
        
        return any(indicator in message_lower for indicator in tool_indicators)

    def get_reasoning_model(self) -> Optional[ModelWrapper]:
        """Get the reasoning model (lfm2-8b)."""
        return self.get_model("reasoning")

    def get_execution_model(self) -> Optional[ModelWrapper]:
        """Get the execution model (lfm2.5-1.2b-instruct)."""
        return self.get_model("tool_execution")

    def get_reasoning_model_id(self) -> Optional[str]:
        """Return the ID string of the current reasoning model."""
        model = self.get_reasoning_model()
        if model:
            return getattr(model, "model_id", None)
        return list(self.models.keys())[0] if self.models else None

    def get_execution_model_id(self) -> Optional[str]:
        """Return the ID string of the current execution model."""
        model = self.get_execution_model()
        if model:
            return getattr(model, "model_id", None)
        return list(self.models.keys())[-1] if self.models else None
    
    def get_available_models(self) -> List[Dict[str, Any]]:
        """
        Get list of available models from all configured inference sources.
        
        Returns a list of model dictionaries with:
        - id: Model identifier
        - name: Display name
        - source: Inference source (local, vps, openai)
        - capabilities: List of capabilities
        
        Returns:
            List of available model dictionaries
        """
        available_models = []
        
        # Add local models if in LOCAL mode or if models are loaded
        if self.inference_mode == InferenceMode.LOCAL or len(self.models) > 0:
            for model_id, model in self.models.items():
                available_models.append({
                    "id": model_id,
                    "name": model_id,
                    "source": "local",
                    "capabilities": model.capabilities if hasattr(model, 'capabilities') else []
                })
        
        # Add VPS models if VPS mode is configured or active
        if self.inference_mode == InferenceMode.VPS or self.inference_mode == InferenceMode.UNINITIALIZED:
            # Standard VPS models available through the VPS service
            vps_models = [
                {
                    "id": "lfm2-8b",
                    "name": "LFM2 8B",
                    "source": "vps",
                    "capabilities": ["conversation", "tool_execution", "reasoning"]
                },
                {
                    "id": "lfm2.5-1.2b-instruct",
                    "name": "LFM2.5 1.2B Instruct",
                    "source": "vps",
                    "capabilities": ["conversation", "tool_execution", "fast_inference"]
                }
            ]
            available_models.extend(vps_models)
        
        # Add OpenAI models if OpenAI mode is configured or active
        if self.inference_mode == InferenceMode.OPENAI or self.inference_mode == InferenceMode.UNINITIALIZED:
            # Standard OpenAI models available through the API
            openai_models = [
                {
                    "id": "gpt-4",
                    "name": "GPT-4",
                    "source": "openai",
                    "capabilities": ["conversation", "tool_execution", "reasoning", "advanced_reasoning"]
                },
                {
                    "id": "gpt-4-turbo",
                    "name": "GPT-4 Turbo",
                    "source": "openai",
                    "capabilities": ["conversation", "tool_execution", "reasoning", "advanced_reasoning", "fast_inference"]
                },
                {
                    "id": "gpt-3.5-turbo",
                    "name": "GPT-3.5 Turbo",
                    "source": "openai",
                    "capabilities": ["conversation", "tool_execution", "fast_inference"]
                }
            ]
            available_models.extend(openai_models)
        
        logger.info(f"[ModelRouter] Found {len(available_models)} available models from all configured sources")
        return available_models

    def __repr__(self):
        return f"<ModelRouter(models={list(self.models.keys())}, ready={self.is_ready()})>"