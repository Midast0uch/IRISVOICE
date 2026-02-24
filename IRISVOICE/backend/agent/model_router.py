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

    def __repr__(self):
        return f"<ModelRouter(models={list(self.models.keys())}, ready={self.is_ready()})>"