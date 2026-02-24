#!/usr/bin/env python3
"""
Agent Kernel

This module provides the core orchestration logic for the AI agent system,
replacing the UnifiedConversationManager with a model-agnostic approach.
"""

from typing import Any, Dict, Optional, List
import json
import asyncio
import logging

logger = logging.getLogger(__name__)
from backend.ws_manager import get_websocket_manager
from backend.core_models import ModelStatusMessage
from .model_router import ModelRouter
from .lfm_audio_manager import LFMAudioManager
from .gui_toolkit import GUIToolkit
from .skill_registry import SkillRegistry
from .model_conversation import ModelConversation
from .inter_model_communication import InterModelCommunicator
from .tool_bridge import get_agent_tool_bridge, initialize_agent_tools

class AgentKernel:
    """The central orchestrator for the AI agent system."""

    def __init__(self, config_path: str = "./backend/agent/agent_config.yaml"):
        self.config_path = config_path
        self.model_router = None
        self.lfm_audio_manager = None
        self.gui_toolkit = None
        self.skill_registry = None
        self.conversation = None
        self.communicator = None
        self.tool_bridge = None
        self._initialize_components()

    def _broadcast_model_status(self, status: str, message: Optional[str] = None):
        """Broadcasts the current model status to all connected WebSocket clients."""
        # During initialization, just log to console to avoid async issues
        logger.info(f"[AgentKernel] Model status: {status} - {message}")
        
        # Try to broadcast if WebSocket manager is available and initialized
        try:
            ws_manager = get_websocket_manager()
            status_message = ModelStatusMessage(status=status, message=message)
            # Note: This will only work if called from an async context
            # For now, we'll skip broadcasting during sync initialization
        except Exception as e:
            # Silently ignore broadcast errors during initialization
            pass

    def _initialize_components(self):
        """Initializes all the core components of the agent."""
        self._broadcast_model_status("loading", "Initializing Model Router...")
        try:
            self.model_router = ModelRouter(self.config_path)
            loaded_models = [k for k, v in self.model_router.models.items() if v.is_loaded()]
            available_models = list(self.model_router.models.keys())
            if loaded_models:
                self._broadcast_model_status("ready", f"Model Router initialized. Loaded: {loaded_models}, Available: {available_models}")
            else:
                self._broadcast_model_status("ready", f"Model Router initialized. No models loaded yet. Available: {available_models}")
        except Exception as e:
            error_msg = f"Error initializing ModelRouter: {e}"
            logger.warning(f"[AgentKernel] {error_msg}")
            self._broadcast_model_status("warning", error_msg)
            # Continue with empty router instead of crashing
            self.model_router = None

        # Defer loading of heavy models until needed
        self._broadcast_model_status("loading", "LFM Audio Manager (deferred)...")
        self.lfm_audio_manager = None

        self._broadcast_model_status("loading", "GUI Toolkit (deferred)...")
        self.gui_toolkit = None

        self._broadcast_model_status("loading", "Initializing Model Conversation...")
        try:
            self.conversation = ModelConversation()
            self._broadcast_model_status("ready", "Model Conversation initialized.")
        except Exception as e:
            error_msg = f"Error initializing ModelConversation: {e}"
            logger.warning(f"[AgentKernel] {error_msg}")
            self._broadcast_model_status("error", error_msg)

        self._broadcast_model_status("loading", "Skill Registry initializing...")
        try:
            self.skill_registry = SkillRegistry()
            self._broadcast_model_status("ready", "Skill Registry initialized.")
        except Exception as e:
            error_msg = f"Error initializing SkillRegistry: {e}"
            logger.warning(f"[AgentKernel] {error_msg}")
            self._broadcast_model_status("error", error_msg)

        self._broadcast_model_status("loading", "Initializing Inter-Model Communicator...")
        try:
            self.communicator = InterModelCommunicator(self.model_router, self.conversation)
            self._broadcast_model_status("ready", "Inter-Model Communicator initialized.")
        except Exception as e:
            error_msg = f"Error initializing InterModelCommunicator: {e}"
            logger.warning(f"[AgentKernel] {error_msg}")
            self._broadcast_model_status("error", error_msg)

        # Initialize Tool Bridge (connects to all IRIS services)
        self._broadcast_model_status("loading", "Initializing Agent Tool Bridge...")
        try:
            self.tool_bridge = get_agent_tool_bridge()
            self._broadcast_model_status("ready", f"Tool Bridge initialized with {len(self.tool_bridge.get_available_tools())} tools.")
        except Exception as e:
            error_msg = f"Error initializing ToolBridge: {e}"
            logger.warning(f"[AgentKernel] {error_msg}")
            self._broadcast_model_status("warning", error_msg)

        self._broadcast_model_status("ready", "Agent Kernel initialized (models deferred).")

    def process_text_message(self, text: str) -> str:
        """Processes an incoming text message by generating and executing a plan."""
        # Check if core components are available
        if self.conversation is None:
            return "Error: Conversation system not initialized."
        
        if self.communicator is None:
            return "Error: Inter-model communicator not initialized."
        
        self.conversation.add_message("user", text)
        
        # Check if brain model is available
        brain_model = None
        if self.model_router:
            brain_model = self.model_router.get_model("reasoning")
        
        if brain_model is None:
            # If no brain model, provide a helpful message
            return "Brain model (lfm2-8b) is not loaded. Please ensure the model files are present at ./models/LFM2-8B-A1B"
        
        plan = self.plan_task(text)
        if "error" in plan:
            self.conversation.add_message("assistant", {"error": plan["error"]})
            return plan["error"]

        execution_result = self.execute_plan(plan)
        
        # Format a nice response
        if execution_result:
            results_summary = []
            for r in execution_result:
                if isinstance(r, dict):
                    if "output_data" in r:
                        results_summary.append(str(r.get("output_data", {})))
                    elif "response" in r:
                        results_summary.append(r.get("response"))
                    elif "error" in r:
                        results_summary.append(f"Error: {r.get('error')}")
                    else:
                        results_summary.append(str(r))
                else:
                    results_summary.append(str(r))
            
            final_response = "I've completed your request:\n\n" + "\n".join(f"- {r}" for r in results_summary)
        else:
            final_response = "I've processed your request."
        
        self.conversation.add_message("assistant", {"plan": plan, "execution_result": execution_result})
        return final_response

    async def process_text_message_async(self, text: str) -> str:
        """Asynchronously processes an incoming text message."""
        return self.process_text_message(text)

    def plan_task(self, task_description: str) -> Dict[str, Any]:
        """Uses the 'brain' model to generate a plan for the given task."""
        try:
            self._broadcast_model_status("processing", "Generating execution plan...")
            
            history_str = json.dumps(self.conversation.get_history(), indent=2)
            
            planning_prompt = f"""
            You are a planning agent. Given a task and the conversation history, create a step-by-step execution plan.
            
            Conversation History:
            {history_str}

            Task: {task_description}
            
            Output the plan as a JSON object with the following structure:
            {{
                "steps": [
                    {{
                        "step": 1,
                        "action": "description of the action",
                        "tool": "tool_name",
                        "parameters": {{ "key": "value" }}
                    }}
                ]
            }}
            Ensure the plan is detailed and actionable.
            """
            
            # Use brain model (reasoning capability) to generate plan
            if self.communicator is None:
                return {"error": "Inter-model communicator not initialized."}
            
            plan_json_str = self.communicator.get_response("reasoning", planning_prompt)
            
            # Try to parse as JSON, if not create a simple response
            try:
                plan = json.loads(plan_json_str)
            except json.JSONDecodeError:
                # If brain model returns plain text, wrap it in a simple plan
                plan = {
                    "steps": [
                        {
                            "step": 1,
                            "action": plan_json_str,
                            "tool": None,
                            "parameters": {}
                        }
                    ]
                }
            
            self._broadcast_model_status("ready", "Execution plan generated.")
            self.conversation.add_message("assistant", {"plan": plan})
            return plan
            
        except Exception as e:
            import traceback
            error_msg = f"Error during planning: {e}"
            logger.error(f"[AgentKernel] {error_msg}")
            traceback.print_exc()
            self._broadcast_model_status("error", error_msg)
            return {"error": error_msg}

    def execute_plan(self, plan: Dict[str, Any]) -> List[Any]:
        """Executes a given plan."""
        results = []
        for step in plan.get("steps", []):
            result = self.execute_step(step)
            self.conversation.add_message("assistant", {"step": step, "result": result})
            results.append(result)
        return results

    def execute_step(self, step: Dict[str, Any]) -> Any:
        """Executes a single step of a plan using the executor model."""
        tool_name = step.get("tool")
        parameters = step.get("parameters", {})
        
        # If no tool is specified, just return the action as response
        if not tool_name:
            return {"response": step.get("action", "No action specified")}
        
        # If executor model is available, use it for tool execution
        if self.communicator and self.model_router:
            executor = self.model_router.get_model("tool_execution")
            if executor:
                # Use executor model to process the tool request
                try:
                    self._broadcast_model_status("processing", f"Executing tool: {tool_name}...")
                    
                    # Create a tool request for the executor
                    tool_request = self.communicator.create_tool_request(
                        tool_name=tool_name,
                        parameters=parameters,
                        context=f"Execute tool: {tool_name}",
                        priority="normal"
                    )
                    
                    # Send to executor model
                    response = self.communicator.send_tool_request_to_executor(tool_request)
                    
                    self._broadcast_model_status("ready", f"Tool {tool_name} executed.")
                    return response.to_dict() if hasattr(response, 'to_dict') else {"result": str(response)}
                    
                except Exception as e:
                    error_msg = f"Error executing tool via executor: {e}"
                    logger.warning(f"[AgentKernel] {error_msg}")
                    # Fall back to direct skill execution
        
        # Fallback: direct skill execution
        if self.skill_registry is None:
            return {"error": "Skill registry not initialized."}
        
        skill = self.skill_registry.get_skill(tool_name)
        if not skill:
            return {"error": f"Skill '{tool_name}' not found."}

        try:
            return skill(**parameters)
        except Exception as e:
            return {"error": f"Error executing skill '{tool_name}': {e}"}

    def process_audio(self, audio_data: bytes):
        """Processes incoming audio data."""
        if not self.lfm_audio_manager:
            return
        # ... (audio processing logic)
        pass

# Singleton instance
_agent_kernel: Optional['AgentKernel'] = None

def get_agent_kernel() -> AgentKernel:
    """Get the singleton AgentKernel instance."""
    global _agent_kernel
    if _agent_kernel is None:
        _agent_kernel = AgentKernel()
    return _agent_kernel