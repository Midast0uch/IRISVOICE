#!/usr/bin/env python3
"""
Inter-Model Communication

This module provides a robust class to manage communication between different models
in the agent system with standardized JSON-based request/response protocols.
"""

import json
import logging
import uuid
import time
from datetime import datetime
from typing import Any, Dict, Optional, List
from enum import Enum

logger = logging.getLogger(__name__)
from .model_router import ModelRouter
from .model_conversation import ModelConversation


class MessagePriority(Enum):
    """Priority levels for inter-model messages."""
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"


class ExecutionStatus(Enum):
    """Status codes for tool execution results."""
    SUCCESS = "success"
    FAILURE = "failure"
    PARTIAL = "partial"
    TIMEOUT = "timeout"
    INVALID_REQUEST = "invalid_request"


class ToolRequest:
    """Standardized tool request from brain model to executor model."""

    def __init__(
        self,
        request_id: str,
        tool_name: str,
        parameters: Dict[str, Any],
        context: str = "",
        priority: MessagePriority = MessagePriority.NORMAL
    ):
        self.request_id = request_id
        self.timestamp = datetime.now().isoformat()
        self.tool_name = tool_name
        self.parameters = parameters
        self.context = context
        self.priority = priority

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "request_id": self.request_id,
            "timestamp": self.timestamp,
            "tool_name": self.tool_name,
            "parameters": self.parameters,
            "context": self.context,
            "priority": self.priority.value
        }

    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ToolRequest':
        """Create from dictionary."""
        return cls(
            request_id=data.get("request_id", str(uuid.uuid4())),
            tool_name=data.get("tool_name", ""),
            parameters=data.get("parameters", {}),
            context=data.get("context", ""),
            priority=MessagePriority(data.get("priority", "normal"))
        )

    @classmethod
    def from_json(cls, json_str: str) -> Optional['ToolRequest']:
        """Deserialize from JSON string."""
        try:
            data = json.loads(json_str)
            return cls.from_dict(data)
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.error(f"[InterModelComm] Failed to parse ToolRequest: {e}")
            return None


class ToolResponse:
    """Standardized tool response from executor model to brain model."""

    def __init__(
        self,
        request_id: str,
        status: ExecutionStatus,
        output_data: Any = None,
        error_message: Optional[str] = None,
        diagnostics: Optional[Dict[str, Any]] = None
    ):
        self.request_id = request_id
        self.timestamp = datetime.now().isoformat()
        self.status = status
        self.output_data = output_data or {}
        self.error_message = error_message
        self.diagnostics = diagnostics or {}

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "request_id": self.request_id,
            "timestamp": self.timestamp,
            "status": self.status.value,
            "output_data": self.output_data,
            "error_message": self.error_message,
            "diagnostics": self.diagnostics
        }

    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ToolResponse':
        """Create from dictionary."""
        return cls(
            request_id=data.get("request_id", ""),
            status=ExecutionStatus(data.get("status", "failure")),
            output_data=data.get("output_data"),
            error_message=data.get("error_message"),
            diagnostics=data.get("diagnostics", {})
        )

    @classmethod
    def from_json(cls, json_str: str) -> Optional['ToolResponse']:
        """Deserialize from JSON string."""
        try:
            data = json.loads(json_str)
            return cls.from_dict(data)
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.error(f"[InterModelComm] Failed to parse ToolResponse: {e}")
            return None

    @classmethod
    def create_success(cls, request_id: str, output_data: Any, diagnostics: Optional[Dict] = None) -> 'ToolResponse':
        """Factory method for successful response."""
        return cls(
            request_id=request_id,
            status=ExecutionStatus.SUCCESS,
            output_data=output_data,
            diagnostics=diagnostics or {}
        )

    @classmethod
    def create_failure(cls, request_id: str, error_message: str, diagnostics: Optional[Dict] = None) -> 'ToolResponse':
        """Factory method for failure response."""
        return cls(
            request_id=request_id,
            status=ExecutionStatus.FAILURE,
            error_message=error_message,
            diagnostics=diagnostics or {}
        )

    @classmethod
    def create_timeout(cls, request_id: str, diagnostics: Optional[Dict] = None) -> 'ToolResponse':
        """Factory method for timeout response."""
        return cls(
            request_id=request_id,
            status=ExecutionStatus.TIMEOUT,
            error_message="Operation timed out",
            diagnostics=diagnostics or {}
        )

    @classmethod
    def create_invalid_request(cls, request_id: str, error_message: str) -> 'ToolResponse':
        """Factory method for invalid request response."""
        return cls(
            request_id=request_id,
            status=ExecutionStatus.INVALID_REQUEST,
            error_message=error_message
        )


class InterModelCommunicator:
    """Manages the communication flow between the brain and executor models with robust error handling."""

    def __init__(
        self,
        model_router: ModelRouter,
        conversation: ModelConversation,
        timeout: float = 30.0,
        max_retries: int = 3
    ):
        self.model_router = model_router
        self.conversation = conversation
        self.timeout = timeout
        self.max_retries = max_retries
        self._request_history: List[Dict[str, Any]] = []

    def _generate_request_id(self) -> str:
        """Generate a unique request ID."""
        return f"req_{uuid.uuid4().hex[:12]}"

    def _record_request(self, request: ToolRequest, response: Optional[ToolResponse] = None):
        """Record request/response in history."""
        self._request_history.append({
            "request": request.to_dict(),
            "response": response.to_dict() if response else None,
            "recorded_at": datetime.now().isoformat()
        })
        # Keep only last 100 requests
        if len(self._request_history) > 100:
            self._request_history = self._request_history[-100:]

    def create_tool_request(
        self,
        tool_name: str,
        parameters: Dict[str, Any],
        context: str = "",
        priority: MessagePriority = MessagePriority.NORMAL
    ) -> ToolRequest:
        """Create a standardized tool request."""
        return ToolRequest(
            request_id=self._generate_request_id(),
            tool_name=tool_name,
            parameters=parameters,
            context=context,
            priority=priority
        )

    def get_response(self, model_capability: str, prompt: str) -> Any:
        """Gets a response from a model with a specific capability.
        
        This is the main entry point for brain model communication.
        """
        model = self.model_router.get_model(model_capability)
        if not model:
            error_response = {
                "error": f"No model with '{model_capability}' capability found.",
                "available_capabilities": self.model_router.list_available_capabilities()
            }
            logger.error(f"[InterModelComm] {error_response['error']}")
            return json.dumps(error_response)

        try:
            response = model.generate(prompt)
            self.conversation.add_message(model_capability, response)
            return response
        except Exception as e:
            error_msg = f"Error generating response from {model_capability} model: {e}"
            logger.error(f"[InterModelComm] {error_msg}")
            error_response = {"error": error_msg, "model_capability": model_capability}
            return json.dumps(error_response)

    def send_tool_request_to_executor(self, request: ToolRequest) -> ToolResponse:
        """Send a tool request to the executor model for processing.
        
        The executor model interprets the request and returns a structured response.
        """
        # Create prompt for executor model
        executor_prompt = self._build_executor_prompt(request)
        
        # Get executor model
        executor = self.model_router.get_model("tool_execution")
        if not executor:
            # Fallback: return error response if executor not available
            error_response = ToolResponse.create_failure(
                request.request_id,
                "Executor model not available for tool execution"
            )
            self._record_request(request, error_response)
            return error_response

        try:
            # Get response from executor model
            executor_response = executor.generate(executor_prompt)
            
            # Try to parse the executor's response as a ToolResponse
            # The executor should return JSON in ToolResponse format
            tool_response = self._parse_executor_response(request, executor_response)
            
            self._record_request(request, tool_response)
            return tool_response
            
        except Exception as e:
            error_response = ToolResponse.create_failure(
                request.request_id,
                f"Error executing tool request: {str(e)}"
            )
            self._record_request(request, error_response)
            return error_response

    def _build_executor_prompt(self, request: ToolRequest) -> str:
        """Build a prompt for the executor model to process the tool request."""
        return f"""You are a tool execution agent. Process the following tool request and return the result.

Tool Request:
{request.to_json()}

Available Tools:
- read_file: Read contents of a file (parameters: path)
- write_file: Write contents to a file (parameters: path, content)
- list_directory: List directory contents (parameters: path, recursive)
- create_directory: Create a new directory (parameters: path)
- delete_file: Delete a file or directory (parameters: path)
- open_url: Open a URL in browser (parameters: url)
- search: Search using default search engine (parameters: query)
- launch_app: Launch an application (parameters: app_name)
- get_system_info: Get system information (parameters: none)

Return your response as a JSON object with the following structure:
{{
    "request_id": "{request.request_id}",
    "status": "success|failure|partial",
    "output_data": {{...}},
    "error_message": null or "error description",
    "diagnostics": {{"execution_time": 0.1}}
}}

Execute the tool and provide the results."""

    def _parse_executor_response(self, request: ToolRequest, executor_output: str) -> ToolResponse:
        """Parse the executor model's output into a ToolResponse."""
        try:
            # Try to parse as JSON
            data = json.loads(executor_output)
            
            # Validate required fields
            if "status" not in data:
                raise ValueError("Missing 'status' field in executor response")
            
            return ToolResponse.from_dict(data)
            
        except json.JSONDecodeError:
            # If not JSON, treat the output as the result
            return ToolResponse.create_success(
                request.request_id,
                {"output": executor_output.strip()},
                {"parsing": "raw_text"}
            )
        except Exception as e:
            return ToolResponse.create_failure(
                request.request_id,
                f"Failed to parse executor response: {str(e)}"
            )

    def get_request_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent request history."""
        return self._request_history[-limit:]

    def clear_history(self):
        """Clear request history."""
        self._request_history = []

    def get_status(self) -> Dict[str, Any]:
        """Get communicator status."""
        return {
            "timeout": self.timeout,
            "max_retries": self.max_retries,
            "request_history_count": len(self._request_history),
            "available_capabilities": self.model_router.list_available_capabilities(),
            "loaded_models": list(self.model_router.models.keys())
        }
