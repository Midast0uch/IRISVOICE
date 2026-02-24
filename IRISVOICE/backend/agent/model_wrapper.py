#!/usr/bin/env python3
"""
Model Wrapper

This module provides a wrapper for different AI models, abstracting their specific
loading and interaction details.
"""

import os
import logging
from typing import Any, Dict, List, Optional
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

logger = logging.getLogger(__name__)

class ModelWrapper:
    """Wraps an AI model, providing a standard interface for loading and generation."""

    def __init__(self, model_id: str, model_path: str, capabilities: List[str], constraints: Optional[Dict[str, Any]] = None):
        self.model_id = model_id
        self.model_path = model_path
        self.capabilities = capabilities
        self.constraints = constraints or {}
        self.device = self.constraints.get("device", "cuda" if torch.cuda.is_available() else "cpu")
        self.dtype = self.constraints.get("dtype", "auto")
        self.model = None
        self.tokenizer = None
        # Lazy loading - model loads on first use, not during init
        # Call self._load_model() when needed via generate() or other methods
        logger.info(f"[{self.model_id}] ModelWrapper created. Model will load on first use (lazy loading).")

    def _load_model(self):
        """Loads the model and tokenizer based on the provided path and constraints."""
        if not os.path.exists(self.model_path):
            logger.warning(f"[{self.model_id}] Model path does not exist: {self.model_path}")
            logger.info(f"[{self.model_id}] Model will be available when file is present.")
            self.model = None
            self.tokenizer = None
            return

        logger.info(f"[{self.model_id}] Loading model from: {self.model_path}")
        try:
            self.tokenizer = AutoTokenizer.from_pretrained(self.model_path)
            # Map string dtype to torch dtype
            torch_dtype_map = {
                "bfloat16": torch.bfloat16,
                "float16": torch.float16,
                "float32": torch.float32,
            }
            torch_dtype = torch_dtype_map.get(self.dtype, "auto")

            self.model = AutoModelForCausalLM.from_pretrained(
                self.model_path,
                device_map="auto",
                torch_dtype=torch_dtype,
                offload_folder="./offload",
            )
            logger.info(f"[{self.model_id}] Model loaded successfully on {self.device}.")
        except Exception as e:
            logger.error(f"[{self.model_id}] Failed to load model: {e}")
            logger.warning(f"[{self.model_id}] Model will be unavailable. Please check the model files.")
            self.model = None
            self.tokenizer = None

    def generate(self, prompt: str, conversation_history: Optional[List[Dict[str, str]]] = None, **gen_kwargs) -> str:
        """Generates a response from the model."""
        # Lazy load model on first use
        if not self.is_loaded():
            self._load_model()
        
        if not self.model or not self.tokenizer:
            raise RuntimeError(f"Model {self.model_id} failed to load.")

        messages = conversation_history or []
        messages.append({"role": "user", "content": prompt})

        input_ids = self.tokenizer.apply_chat_template(
            messages,
            add_generation_prompt=True,
            return_tensors="pt",
        ).to(self.device)

        # Default generation parameters
        default_gen_kwargs = {
            "repetition_penalty": 1.05,
            "max_new_tokens": 512,
        }
        default_gen_kwargs.update(gen_kwargs)

        output_ids = self.model.generate(input_ids, **default_gen_kwargs)
        response_text = self.tokenizer.decode(output_ids[0][input_ids.shape[1]:], skip_special_tokens=True)

        return response_text.strip()

    def has_capability(self, capability: str) -> bool:
        """Checks if the model has a specific capability."""
        return capability in self.capabilities

    def is_loaded(self) -> bool:
        """Check if the model and tokenizer are loaded."""
        return self.model is not None and self.tokenizer is not None

    def load(self) -> bool:
        """Explicitly load the model. Returns True if successful."""
        if not self.is_loaded():
            self._load_model()
        return self.is_loaded()

    def health_check(self, load_if_needed: bool = False) -> dict:
        """Perform a health check on the model.
        
        Args:
            load_if_needed: If True, load the model first before checking health.
                          If False, only check health of already-loaded models.
        """
        if not self.is_loaded():
            if load_if_needed:
                self._load_model()
            else:
                return {
                    "healthy": False,
                    "model_id": self.model_id,
                    "error": "Model not loaded (use load_if_needed=True to load)"
                }

        try:
            # Try a minimal generation to verify the model works
            test_input = "Hello"
            input_ids = self.tokenizer.encode(test_input, return_tensors="pt").to(self.device)
            with torch.no_grad():
                _ = self.model.generate(input_ids, max_new_tokens=1, do_sample=False)

            return {
                "healthy": True,
                "model_id": self.model_id,
                "device": self.device,
                "dtype": self.dtype
            }
        except Exception as e:
            return {
                "healthy": False,
                "model_id": self.model_id,
                "error": str(e)
            }

    def get_status(self) -> dict:
        """Get detailed status of the model."""
        return {
            "model_id": self.model_id,
            "model_path": self.model_path,
            "capabilities": self.capabilities,
            "loaded": self.is_loaded(),
            "device": self.device,
            "dtype": self.dtype,
            "constraints": self.constraints
        }

    def __repr__(self):
        return f"<ModelWrapper(id='{self.model_id}', capabilities={self.capabilities}, loaded={self.is_loaded()})>"