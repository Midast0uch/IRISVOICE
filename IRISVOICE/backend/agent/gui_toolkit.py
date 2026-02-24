#!/usr/bin/env python3
"""
GUI Toolkit

This module provides a toolkit for GUI interaction using MiniCPM.
It wraps the MiniCPM model to provide screenshot analysis, element finding, and action validation.
"""

import os
import logging
from typing import Any, Dict, List, Optional
from PIL import Image
import io
import base64

logger = logging.getLogger(__name__)

class GUIToolkit:
    """A toolkit for GUI interaction using MiniCPM."""

    def __init__(self, model_path: Optional[str] = None):
        """Initialize the GUI Toolkit.

        Args:
            model_path: Path to the MiniCPM model. If None, it will be loaded from a default location.
        """
        self.model_path = model_path or "./models/MiniCPM-V-2_6" # Default path
        self.model = None
        self.tokenizer = None
        # Lazy loading - model loads on first use
        logger.info(f"[GUIToolkit] Created. Model will load on first use (lazy loading).")

    def _load_model(self):
        """Load the MiniCPM model and tokenizer."""
        # Check if already loaded
        if self.model is not None and self.tokenizer is not None:
            return
            
        if not os.path.exists(self.model_path):
            logger.warning(f"[GUIToolkit] Model not found at {self.model_path}. GUI capabilities will be disabled.")
            return

        logger.info(f"[GUIToolkit] Loading MiniCPM model from {self.model_path}...")
        try:
            # Import here to avoid dependency issues if MiniCPM is not installed
            from transformers import AutoModel, AutoTokenizer
            self.model = AutoModel.from_pretrained(self.model_path, trust_remote_code=True)
            self.tokenizer = AutoTokenizer.from_pretrained(self.model_path, trust_remote_code=True)
            logger.info("[GUIToolkit] MiniCPM model loaded successfully.")
        except Exception as e:
            logger.error(f"[GUIToolkit] Error loading MiniCPM model: {e}")
            logger.warning("[GUIToolkit] GUI capabilities will be disabled.")

    def take_screenshot(self) -> Optional[Image.Image]:
        """Take a screenshot of the current screen.

        Returns:
            A PIL Image object, or None if the screenshot could not be taken.
        """
        try:
            # Import here to avoid dependency issues if mss is not installed
            import mss
            with mss.mss() as sct:
                # Get the primary monitor
                monitor = sct.monitors[0]
                screenshot = sct.grab(monitor)
                img = Image.frombytes('RGB', screenshot.size, screenshot.bgra, 'raw', 'BGRX')
                return img
        except Exception as e:
            logger.error(f"[GUIToolkit] Error taking screenshot: {e}")
            return None

    def find_element(self, description: str, screenshot: Optional[Image.Image] = None) -> Dict[str, Any]:
        """Find an element on the screen based on a description.

        Args:
            description: A natural language description of the element to find.
            screenshot: A PIL Image object. If None, a new screenshot will be taken.

        Returns:
            A dictionary containing information about the found element, or an error message.
        """
        # Lazy load model on first use
        if not self.model or not self.tokenizer:
            self._load_model()
        
        if not self.model or not self.tokenizer:
            return {"error": "MiniCPM model failed to load."}

        if screenshot is None:
            screenshot = self.take_screenshot()
            if screenshot is None:
                return {"error": "Could not take a screenshot."}

        try:
            # Prepare the prompt for the model
            prompt = f"Find the element described as: '{description}'. Provide the coordinates and a brief description of the element."

            # Process the image and prompt with the model
            # This is a placeholder for the actual MiniCPM inference logic
            # The exact method call will depend on the MiniCPM API
            # For example:
            # response = self.model.chat(
            #     image=screenshot,
            #     msgs=[{"role": "user", "content": prompt}],
            #     tokenizer=self.tokenizer,
            # )

            # Placeholder response
            response = {
                "element_found": True,
                "coordinates": {"x": 100, "y": 200, "width": 50, "height": 30},
                "description": f"Found element matching '{description}'",
                "confidence": 0.85
            }

            return response

        except Exception as e:
            logger.error(f"[GUIToolkit] Error finding element: {e}")
            return {"error": f"Error finding element: {e}"}

    def validate_action(self, action: str, target_description: str, screenshot: Optional[Image.Image] = None) -> Dict[str, Any]:
        """Validate if an action can be performed on a target element.

        Args:
            action: The action to validate (e.g., "click", "type", "scroll").
            target_description: A description of the target element.
            screenshot: A PIL Image object. If None, a new screenshot will be taken.

        Returns:
            A dictionary containing validation results.
        """
        # Lazy load model on first use
        if not self.model or not self.tokenizer:
            self._load_model()
        
        if not self.model or not self.tokenizer:
            return {"valid": False, "error": "MiniCPM model failed to load."}

        if screenshot is None:
            screenshot = self.take_screenshot()
            if screenshot is None:
                return {"valid": False, "error": "Could not take a screenshot."}

        try:
            # Prepare the prompt for the model
            prompt = f"Can the action '{action}' be performed on the element described as '{target_description}'? Explain why or why not."

            # Process the image and prompt with the model
            # This is a placeholder for the actual MiniCPM inference logic
            # The exact method call will depend on the MiniCPM API

            # Placeholder response
            response = {
                "valid": True,
                "reasoning": f"The action '{action}' can be performed on '{target_description}'.",
                "confidence": 0.90
            }

            return response

        except Exception as e:
            logger.error(f"[GUIToolkit] Error validating action: {e}")
            return {"valid": False, "error": f"Error validating action: {e}"}

    def analyze_screen(self, screenshot: Optional[Image.Image] = None) -> Dict[str, Any]:
        """Analyze the current screen and provide a description.

        Args:
            screenshot: A PIL Image object. If None, a new screenshot will be taken.

        Returns:
            A dictionary containing screen analysis results.
        """
        # Lazy load model on first use
        if not self.model or not self.tokenizer:
            self._load_model()
        
        if not self.model or not self.tokenizer:
            return {"error": "MiniCPM model failed to load."}

        if screenshot is None:
            screenshot = self.take_screenshot()
            if screenshot is None:
                return {"error": "Could not take a screenshot."}

        try:
            # Prepare the prompt for the model
            prompt = "Describe the current screen. What applications are open? What UI elements are visible?"

            # Process the image and prompt with the model
            # This is a placeholder for the actual MiniCPM inference logic
            # The exact method call will depend on the MiniCPM API

            # Placeholder response
            response = {
                "description": "A screenshot of a desktop environment with several applications open.",
                "applications": ["File Explorer", "Web Browser", "Code Editor"],
                "ui_elements": ["Start Menu", "Taskbar", "Window Title Bars"],
                "confidence": 0.80
            }

            return response

        except Exception as e:
            logger.error(f"[GUIToolkit] Error analyzing screen: {e}")
            return {"error": f"Error analyzing screen: {e}"}

    def is_ready(self) -> bool:
        """Check if the toolkit is ready to use."""
        return self.model is not None and self.tokenizer is not None