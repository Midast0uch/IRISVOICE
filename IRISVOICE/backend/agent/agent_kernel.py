#!/usr/bin/env python3
"""
Agent Kernel

Orchestrates the dual-LLM system with:
- lfm2-8b for reasoning and planning
- lfm2.5-1.2b-instruct for tool execution
- Inter-model communication and state management
- Model failure fallback to single-model mode
"""

from typing import Any, Dict, Optional, List
import json
import asyncio
import logging
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

from .model_router import ModelRouter
from .memory import ConversationMemory, TaskRecord
from .personality import PersonalityManager
from .vps_gateway import VPSGateway, VPSConfig
from .inter_model_communication import InterModelCommunicator
from .model_conversation import ModelConversation


@dataclass
class TaskContext:
    """
    Carries full context through the entire task pipeline.
    
    This is the single object that carries context from the user's message
    through planning, execution, and response synthesis. It prevents context
    loss at handoff points between the brain and executor models.
    """
    task_id: str                          # unique per user message
    user_message: str                     # original user request — never lost
    session_id: str
    conversation_history: List[Dict]      # snapshot of memory at task start
    plan: Optional[Dict] = None           # brain's plan (set after planning)
    step_results: List[Dict] = field(default_factory=list)  # accumulates as steps execute
    started_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None
    
    def get_results_summary(self) -> str:
        """Get a formatted summary of all step results for the brain."""
        if not self.step_results:
            return "No tool results."
        
        summary_parts = []
        for i, result in enumerate(self.step_results, 1):
            if isinstance(result, dict):
                if "error" in result:
                    summary_parts.append(f"Step {i}: ERROR - {result.get('error')}")
                elif result.get("success"):
                    tool_name = result.get("tool", "unknown")
                    action = result.get("action", "")
                    result_text = result.get("result", result.get("response", ""))
                    summary_parts.append(f"Step {i}: {tool_name} ({action}): {result_text[:200]}")
        
        return "\n".join(summary_parts) if summary_parts else "No tool results."

class AgentKernel:
    """
    Central orchestrator for the dual-LLM agent system.
    
    Coordinates:
    - lfm2-8b (reasoning model) for planning and analysis
    - lfm2.5-1.2b-instruct (execution model) for tool execution
    - Inter-model communication and state management
    - Model failure fallback to single-model mode
    """

    def __init__(
        self, 
        config_path: str = "./backend/agent/agent_config.yaml",
        session_id: str = "default"
    ):
        """
        Initialize AgentKernel with dual-LLM coordination.
        
        Args:
            config_path: Path to agent configuration YAML
            session_id: Session identifier for conversation memory
        """
        self.config_path = config_path
        self.session_id = session_id
        
        # Core components
        self._model_router: Optional[ModelRouter] = None
        self._vps_gateway: Optional[VPSGateway] = None
        self._conversation_memory: Optional[ConversationMemory] = None
        self._personality: Optional[PersonalityManager] = None
        self._tool_bridge = None  # Will be initialized lazily
        self._inter_model_communicator: Optional[InterModelCommunicator] = None  # For brain↔executor logging
        
        # State management
        self._single_model_mode = False
        self._available_model_id: Optional[str] = None
        self._initialization_error: Optional[str] = None
        
        # Model selection (user-configurable dual-LLM)
        self._selected_reasoning_model: Optional[str] = None
        self._selected_tool_execution_model: Optional[str] = None
        
        # VPS configuration (loaded from settings)
        self._vps_config: Optional[VPSConfig] = None
        
        # Internet access control (default: False to match UI default)
        self._internet_access_enabled: bool = False
        
        # Initialize components
        self._initialize_components()

    def _initialize_components(self):
        """Initialize all core components with error handling."""
        try:
            # Initialize Model Router with UNINITIALIZED mode (lazy loading)
            logger.info("[AgentKernel] Initializing Model Router in UNINITIALIZED mode (lazy loading)...")
            from .model_router import InferenceMode
            self._model_router = ModelRouter(self.config_path, inference_mode=InferenceMode.UNINITIALIZED)
            logger.info("[AgentKernel] Model Router initialized - models will NOT be loaded automatically")
            logger.info("[AgentKernel] Models will be loaded only when user selects Local Model inference mode")
            
            # In UNINITIALIZED mode, we don't have models yet
            logger.info("[AgentKernel] Waiting for user to configure inference mode (Local/VPS/OpenAI)")
            self._single_model_mode = False
                
        except Exception as e:
            logger.error(f"[AgentKernel] Failed to initialize Model Router: {e}")
            self._initialization_error = f"Model Router initialization failed: {e}"
            self._model_router = None
        
        try:
            # Initialize VPS Gateway with default disabled config
            # Configuration will be loaded from settings when available
            logger.info("[AgentKernel] Initializing VPS Gateway...")
            self._vps_config = VPSConfig(enabled=False)
            
            if self._model_router:
                self._vps_gateway = VPSGateway(self._vps_config, self._model_router)
                logger.info("[AgentKernel] VPS Gateway initialized (disabled by default)")
            else:
                logger.warning("[AgentKernel] VPS Gateway not initialized: Model Router unavailable")
                
        except Exception as e:
            logger.error(f"[AgentKernel] Failed to initialize VPS Gateway: {e}")
            self._vps_gateway = None
        
        try:
            # Initialize Conversation Memory
            logger.info(f"[AgentKernel] Initializing Conversation Memory for session {self.session_id}...")
            self._conversation_memory = ConversationMemory(
                session_id=self.session_id,
                max_messages=10  # Default from requirements
            )
            logger.info("[AgentKernel] Conversation Memory initialized")
            
        except Exception as e:
            logger.error(f"[AgentKernel] Failed to initialize Conversation Memory: {e}")
            self._initialization_error = f"Conversation Memory initialization failed: {e}"
            self._conversation_memory = None
        
        try:
            # Initialize Personality Manager
            logger.info("[AgentKernel] Initializing Personality Manager...")
            self._personality = PersonalityManager()
            logger.info("[AgentKernel] Personality Manager initialized")
            
        except Exception as e:
            logger.error(f"[AgentKernel] Failed to initialize Personality Manager: {e}")
            self._initialization_error = f"Personality Manager initialization failed: {e}"
            self._personality = None
        
        try:
            # Initialize Inter-Model Communicator for brain↔executor logging (Bug 5 fix)
            logger.info("[AgentKernel] Initializing Inter-Model Communicator...")
            if self._model_router:
                model_conversation = ModelConversation()
                self._inter_model_communicator = InterModelCommunicator(
                    model_router=self._model_router,
                    conversation=model_conversation
                )
                logger.info("[AgentKernel] Inter-Model Communicator initialized")
            else:
                logger.warning("[AgentKernel] Inter-Model Communicator not initialized: Model Router unavailable")
        except Exception as e:
            logger.error(f"[AgentKernel] Failed to initialize Inter-Model Communicator: {e}")
            self._inter_model_communicator = None
        
        # Tool Bridge will be initialized lazily when needed
        
        # Memory Foundation integration
        self._memory_interface: Optional[Any] = None
        
        logger.info("[AgentKernel] Initialization complete")
    
    def set_memory_interface(self, memory_interface: Any) -> None:
        """
        Set the memory interface for the agent kernel.
        
        This is called after AgentKernel initialization to wire in
        the Memory Foundation system.
        
        Args:
            memory_interface: MemoryInterface instance from backend.memory
        """
        self._memory_interface = memory_interface
        logger.info("[AgentKernel] Memory interface connected")
    
    def _get_memory_context(self, task: str) -> str:
        """
        Get memory-augmented context for a task.
        
        Args:
            task: Task description
        
        Returns:
            Context string with memory augmentation
        """
        if self._memory_interface is None:
            return ""
        
        try:
            context = self._memory_interface.get_task_context(
                task=task,
                session_id=self.session_id
            )
            return context
        except Exception as e:
            logger.warning(f"[AgentKernel] Failed to get memory context: {e}")
            return ""
    
    def _store_task_episode(
        self,
        task_summary: str,
        full_content: str,
        outcome_type: str = "success",
        tool_sequence: Optional[List[Dict[str, Any]]] = None
    ) -> None:
        """
        Store a task episode in memory.
        
        Args:
            task_summary: Brief task description
            full_content: Full conversation/task content
            outcome_type: Task outcome (success, failure, etc.)
            tool_sequence: List of tool calls made
        """
        if self._memory_interface is None:
            return
        
        try:
            from backend.memory import Episode
            
            episode = Episode(
                session_id=self.session_id,
                task_summary=task_summary,
                full_content=full_content,
                tool_sequence=tool_sequence or [],
                outcome_type=outcome_type,
                source_channel="websocket",
                node_id="local",
                origin="local"
            )
            
            self._memory_interface.store_episode(episode)
            logger.debug(f"[AgentKernel] Stored episode for task: {task_summary[:50]}...")
            
        except Exception as e:
            logger.warning(f"[AgentKernel] Failed to store episode: {e}")
    
    async def initialize_vps_gateway(self) -> None:
        """
        Initialize VPS Gateway asynchronously.
        
        This should be called after AgentKernel initialization to set up
        the VPS Gateway with async operations (health checks, etc.).
        """
        if self._vps_gateway and self._vps_config and self._vps_config.enabled:
            try:
                logger.info("[AgentKernel] Initializing VPS Gateway async operations...")
                await self._vps_gateway.initialize()
                logger.info("[AgentKernel] VPS Gateway async initialization complete")
            except Exception as e:
                logger.error(f"[AgentKernel] Failed to initialize VPS Gateway async: {e}")
    
    async def shutdown_vps_gateway(self) -> None:
        """
        Shutdown VPS Gateway gracefully.
        
        This should be called when AgentKernel is being shut down to clean up
        VPS Gateway resources (HTTP clients, health check tasks, etc.).
        """
        if self._vps_gateway:
            try:
                logger.info("[AgentKernel] Shutting down VPS Gateway...")
                await self._vps_gateway.shutdown()
                logger.info("[AgentKernel] VPS Gateway shutdown complete")
            except Exception as e:
                logger.error(f"[AgentKernel] Error during VPS Gateway shutdown: {e}")
    
    def configure_vps(self, vps_config: Dict[str, Any]) -> None:
        """
        Configure VPS Gateway from settings.
        
        Args:
            vps_config: Dictionary containing VPS configuration fields from agent.vps subnode
                - enabled: bool - Enable VPS routing
                - endpoints: List[str] - VPS endpoint URLs
                - auth_token: str - Authentication token
                - timeout: int - Request timeout in seconds
                - health_check_interval: int - Health check interval in seconds
                - fallback_to_local: bool - Fall back to local on VPS failure
                - load_balancing: bool - Enable load balancing
                - load_balancing_strategy: str - "round_robin" or "least_loaded"
                - protocol: str - "rest" or "websocket"
                - offload_tools: bool - Offload tool execution to VPS
        """
        try:
            logger.info(f"[AgentKernel] Configuring VPS Gateway: {vps_config}")
            
            # Create VPSConfig from settings
            self._vps_config = VPSConfig(
                enabled=vps_config.get("enabled", False),
                endpoints=vps_config.get("endpoints", []),
                auth_token=vps_config.get("auth_token"),
                timeout=vps_config.get("timeout", 30),
                health_check_interval=vps_config.get("health_check_interval", 60),
                fallback_to_local=vps_config.get("fallback_to_local", True),
                load_balancing=vps_config.get("load_balancing", False),
                load_balancing_strategy=vps_config.get("load_balancing_strategy", "round_robin"),
                protocol=vps_config.get("protocol", "rest"),
                offload_tools=vps_config.get("offload_tools", False)
            )
            
            # Recreate VPS Gateway with new config
            if self._model_router:
                self._vps_gateway = VPSGateway(self._vps_config, self._model_router)
                logger.info(f"[AgentKernel] VPS Gateway reconfigured: enabled={self._vps_config.enabled}, endpoints={len(self._vps_config.endpoints)}")
            else:
                logger.warning("[AgentKernel] Cannot configure VPS Gateway: Model Router unavailable")
                
        except Exception as e:
            logger.error(f"[AgentKernel] Failed to configure VPS Gateway: {e}")
            self._vps_config = VPSConfig(enabled=False)
            if self._model_router:
                self._vps_gateway = VPSGateway(self._vps_config, self._model_router)

    def process_text_message(self, text: str, session_id: Optional[str] = None) -> str:
        """
        Process a text message with dual-LLM coordination.
        
        Workflow:
        1. Add user message to conversation memory
        2. Plan task using lfm2-8b (reasoning model)
        3. Execute plan using lfm2.5-1.2b-instruct (execution model)
        4. Generate response and add to conversation memory
        
        Args:
            text: User's text message
            session_id: Optional session ID (uses instance session_id if not provided)
            
        Returns:
            Agent's response text
        """
        # Use provided session_id or fall back to instance session_id
        if session_id is None:
            session_id = self.session_id
        
        # Check if agent is available
        if self._initialization_error:
            error_msg = f"Agent kernel is not available: {self._initialization_error}"
            logger.error(f"[AgentKernel] {error_msg}")
            return error_msg
        
        if not self._model_router or not self._conversation_memory:
            error_msg = "Agent kernel is not available"
            logger.error(f"[AgentKernel] {error_msg}")
            return error_msg
        
        # Create TaskContext to carry full context through pipeline (fixes Bug 3, 4, 5, 6)
        import uuid
        task_id = str(uuid.uuid4())
        
        try:
            # Add user message to conversation memory
            self._conversation_memory.add_message("user", text)
            logger.info(f"[AgentKernel] Processing text message: {text[:50]}...")
            
            # Get conversation context
            context = self._conversation_memory.get_context()
        except Exception as e:
            # Handle conversation memory errors gracefully
            logger.warning(f"[AgentKernel] Conversation memory error: {e}")
            context = []  # Continue with empty context

        # Create TaskContext with initial data
        task = TaskContext(
            task_id=task_id,
            user_message=text,
            session_id=session_id,
            conversation_history=context
        )

        # Plan task using reasoning model with timeout
        try:
            plan = self.plan_task(text, context)
            task.plan = plan  # Store plan in TaskContext
        except TimeoutError as e:
            error_response = f"Request timed out while planning: {e}"
            logger.error(f"[AgentKernel] {error_response}")
            self._conversation_memory.add_message("assistant", error_response)
            return error_response
        except Exception as e:
            error_response = f"Error planning task: {e}"
            logger.error(f"[AgentKernel] {error_response}", exc_info=True)
            self._conversation_memory.add_message("assistant", error_response)
            return error_response
        
        if "error" in plan:
            error_response = f"Error planning task: {plan['error']}"
            self._conversation_memory.add_message("assistant", error_response)
            return error_response
        
        # Execute plan using execution model with timeout
        try:
            execution_results = self.execute_plan(plan)
            # Accumulate results in TaskContext (fixes Bug 4)
            task.step_results = execution_results
        except TimeoutError as e:
            error_response = f"Request timed out during execution: {e}"
            logger.error(f"[AgentKernel] {error_response}")
            self._conversation_memory.add_message("assistant", error_response)
            return error_response
        except Exception as e:
            error_response = f"Error executing plan: {e}"
            logger.error(f"[AgentKernel] {error_response}", exc_info=True)
            self._conversation_memory.add_message("assistant", error_response)
            return error_response
        
        # Generate final response using brain synthesis (fixes Bug 2)
        response = self._synthesize_response(task, execution_results)
        
        # Add assistant response to conversation memory
        try:
            self._conversation_memory.add_message("assistant", response)
        except Exception as e:
            # Log but don't fail if memory update fails
            logger.warning(f"[AgentKernel] Failed to save response to conversation memory: {e}")
        
        # Record task for session-level memory continuity (fixes Bug 6)
        try:
            task.completed_at = time.time()
            had_failures = any(
                isinstance(r, dict) and "error" in r
                for r in execution_results
            )
            tool_names_used = list(set(
                r.get("tool", "unknown")
                for r in execution_results
                if isinstance(r, dict)
            ))
            
            task_record = TaskRecord(
                task_id=task.task_id,
                user_message=task.user_message,
                summary=response,
                step_count=len(execution_results),
                had_failures=had_failures,
                tool_names_used=tool_names_used,
                started_at=task.started_at,
                completed_at=task.completed_at,
                session_id=task.session_id
            )
            self._conversation_memory.record_task(task_record)
            logger.info(f"[AgentKernel] Recorded task {task.task_id} to session memory")
        except Exception as e:
            logger.warning(f"[AgentKernel] Failed to record task: {e}")
        
        logger.info(f"[AgentKernel] Generated response: {response[:50]}...")
        return response

    def plan_task(self, task_description: str, context: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """
        Use lfm2-8b (reasoning model) for task planning with timeout and error handling.
        
        Args:
            task_description: User's task/query
            context: Optional conversation context
            
        Returns:
            Plan dictionary with steps, or error dictionary
            
        Raises:
            TimeoutError: If inference exceeds 30 seconds
        """
        start_time = time.time()
        timeout_seconds = 30
        
        try:
            logger.info("[AgentKernel] Planning task with reasoning model...")
            
            # Get reasoning model
            reasoning_model = None
            if self._model_router:
                try:
                    # Use user-selected reasoning model if available
                    if self._selected_reasoning_model:
                        reasoning_model = self._model_router.models.get(self._selected_reasoning_model)
                        if reasoning_model:
                            logger.info(f"[AgentKernel] Using user-selected reasoning model: {self._selected_reasoning_model}")
                        else:
                            logger.warning(f"[AgentKernel] Selected model {self._selected_reasoning_model} unavailable, falling back to default")
                            reasoning_model = self._model_router.get_reasoning_model()
                            if reasoning_model:
                                default_model_id = getattr(reasoning_model, 'model_id', 'unknown')
                                logger.info(f"[AgentKernel] Fallback successful: using default reasoning model {default_model_id}")
                    else:
                        # Use default reasoning model
                        reasoning_model = self._model_router.get_reasoning_model()
                        if reasoning_model:
                            default_model_id = getattr(reasoning_model, 'model_id', 'unknown')
                            logger.info(f"[AgentKernel] No model selected, using default reasoning model: {default_model_id}")
                except Exception as e:
                    logger.error(f"[AgentKernel] Error getting reasoning model: {e}")
                    return {"error": f"Failed to access reasoning model: {e}"}
            
            # Handle model unavailability
            if not reasoning_model:
                if self._single_model_mode and self._available_model_id:
                    # Fall back to available model
                    logger.warning("[AgentKernel] Reasoning model unavailable, using fallback model")
                    try:
                        reasoning_model = self._model_router.models.get(self._available_model_id)
                    except Exception as e:
                        logger.error(f"[AgentKernel] Error accessing fallback model: {e}")
                        return {"error": f"Failed to access fallback model: {e}"}
                else:
                    return {"error": "Reasoning model not available"}
            
            # Build planning prompt with personality and context
            system_prompt = ""
            if self._personality:
                try:
                    system_prompt = self._personality.get_system_prompt()
                except Exception as e:
                    logger.warning(f"[AgentKernel] Error getting system prompt: {e}")
            
            context_str = ""
            if context:
                context_str = "\n\nConversation Context:\n" + json.dumps(context[-5:], indent=2)
            
            planning_prompt = f"""{system_prompt}

You are analyzing a user request and creating an execution plan.

Task: {task_description}{context_str}

Create a structured plan with these steps:
1. Analyze what the user wants
2. Determine if tools are needed
3. Break down into actionable steps

Respond with a JSON object:
{{
    "analysis": "brief analysis of the request",
    "requires_tools": true/false,
    "steps": [
        {{
            "step": 1,
            "action": "description",
            "tool": "tool_name or null",
            "parameters": {{}}
        }}
    ]
}}"""
            
            # Use VPS Gateway for inference if available, otherwise use local model
            plan_response = None
            if self._vps_gateway:
                try:
                    logger.info("[AgentKernel] Using VPS Gateway for planning inference...")
                    # Check if we're in an async context
                    try:
                        loop = asyncio.get_running_loop()
                        # We're in an async context, cannot use run_until_complete
                        logger.warning("[AgentKernel] Cannot use VPS Gateway in sync method from async context, using direct model access")
                        plan_response = None
                    except RuntimeError:
                        # No running loop, we can create one
                        plan_response = asyncio.run(
                            self._vps_gateway.infer(
                                model="lfm2-8b",
                                prompt=planning_prompt,
                                context={"conversation_history": context} if context else {},
                                params={"max_tokens": 1024, "temperature": 0.7},
                                session_id=self.session_id
                            )
                        )
                        logger.info("[AgentKernel] VPS Gateway inference complete")
                except TimeoutError:
                    logger.error("[AgentKernel] VPS Gateway inference timed out")
                    raise
                except Exception as e:
                    logger.warning(f"[AgentKernel] VPS Gateway inference failed, falling back to direct model: {e}")
                    plan_response = None
            
            # Fall back to direct model access if VPS Gateway not available or failed
            if plan_response is None:
                # Check timeout before loading model
                elapsed = time.time() - start_time
                if elapsed > timeout_seconds:
                    raise TimeoutError(f"Planning timed out after {elapsed:.1f}s")
                
                # Load model if needed with error handling
                try:
                    if not reasoning_model.is_loaded():
                        logger.info("[AgentKernel] Loading reasoning model...")
                        reasoning_model.load()
                except Exception as e:
                    logger.error(f"[AgentKernel] Failed to load reasoning model: {e}")
                    return {"error": f"Model loading failed: {e}"}
                
                # Check timeout before inference
                elapsed = time.time() - start_time
                if elapsed > timeout_seconds:
                    raise TimeoutError(f"Planning timed out after {elapsed:.1f}s")
                
                # Generate plan with error handling
                try:
                    plan_response = reasoning_model.generate(
                        planning_prompt,
                        max_tokens=1024,
                        temperature=0.7
                    )
                except Exception as e:
                    logger.error(f"[AgentKernel] Model inference failed: {e}")
                    # Attempt to restart model
                    try:
                        logger.info("[AgentKernel] Attempting to restart reasoning model...")
                        reasoning_model.unload()
                        reasoning_model.load()
                        plan_response = reasoning_model.generate(
                            planning_prompt,
                            max_tokens=1024,
                            temperature=0.7
                        )
                        logger.info("[AgentKernel] Model restarted successfully")
                    except Exception as restart_error:
                        logger.error(f"[AgentKernel] Model restart failed: {restart_error}")
                        return {"error": f"Model crashed and restart failed: {restart_error}"}
            
            # Check timeout after inference
            elapsed = time.time() - start_time
            if elapsed > timeout_seconds:
                raise TimeoutError(f"Planning timed out after {elapsed:.1f}s")
            
            # Parse JSON response
            try:
                plan = json.loads(plan_response)
                logger.info(f"[AgentKernel] Plan generated with {len(plan.get('steps', []))} steps in {elapsed:.2f}s")
                return plan
            except json.JSONDecodeError:
                # If not valid JSON, create a simple plan
                logger.warning("[AgentKernel] Failed to parse plan as JSON, creating simple plan")
                return {
                    "analysis": plan_response[:200],
                    "requires_tools": False,
                    "steps": [
                        {
                            "step": 1,
                            "action": "respond_to_user",
                            "tool": None,
                            "parameters": {"response": plan_response}
                        }
                    ]
                }
                
        except TimeoutError:
            logger.error(f"[AgentKernel] Planning timed out after {timeout_seconds}s")
            raise
        except Exception as e:
            error_msg = f"Error during task planning: {e}"
            logger.error(f"[AgentKernel] {error_msg}", exc_info=True)
            return {"error": error_msg}

    def execute_plan(self, plan: Dict[str, Any]) -> List[Any]:
        """
        Execute a plan using lfm2.5-1.2b-instruct (execution model).
        
        Args:
            plan: Plan dictionary from plan_task()
            
        Returns:
            List of execution results for each step
        """
        results = []
        steps = plan.get("steps", [])
        
        logger.info(f"[AgentKernel] Executing plan with {len(steps)} steps...")
        
        for step in steps:
            try:
                result = self.execute_step(step)
                results.append(result)
                logger.debug(f"[AgentKernel] Step {step.get('step')} completed")
            except Exception as e:
                error_result = {"error": f"Step {step.get('step')} failed: {e}"}
                results.append(error_result)
                logger.error(f"[AgentKernel] {error_result['error']}")
        
        return results
    
    def execute_step(self, step: Dict[str, Any]) -> Any:
        """
        Execute a single plan step using execution model with timeout and error handling.
        
        Args:
            step: Step dictionary with action, tool, and parameters
            
        Returns:
            Execution result
            
        Raises:
            TimeoutError: If execution exceeds 30 seconds
        """
        start_time = time.time()
        timeout_seconds = 30
        
        tool_name = step.get("tool")
        parameters = step.get("parameters", {})
        action = step.get("action", "")
        
        # If no tool specified, return the action as response
        if not tool_name:
            return {"response": action, "success": True}
        
        # Get execution model
        execution_model = None
        if self._model_router:
            try:
                # Use user-selected tool execution model if available
                if self._selected_tool_execution_model:
                    execution_model = self._model_router.models.get(self._selected_tool_execution_model)
                    if execution_model:
                        logger.info(f"[AgentKernel] Using user-selected tool execution model: {self._selected_tool_execution_model}")
                    else:
                        logger.warning(f"[AgentKernel] Selected model {self._selected_tool_execution_model} unavailable, falling back to default")
                        execution_model = self._model_router.get_execution_model()
                        if execution_model:
                            default_model_id = getattr(execution_model, 'model_id', 'unknown')
                            logger.info(f"[AgentKernel] Fallback successful: using default tool execution model {default_model_id}")
                else:
                    # Use default execution model
                    execution_model = self._model_router.get_execution_model()
                    if execution_model:
                        default_model_id = getattr(execution_model, 'model_id', 'unknown')
                        logger.info(f"[AgentKernel] No model selected, using default tool execution model: {default_model_id}")
            except Exception as e:
                logger.error(f"[AgentKernel] Error getting execution model: {e}")
                return {"error": f"Failed to access execution model: {e}", "success": False}
        
        # Handle model unavailability
        if not execution_model:
            if self._single_model_mode and self._available_model_id:
                # Fall back to available model
                logger.warning("[AgentKernel] Execution model unavailable, using fallback model")
                try:
                    execution_model = self._model_router.models.get(self._available_model_id)
                except Exception as e:
                    logger.error(f"[AgentKernel] Error accessing fallback model: {e}")
                    return {"error": f"Failed to access fallback model: {e}", "success": False}
            else:
                return {"error": "Execution model not available", "success": False}
        
        try:
            # Create execution prompt
            execution_prompt = f"""Execute the following action:

Action: {action}
Tool: {tool_name}
Parameters: {json.dumps(parameters, indent=2)}

Provide the execution result."""
            
            # Use VPS Gateway for inference if available, otherwise use local model
            result_text = None
            if self._vps_gateway:
                try:
                    logger.info("[AgentKernel] Using VPS Gateway for execution inference...")
                    # Check if we're in an async context
                    try:
                        loop = asyncio.get_running_loop()
                        # We're in an async context, cannot use run_until_complete
                        logger.warning("[AgentKernel] Cannot use VPS Gateway in sync method from async context, using direct model access")
                        result_text = None
                    except RuntimeError:
                        # No running loop, we can create one
                        result_text = asyncio.run(
                            self._vps_gateway.infer(
                                model="lfm2.5-1.2b-instruct",
                                prompt=execution_prompt,
                                context={},
                                params={"max_tokens": 512, "temperature": 0.3},
                                session_id=self.session_id
                            )
                        )
                        logger.info("[AgentKernel] VPS Gateway execution inference complete")
                except TimeoutError:
                    logger.error("[AgentKernel] VPS Gateway execution timed out")
                    raise
                except Exception as e:
                    logger.warning(f"[AgentKernel] VPS Gateway execution inference failed, falling back to direct model: {e}")
                    result_text = None
            
            # Fall back to direct model access if VPS Gateway not available or failed
            if result_text is None:
                # Check timeout before loading model
                elapsed = time.time() - start_time
                if elapsed > timeout_seconds:
                    raise TimeoutError(f"Execution timed out after {elapsed:.1f}s")
                
                # Load model if needed with error handling
                try:
                    if not execution_model.is_loaded():
                        logger.info("[AgentKernel] Loading execution model...")
                        execution_model.load()
                except Exception as e:
                    logger.error(f"[AgentKernel] Failed to load execution model: {e}")
                    return {
                        "tool": tool_name,
                        "action": action,
                        "error": f"Model loading failed: {e}",
                        "success": False
                    }
                
                # Check timeout before inference
                elapsed = time.time() - start_time
                if elapsed > timeout_seconds:
                    raise TimeoutError(f"Execution timed out after {elapsed:.1f}s")
                
                # Generate execution response with error handling
                try:
                    result_text = execution_model.generate(
                        execution_prompt,
                        max_tokens=512,
                        temperature=0.3
                    )
                except Exception as e:
                    logger.error(f"[AgentKernel] Model inference failed: {e}")
                    # Attempt to restart model
                    try:
                        logger.info("[AgentKernel] Attempting to restart execution model...")
                        execution_model.unload()
                        execution_model.load()
                        result_text = execution_model.generate(
                            execution_prompt,
                            max_tokens=512,
                            temperature=0.3
                        )
                        logger.info("[AgentKernel] Model restarted successfully")
                    except Exception as restart_error:
                        logger.error(f"[AgentKernel] Model restart failed: {restart_error}")
                        return {
                            "tool": tool_name,
                            "action": action,
                            "error": f"Model crashed and restart failed: {restart_error}",
                            "success": False
                        }
            
            # Check timeout after inference
            elapsed = time.time() - start_time
            if elapsed > timeout_seconds:
                raise TimeoutError(f"Execution timed out after {elapsed:.1f}s")
            
            # Handle tool execution errors
            if self._tool_bridge:
                try:
                    # Execute tool through tool bridge
                    tool_result = self._tool_bridge.execute_tool(tool_name, parameters)
                    if "error" in tool_result:
                        logger.warning(f"[AgentKernel] Tool execution error: {tool_result['error']}")
                        return {
                            "tool": tool_name,
                            "action": action,
                            "error": tool_result["error"],
                            "success": False
                        }
                except Exception as e:
                    logger.error(f"[AgentKernel] Tool execution failed: {e}")
                    return {
                        "tool": tool_name,
                        "action": action,
                        "error": f"Tool execution failed: {e}",
                        "success": False
                    }
            
            logger.info(f"[AgentKernel] Step executed successfully in {elapsed:.2f}s")
            return {
                "tool": tool_name,
                "action": action,
                "result": result_text,
                "success": True
            }
            
        except TimeoutError:
            logger.error(f"[AgentKernel] Execution timed out after {timeout_seconds}s")
            raise
        except Exception as e:
            error_msg = f"Error executing step: {e}"
            logger.error(f"[AgentKernel] {error_msg}", exc_info=True)
            return {
                "tool": tool_name,
                "action": action,
                "error": error_msg,
                "success": False
            }
    
    def _generate_response(
        self, 
        user_message: str, 
        plan: Dict[str, Any], 
        execution_results: List[Any],
        context: List[Dict[str, Any]]
    ) -> str:
        """
        Generate final response based on plan and execution results.
        
        Args:
            user_message: Original user message
            plan: Generated plan
            execution_results: Results from execute_plan()
            context: Conversation context
            
        Returns:
            Final response text
        """
        # Check if any steps failed
        has_errors = any(
            isinstance(r, dict) and ("error" in r or not r.get("success", True))
            for r in execution_results
        )
        
        # Build response based on results
        if has_errors:
            error_messages = [
                r.get("error", "Unknown error")
                for r in execution_results
                if isinstance(r, dict) and "error" in r
            ]
            return f"I encountered some issues: {'; '.join(error_messages)}"
        
        # Extract successful results
        success_results = [
            r for r in execution_results
            if isinstance(r, dict) and r.get("success", False)
        ]
        
        if not success_results:
            return "I've processed your request."
        
        # Format response based on results
        if len(success_results) == 1:
            result = success_results[0]
            if "response" in result:
                return result["response"]
            elif "result" in result:
                return result["result"]
        
        # Multiple results - summarize
        summary_parts = []
        for r in success_results:
            if "result" in r:
                summary_parts.append(f"- {r.get('action', 'Action')}: {r['result'][:100]}")
            elif "response" in r:
                summary_parts.append(f"- {r['response'][:100]}")
        
        if summary_parts:
            return "I've completed your request:\n\n" + "\n".join(summary_parts)
        
        return "I've processed your request."
    
    def _synthesize_response(
        self,
        task: TaskContext,
        execution_results: List[Any]
    ) -> str:
        """
        Synthesize response using the brain model with tool results.
        
        This addresses Bug 2: The brain now sees the actual tool output
        before generating the final response.
        
        Args:
            task: TaskContext containing user message and plan
            execution_results: Results from execute_plan()
            
        Returns:
            Synthesized response from the brain model
        """
        # Get results summary for the brain
        results_summary = task.get_results_summary()
        
        # Build synthesis prompt for the brain
        synthesis_prompt = f"""User request: {task.user_message}

Tool execution results:
{results_summary}

Based on the tool results above, provide a natural response to the user's request.
If any tools failed, address those issues in your response.
"""
        
        try:
            # Get reasoning model for synthesis
            reasoning_model = None
            if self._model_router:
                if self._selected_reasoning_model:
                    reasoning_model = self._model_router.models.get(self._selected_reasoning_model)
                if not reasoning_model:
                    reasoning_model = self._model_router.get_reasoning_model()
            
            if reasoning_model:
                # Call the brain model for synthesis
                response = reasoning_model.generate(synthesis_prompt)
                logger.info("[AgentKernel] Brain synthesized response with tool results context")
                return response
            else:
                # Fall back to template-based response
                logger.warning("[AgentKernel] No reasoning model available, using fallback response")
                return self._generate_response(task.user_message, task.plan, execution_results, task.conversation_history)
                
        except Exception as e:
            logger.error(f"[AgentKernel] Error in brain synthesis: {e}")
            # Fall back to template-based response
            return self._generate_response(task.user_message, task.plan, execution_results, task.conversation_history)
    
    def get_status(self) -> Dict[str, Any]:
        """
        Get agent status information.
        
        Returns:
            Status dictionary with:
            - ready: bool - if agent is ready to process requests
            - models_loaded: int - number of loaded models
            - total_models: int - total number of models
            - tool_bridge_available: bool - if tool bridge is available
            - model_status: dict - individual model status
            - single_model_mode: bool - if in fallback mode
            - error: str - initialization error if any
            - vps_gateway: dict - VPS Gateway status (enabled, available endpoints, health)
        """
        status = {
            "ready": False,
            "models_loaded": 0,
            "total_models": 0,
            "tool_bridge_available": False,
            "model_status": {},
            "single_model_mode": self._single_model_mode,
            "error": self._initialization_error
        }
        
        # Check model router status
        if self._model_router:
            all_status = self._model_router.get_all_models_status()
            status["model_status"] = all_status
            status["total_models"] = len(all_status)
            status["models_loaded"] = len(self._model_router.get_loaded_models())
            
            # Agent is ready if at least one model is available
            reasoning_model = self._model_router.get_reasoning_model()
            execution_model = self._model_router.get_execution_model()
            status["ready"] = reasoning_model is not None or execution_model is not None
        
        # Check tool bridge status
        if self._tool_bridge:
            try:
                bridge_status = self._tool_bridge.get_status()
                status["tool_bridge_available"] = bridge_status.get("available", False)
            except Exception as e:
                logger.warning(f"[AgentKernel] Failed to get tool bridge status: {e}")
        
        # Add VPS Gateway status
        if self._vps_gateway:
            try:
                vps_status = self._vps_gateway.get_status()
                status["vps_gateway"] = vps_status
                logger.debug(f"[AgentKernel] VPS Gateway status: {vps_status}")
            except Exception as e:
                logger.warning(f"[AgentKernel] Failed to get VPS Gateway status: {e}")
                status["vps_gateway"] = {
                    "enabled": False,
                    "error": str(e)
                }
        else:
            status["vps_gateway"] = {
                "enabled": False,
                "available_endpoints": 0
            }
        
        return status
    
    def clear_conversation(self) -> None:
        """Clear conversation history for the current session."""
        if self._conversation_memory:
            self._conversation_memory.clear()
            logger.info(f"[AgentKernel] Conversation cleared for session {self.session_id}")
    
    def get_conversation_context(self, max_messages: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Get conversation context.
        
        Args:
            max_messages: Optional limit on number of messages
            
        Returns:
            List of message dictionaries
        """
        if self._conversation_memory:
            return self._conversation_memory.get_context(max_messages=max_messages)
        return []
    
    def update_personality(self, config: Dict[str, Any]) -> None:
        """
        Update personality configuration.
        
        Args:
            config: Dictionary containing identity fields
        """
        if self._personality:
            self._personality.load_from_config(config)
            logger.info("[AgentKernel] Personality configuration updated")
    
    def set_model_selection(self, reasoning_model: Optional[str] = None, tool_execution_model: Optional[str] = None) -> bool:
        """
        Set user-selected models for reasoning and tool execution.
        
        Args:
            reasoning_model: Model ID for reasoning tasks (None to use default)
            tool_execution_model: Model ID for tool execution tasks (None to use default)
            
        Returns:
            True if models were set successfully, False otherwise
        """
        try:
            # Validate that selected models are available
            if reasoning_model and self._model_router:
                available_models = self._model_router.get_available_models()
                available_ids = [m["id"] for m in available_models]
                
                if reasoning_model not in available_ids:
                    logger.error(f"[AgentKernel] Reasoning model '{reasoning_model}' not available. Available: {available_ids}")
                    return False
            
            if tool_execution_model and self._model_router:
                available_models = self._model_router.get_available_models()
                available_ids = [m["id"] for m in available_models]
                
                if tool_execution_model not in available_ids:
                    logger.error(f"[AgentKernel] Tool execution model '{tool_execution_model}' not available. Available: {available_ids}")
                    return False
            
            # Set the selected models
            self._selected_reasoning_model = reasoning_model
            self._selected_tool_execution_model = tool_execution_model
            
            logger.info(f"[AgentKernel] Model selection updated: reasoning={reasoning_model}, tool_execution={tool_execution_model}")
            return True
            
        except Exception as e:
            logger.error(f"[AgentKernel] Failed to set model selection: {e}")
            return False
    
    def get_model_selection(self) -> Dict[str, Optional[str]]:
        """
        Get current model selection.
        
        Returns:
            Dictionary with reasoning_model and tool_execution_model keys
        """
        return {
            "reasoning_model": self._selected_reasoning_model,
            "tool_execution_model": self._selected_tool_execution_model
        }
    
    def set_internet_access(self, enabled: bool) -> None:
        """
        Enable or disable agent internet access.
        
        This controls whether the agent can use web search and internet-based tools.
        It does NOT affect application connectivity to VPS or OpenAI services.
        
        Args:
            enabled: True to enable internet access, False to disable
        """
        self._internet_access_enabled = enabled
        logger.info(f"[AgentKernel] Agent internet access {'enabled' if enabled else 'disabled'}")
        logger.info("[AgentKernel] Note: This controls agent web search tools, not application connectivity")
    
    def get_internet_access(self) -> bool:
        """
        Get current internet access setting.
        
        Returns:
            True if internet access is enabled, False otherwise
        """
        return self._internet_access_enabled


# Singleton instance management
_agent_kernel_instances: Dict[str, AgentKernel] = {}


def get_agent_kernel(session_id: str = "default") -> AgentKernel:
    """
    Get or create an AgentKernel instance for a session.
    
    Args:
        session_id: Session identifier
        
    Returns:
        AgentKernel instance for the session
    """
    global _agent_kernel_instances
    
    if session_id not in _agent_kernel_instances:
        _agent_kernel_instances[session_id] = AgentKernel(session_id=session_id)
    
    return _agent_kernel_instances[session_id]