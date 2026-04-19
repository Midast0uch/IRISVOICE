#!/usr/bin/env python3
"""
Inter-Model Communication

Manages direct brain ↔ executor communication with full context preservation.
All messages carry the originating TaskContext so neither model ever loses
track of the user's original intent or prior execution results.
"""

import json
import logging
import uuid
import time
from datetime import datetime
from typing import Any, Dict, Optional, List
from enum import Enum
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

from .model_router import ModelRouter
from .model_conversation import ModelConversation


class MessagePriority(Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"


class ExecutionStatus(Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    PARTIAL = "partial"
    TIMEOUT = "timeout"
    INVALID_REQUEST = "invalid_request"


class ToolRequest:
    """
    Standardized tool request from brain to executor.

    Critically includes `user_intent` and `prior_results` so the executor
    always understands WHY it's being asked to execute a tool and WHAT has
    already happened in the task.
    """

    def __init__(
        self,
        request_id: str,
        tool_name: str,
        parameters: Dict[str, Any],
        context: str = "",
        priority: MessagePriority = MessagePriority.NORMAL,
        # Context engineering additions:
        user_intent: str = "",
        prior_results: Optional[List[Dict[str, Any]]] = None,
        step_rationale: str = ""
    ):
        self.request_id = request_id
        self.timestamp = datetime.now().isoformat()
        self.tool_name = tool_name
        self.parameters = parameters
        self.context = context
        self.priority = priority
        self.user_intent = user_intent
        self.prior_results = prior_results or []
        self.step_rationale = step_rationale

    def to_dict(self) -> Dict[str, Any]:
        return {
            "request_id": self.request_id,
            "timestamp": self.timestamp,
            "tool_name": self.tool_name,
            "parameters": self.parameters,
            "context": self.context,
            "priority": self.priority.value,
            "user_intent": self.user_intent,
            "prior_results": self.prior_results,
            "step_rationale": self.step_rationale
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ToolRequest':
        return cls(
            request_id=data.get("request_id", str(uuid.uuid4())),
            tool_name=data.get("tool_name", ""),
            parameters=data.get("parameters", {}),
            context=data.get("context", ""),
            priority=MessagePriority(data.get("priority", "normal")),
            user_intent=data.get("user_intent", ""),
            prior_results=data.get("prior_results", []),
            step_rationale=data.get("step_rationale", "")
        )

    @classmethod
    def from_json(cls, json_str: str) -> Optional['ToolRequest']:
        try:
            return cls.from_dict(json.loads(json_str))
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.error(f"[InterModelComm] Failed to parse ToolRequest: {e}")
            return None


class ToolResponse:
    """
    Standardized tool response from executor to brain.

    Includes execution metadata so the brain can reason about what happened
    and why, not just whether it succeeded.
    """

    def __init__(
        self,
        request_id: str,
        status: ExecutionStatus,
        output_data: Any = None,
        error_message: Optional[str] = None,
        diagnostics: Optional[Dict[str, Any]] = None,
        tool_name: str = "",
        user_intent: str = ""
    ):
        self.request_id = request_id
        self.timestamp = datetime.now().isoformat()
        self.status = status
        self.output_data = output_data or {}
        self.error_message = error_message
        self.diagnostics = diagnostics or {}
        # Echo back identifiers so brain can correlate without lookup
        self.tool_name = tool_name
        self.user_intent = user_intent

    def to_dict(self) -> Dict[str, Any]:
        return {
            "request_id": self.request_id,
            "timestamp": self.timestamp,
            "status": self.status.value,
            "output_data": self.output_data,
            "error_message": self.error_message,
            "diagnostics": self.diagnostics,
            "tool_name": self.tool_name,
            "user_intent": self.user_intent
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict())

    @property
    def succeeded(self) -> bool:
        return self.status == ExecutionStatus.SUCCESS

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ToolResponse':
        return cls(
            request_id=data.get("request_id", ""),
            status=ExecutionStatus(data.get("status", "failure")),
            output_data=data.get("output_data"),
            error_message=data.get("error_message"),
            diagnostics=data.get("diagnostics", {}),
            tool_name=data.get("tool_name", ""),
            user_intent=data.get("user_intent", "")
        )

    @classmethod
    def from_json(cls, json_str: str) -> Optional['ToolResponse']:
        try:
            return cls.from_dict(json.loads(json_str))
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.error(f"[InterModelComm] Failed to parse ToolResponse: {e}")
            return None

    @classmethod
    def create_success(cls, request: 'ToolRequest', output_data: Any, diagnostics: Optional[Dict] = None) -> 'ToolResponse':
        return cls(
            request_id=request.request_id,
            status=ExecutionStatus.SUCCESS,
            output_data=output_data,
            diagnostics=diagnostics or {},
            tool_name=request.tool_name,
            user_intent=request.user_intent
        )

    @classmethod
    def create_failure(cls, request_id: str, error_message: str, tool_name: str = "", diagnostics: Optional[Dict] = None) -> 'ToolResponse':
        return cls(
            request_id=request_id,
            status=ExecutionStatus.FAILURE,
            error_message=error_message,
            diagnostics=diagnostics or {},
            tool_name=tool_name
        )

    @classmethod
    def create_timeout(cls, request_id: str, tool_name: str = "") -> 'ToolResponse':
        return cls(
            request_id=request_id,
            status=ExecutionStatus.TIMEOUT,
            error_message="Operation timed out",
            tool_name=tool_name
        )

    @classmethod
    def create_invalid_request(cls, request_id: str, error_message: str) -> 'ToolResponse':
        return cls(request_id=request_id, status=ExecutionStatus.INVALID_REQUEST, error_message=error_message)


class InterModelCommunicator:
    """
    Manages brain ↔ executor communication with full context integrity.

    Key design principles:
    1. Every ToolRequest carries user_intent and prior_results
    2. Every ToolResponse echoes back tool_name and user_intent for correlation
    3. ModelConversation records the full inter-model dialogue for debugging
    4. Request history retains the full context objects, not just IDs
    """

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
        return f"req_{uuid.uuid4().hex[:12]}"

    def _record_exchange(self, request: ToolRequest, response: Optional[ToolResponse] = None):
        """Record request/response with full context for debugging."""
        self._request_history.append({
            "request": request.to_dict(),
            "response": response.to_dict() if response else None,
            "recorded_at": datetime.now().isoformat()
        })
        if len(self._request_history) > 100:
            self._request_history = self._request_history[-100:]

        # Also record in ModelConversation so the inter-model dialogue is visible
        self.conversation.add_message(
            role="brain_to_executor",
            content={
                "tool": request.tool_name,
                "user_intent": request.user_intent,
                "parameters": request.parameters
            }
        )
        if response:
            self.conversation.add_message(
                role="executor_to_brain",
                content={
                    "status": response.status.value,
                    "output": response.output_data,
                    "error": response.error_message
                }
            )

    def create_tool_request(
        self,
        tool_name: str,
        parameters: Dict[str, Any],
        context: str = "",
        priority: MessagePriority = MessagePriority.NORMAL,
        user_intent: str = "",
        prior_results: Optional[List[Dict[str, Any]]] = None,
        step_rationale: str = ""
    ) -> ToolRequest:
        """Create a ToolRequest with full context attached."""
        return ToolRequest(
            request_id=self._generate_request_id(),
            tool_name=tool_name,
            parameters=parameters,
            context=context,
            priority=priority,
            user_intent=user_intent,
            prior_results=prior_results or [],
            step_rationale=step_rationale
        )

    def get_response(self, model_capability: str, prompt: str) -> Any:
        """Get a response from a model. Records in conversation history."""
        model = self.model_router.get_model(model_capability)
        if not model:
            error = {
                "error": f"No model with '{model_capability}' capability found.",
                "available_capabilities": self.model_router.list_available_capabilities()
            }
            logger.error(f"[InterModelComm] {error['error']}")
            return json.dumps(error)

        try:
            response = model.generate(prompt)
            self.conversation.add_message(model_capability, response)
            return response
        except Exception as e:
            error_msg = f"Error generating response from {model_capability} model: {e}"
            logger.error(f"[InterModelComm] {error_msg}")
            return json.dumps({"error": error_msg, "model_capability": model_capability})

    def send_tool_request_to_executor(self, request: ToolRequest) -> ToolResponse:
        """
        Send a tool request to the executor model.

        The executor receives the full ToolRequest including:
        - user_intent: what the user originally asked for
        - prior_results: what has already been executed this task
        - step_rationale: why this tool was chosen by the brain

        This ensures the executor can adapt its parameter resolution and
        provide meaningful results even for ambiguous inputs.
        """
        executor_prompt = self._build_executor_prompt(request)

        executor = self.model_router.get_model("tool_execution")
        if not executor:
            response = ToolResponse.create_failure(
                request.request_id,
                "Executor model not available",
                tool_name=request.tool_name
            )
            self._record_exchange(request, response)
            return response

        try:
            executor_output = executor.generate(executor_prompt)
            tool_response = self._parse_executor_response(request, executor_output)
            self._record_exchange(request, tool_response)
            return tool_response
        except Exception as e:
            response = ToolResponse.create_failure(
                request.request_id,
                f"Error executing tool request: {str(e)}",
                tool_name=request.tool_name
            )
            self._record_exchange(request, response)
            return response

    def _build_executor_prompt(self, request: ToolRequest) -> str:
        """
        Build executor prompt with full context so it can resolve parameters
        intelligently against prior results.
        """
        prior_context = ""
        if request.prior_results:
            prior_context = "\nPrevious steps in this task:\n" + json.dumps(
                request.prior_results, indent=2
            )[:600]

        return f"""You are a tool execution agent. Execute the requested tool and return the result.

User's original request: {request.user_intent or "Not specified"}
Step rationale: {request.step_rationale or "Execute as requested"}
{prior_context}

Tool to execute:
{request.to_json()}

Available tools and signatures:
- read_file(path): Read file contents
- write_file(path, content): Write to file
- list_directory(path, recursive): List directory
- create_directory(path): Create directory
- delete_file(path): Delete file/directory
- open_url(url): Open URL in browser
- search(query): Web search
- launch_app(app_name): Launch application
- get_system_info(): Get system information

Return ONLY a JSON object:
{{
    "request_id": "{request.request_id}",
    "status": "success|failure|partial",
    "output_data": {{}},
    "error_message": null,
    "diagnostics": {{"execution_time_ms": 100}}
}}"""

    def _parse_executor_response(self, request: ToolRequest, executor_output: str) -> ToolResponse:
        """Parse executor output into a ToolResponse using OutputParser (5-format priority chain)."""
        try:
            from backend.agent.mcm_protocol.actions.output_parse import OutputParser
            parsed = OutputParser().parse(executor_output)
            if parsed.tool_calls:
                tc = parsed.tool_calls[0]
                output_data = tc.get("arguments", tc)
            else:
                output_data = {"output": parsed.content or executor_output.strip()}
            return ToolResponse(
                request_id=request.request_id,
                status=ExecutionStatus.SUCCESS,
                output_data=output_data,
                diagnostics={
                    "parsing": "output_parser",
                    "format": getattr(parsed, "format_used", "unknown"),
                },
                tool_name=request.tool_name,
                user_intent=request.user_intent,
            )
        except Exception as e:
            # Final fallback: try legacy JSON parse, then raw text
            try:
                data = json.loads(executor_output)
                if "status" in data:
                    response = ToolResponse.from_dict(data)
                    response.tool_name = request.tool_name
                    response.user_intent = request.user_intent
                    return response
            except Exception:
                pass
            return ToolResponse(
                request_id=request.request_id,
                status=ExecutionStatus.SUCCESS,
                output_data={"output": executor_output.strip()},
                diagnostics={"parsing": "raw_text_fallback", "error": str(e)},
                tool_name=request.tool_name,
                user_intent=request.user_intent,
            )

    def get_request_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        return self._request_history[-limit:]

    def get_conversation_history(self) -> List[Dict[str, Any]]:
        """Get the full brain ↔ executor conversation log."""
        return self.conversation.get_history()

    def clear_history(self):
        self._request_history = []
        self.conversation.clear_history()

    def get_status(self) -> Dict[str, Any]:
        return {
            "timeout": self.timeout,
            "max_retries": self.max_retries,
            "request_history_count": len(self._request_history),
            "conversation_turns": len(self.conversation.get_history()),
            "available_capabilities": self.model_router.list_available_capabilities(),
            "loaded_models": list(self.model_router.models.keys())
        }