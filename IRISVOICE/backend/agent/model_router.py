#!/usr/bin/env python3
"""
Model Router

This module provides a router to select the appropriate model based on required capabilities.
"""

import os
import logging
import yaml
from typing import List, Optional, Dict, Any

logger = logging.getLogger(__name__)
from .model_wrapper import ModelWrapper

class ModelRouter:
    """Routes requests to the appropriate model based on capabilities."""

    def __init__(self, config_path: str = "./backend/agent/agent_config.yaml"):
        self.config_path = config_path
        self.models: Dict[str, ModelWrapper] = {}
        self._load_config()

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

    def __repr__(self):
        return f"<ModelRouter(models={list(self.models.keys())}, ready={self.is_ready()})>"