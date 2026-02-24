#!/usr/bin/env python3
"""
Unified Conversation Manager

This module provides a unified conversation manager that orchestrates the LFM audio
and text generation models.
"""

import os
import logging
from typing import Any, Dict, Optional, List
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

logger = logging.getLogger(__name__)

from backend.ws_manager import get_websocket_manager
from backend.core_models import ModelStatusMessage
from .lfm_audio_manager import LFMAudioManager

# --- New LFM Text Manager ---

class LFMTextManager:
    """Manages the LFM text generation model."""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.model_path = config.get("lfm_text_model_path", "./models/LFM2.5-1.2B-Instruct")
        self.model = None
        self.tokenizer = None
        # Lazy loading - model loads on first use
        logger.info(f"[LFMTextManager] Created. Model will load on first use (lazy loading).")

    def _load_model(self):
        """Loads the LFM text model and tokenizer."""
        if not os.path.exists(self.model_path):
            raise FileNotFoundError(f"LFM text model not found at: {self.model_path}")

        logger.info(f"Loading LFM text model from: {self.model_path}")
        try:
            self.tokenizer = AutoTokenizer.from_pretrained(self.model_path)
            self.model = AutoModelForCausalLM.from_pretrained(
                self.model_path,
                device_map="auto",
                torch_dtype=torch.bfloat16, # Recommended for performance
                # attn_implementation="flash_attention_2" # Uncomment on compatible GPU
            )
            logger.info("LFM text model loaded successfully.")
        except Exception as e:
            raise RuntimeError(f"Error loading LFM text model: {e}")

    def generate_response(self, prompt: str, conversation_history: List[Dict[str, str]] = None) -> str:
        """
        Generates a response using the LFM text model.
        """
        # Lazy load model on first use
        if not self.model or not self.tokenizer:
            self._load_model()
        
        if not self.model or not self.tokenizer:
            return "Error: Text model failed to load."

        # Apply the chat template
        messages = conversation_history or []
        messages.append({"role": "user", "content": prompt})
        
        input_ids = self.tokenizer.apply_chat_template(
            messages,
            add_generation_prompt=True,
            return_tensors="pt",
        ).to(self.device)

        # Generation parameters from model card
        gen_kwargs = {
            "repetition_penalty": 1.05,
            "max_new_tokens": 512,
        }

        # Generate response
        output_ids = self.model.generate(input_ids, **gen_kwargs)
        response_text = self.tokenizer.decode(output_ids[0][input_ids.shape[1]:], skip_special_tokens=True)
        
        return response_text.strip()

# --- Unified Conversation Manager ---

_unified_conversation_manager: Optional['UnifiedConversationManager'] = None

class UnifiedConversationManager:
    """
    Manages conversations by orchestrating the speech-to-speech and text models.
    """
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.lfm_audio_manager = None
        self.lfm_text_manager = None
        self._initialize_managers()

    def _broadcast_model_status(self, status: str, message: Optional[str] = None):
        """Broadcasts the current model status to all connected WebSocket clients."""
        try:
            ws_manager = get_websocket_manager()
            status_message = ModelStatusMessage(status=status, message=message)
            ws_manager.broadcast(status_message.model_dump())
            logger.info(f"[UnifiedConversationManager] Broadcasted model status: {status} - {message}")
        except Exception as e:
            logger.error(f"[UnifiedConversationManager] Error broadcasting model status: {e}")

    def _initialize_managers(self):
        """Initializes the LFM Audio and Text Managers."""
        # Initialize Audio Manager
        self._broadcast_model_status("loading", "Initializing LFM Audio Manager...")
        try:
            self.lfm_audio_manager = LFMAudioManager(self.config)
            self._broadcast_model_status("ready", "LFM Audio Manager initialized.")
        except Exception as e:
            error_msg = f"Error initializing LFMAudioManager: {e}"
            logger.warning(f"[UnifiedConversationManager] {error_msg}")
            self._broadcast_model_status("error", error_msg)

        # Initialize Text Manager
        self._broadcast_model_status("loading", "Initializing LFM Text Manager...")
        try:
            self.lfm_text_manager = LFMTextManager(self.config)
            self._broadcast_model_status("ready", "LFM Text Manager initialized.")
        except Exception as e:
            error_msg = f"Error initializing LFMTextManager: {e}"
            logger.warning(f"[UnifiedConversationManager] {error_msg}")
            self._broadcast_model_status("error", error_msg)

    def process_audio(self, audio_data: bytes):
        """Processes incoming audio data."""
        if not self.lfm_audio_manager:
            # ... (error handling)
            return
        # ... (audio processing logic)

    def process_text_message(self, text: str) -> str:
        """Processes an incoming text message and returns the model's response."""
        if not self.lfm_text_manager:
            error_msg = "LFM Text Manager is not initialized."
            self._broadcast_model_status("error", error_msg)
            return error_msg

        try:
            self._broadcast_model_status("processing", "Generating text response...")
            response = self.lfm_text_manager.generate_response(text)
            self._broadcast_model_status("ready", "Text response generated.")
            return response
        except Exception as e:
            import traceback
            error_msg = f"Error during text generation: {e}"
            logger.error(f"[UnifiedConversationManager] {error_msg}")
            traceback.print_exc()
            self._broadcast_model_status("error", error_msg)
            return "Sorry, I encountered an error while generating a response."

def get_unified_conversation_manager() -> UnifiedConversationManager:
    """
    Get the singleton UnifiedConversationManager instance.
    """
    global _unified_conversation_manager
    if _unified_conversation_manager is None:
        default_config = {
            "lfm_text_model_path": "./models/LFM2.5-1.2B-Instruct",
            # Add other relevant audio config here if needed
        }
        _unified_conversation_manager = UnifiedConversationManager(default_config)
    
    return _unified_conversation_manager

# Example Usage:
if __name__ == "__main__":
    logger.info("--- Testing Unified Conversation Manager ---")
    
    manager = get_unified_conversation_manager()
    
    if manager.lfm_text_manager:
        prompt = "What is the capital of France?"
        logger.info(f"User: {prompt}")
        response = manager.process_text_message(prompt)
        logger.info(f"Assistant: {response}")