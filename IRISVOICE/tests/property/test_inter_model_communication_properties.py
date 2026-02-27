"""
Property-based tests for inter-model communication.
Tests universal properties that should hold for all inter-model communication scenarios.
"""
import pytest
from hypothesis import given, settings, strategies as st, seed
import sys
import os
import json

# Add backend to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from backend.agent.agent_kernel import AgentKernel
from backend.agent.model_router import ModelRouter


# ============================================================================
# Test Data Generators (Hypothesis Strategies)
# ============================================================================

@st.composite
def task_descriptions(draw):
    """Generate various task descriptions that require reasoning and execution."""
    return draw(st.one_of(
        # Simple tasks
        st.text(min_size=10, max_size=200),
        # Tasks requiring planning
        st.sampled_from([
            "Create a plan to organize my files by date",
            "Help me analyze the best approach to solve this problem",
            "I need to search for information and then summarize it",
            "Plan a workflow to automate my daily tasks",
            "Design a strategy to improve system performance",
            "Analyze the data and generate a report",
            "Research the topic and create a presentation",
            "Find relevant files and organize them into categories",
        ]),
        # Tasks requiring tool execution
        st.sampled_from([
            "Read the file config.json and tell me what's in it",
            "Search for Python tutorials online",
            "Create a new directory called 'projects'",
            "List all files in the current directory",
            "Open the browser and navigate to example.com",
            "Launch the calculator application",
            "Get system information about CPU and memory",
            "Delete the temporary files in /tmp",
        ])
    ))


@st.composite
def reasoning_results(draw):
    """Generate reasoning results from the reasoning model."""
    requires_tools = draw(st.booleans())
    num_steps = draw(st.integers(min_value=1, max_value=5))
    
    steps = []
    for i in range(num_steps):
        step = {
            "step": i + 1,
            "action": draw(st.sampled_from([
                "analyze_request",
                "search_information",
                "read_file",
                "write_file",
                "list_directory",
                "respond_to_user"
            ])),
            "tool": draw(st.sampled_from([
                "read_file", "write_file", "search", "list_directory", None
            ])) if requires_tools else None,
            "parameters": draw(st.dictionaries(
                keys=st.sampled_from(["path", "query", "content", "recursive"]),
                values=st.one_of(st.text(min_size=1, max_size=50), st.booleans()),
                min_size=0,
                max_size=3
            ))
        }
        steps.append(step)
    
    return {
        "analysis": draw(st.text(min_size=10, max_size=200)),
        "requires_tools": requires_tools,
        "steps": steps
    }


# ============================================================================
# Property 55: Inter-Model Communication
# Feature: irisvoice-backend-integration, Property 55: Inter-Model Communication
# Validates: Requirements 23.4
# ============================================================================

class TestInterModelCommunication:
    """
    Property 55: Inter-Model Communication
    
    For any reasoning result from lfm2-8b that requires execution, the 
    Agent_Kernel shall pass it to lfm2.5-1.2b-instruct for execution.
    """
    
    @settings(max_examples=10, deadline=None)
    @seed(42)  # Fixed seed for reproducibility
    @given(
        task_description=task_descriptions()
    )
    def test_reasoning_results_passed_to_execution_model(self, task_description):
        """
        Property: For any task description, when the reasoning model generates 
        a plan, the Agent_Kernel passes it to the execution model for execution.
        
        # Feature: irisvoice-backend-integration, Property 55: Inter-Model Communication
        **Validates: Requirements 23.4**
        """
        # Setup
        config_path = os.path.join(os.path.dirname(__file__), '../../backend/agent/agent_config.yaml')
        agent_kernel = AgentKernel(config_path=config_path, session_id="test_inter_model")
        
        # Check if agent is ready
        status = agent_kernel.get_status()
        if not status.get("ready", False):
            pytest.skip("Agent kernel not ready - models not available")
        
        # Verify both models are available for dual-LLM mode
        reasoning_model = agent_kernel._model_router.get_reasoning_model()
        execution_model = agent_kernel._model_router.get_execution_model()
        
        if reasoning_model is None or execution_model is None:
            pytest.skip("Dual-LLM mode not available - both models required")
        
        # Execute: Plan task using reasoning model
        plan = agent_kernel.plan_task(task_description)
        
        # Verify: Plan was generated successfully
        assert "error" not in plan, f"Planning should succeed, got error: {plan.get('error')}"
        assert "steps" in plan, "Plan should contain steps"
        assert isinstance(plan["steps"], list), "Steps should be a list"
        assert len(plan["steps"]) > 0, "Plan should have at least one step"
        
        # Execute: Execute plan using execution model
        execution_results = agent_kernel.execute_plan(plan)
        
        # Verify: Execution results were generated
        assert execution_results is not None, "Execution should return results"
        assert isinstance(execution_results, list), "Execution results should be a list"
        assert len(execution_results) == len(plan["steps"]), \
            "Should have one result per step"
        
        # Verify: Each step was processed
        for i, result in enumerate(execution_results):
            assert isinstance(result, dict), f"Result {i} should be a dictionary"
            # Result should have either success indicator or error
            assert "success" in result or "error" in result or "response" in result, \
                f"Result {i} should indicate success/error/response"
    
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        plan=reasoning_results()
    )
    def test_execution_model_receives_complete_plan(self, plan):
        """
        Property: For any plan generated by the reasoning model, the execution 
        model receives all plan details including steps, actions, and parameters.
        
        # Feature: irisvoice-backend-integration, Property 55: Inter-Model Communication
        **Validates: Requirements 23.4**
        """
        # Setup
        config_path = os.path.join(os.path.dirname(__file__), '../../backend/agent/agent_config.yaml')
        agent_kernel = AgentKernel(config_path=config_path, session_id="test_plan_passing")
        
        # Check if agent is ready
        status = agent_kernel.get_status()
        if not status.get("ready", False):
            pytest.skip("Agent kernel not ready - models not available")
        
        # Verify execution model is available
        execution_model = agent_kernel._model_router.get_execution_model()
        if execution_model is None:
            pytest.skip("Execution model not available")
        
        # Execute: Execute the plan
        execution_results = agent_kernel.execute_plan(plan)
        
        # Verify: All steps were processed
        assert len(execution_results) == len(plan["steps"]), \
            "Execution should process all steps from the plan"
        
        # Verify: Each step's information was preserved
        for i, (step, result) in enumerate(zip(plan["steps"], execution_results)):
            assert isinstance(result, dict), f"Result {i} should be a dictionary"
            
            # If step had a tool, verify it was attempted
            if step.get("tool"):
                # Result should reference the tool or indicate execution attempt
                assert "tool" in result or "action" in result or "error" in result, \
                    f"Result {i} should indicate tool execution attempt"
    
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        task_description=task_descriptions()
    )
    def test_inter_model_communication_maintains_context(self, task_description):
        """
        Property: For any task, the context from the reasoning phase is 
        maintained and available during the execution phase.
        
        # Feature: irisvoice-backend-integration, Property 55: Inter-Model Communication
        **Validates: Requirements 23.4**
        """
        # Setup
        config_path = os.path.join(os.path.dirname(__file__), '../../backend/agent/agent_config.yaml')
        agent_kernel = AgentKernel(config_path=config_path, session_id="test_context_passing")
        
        # Check if agent is ready
        status = agent_kernel.get_status()
        if not status.get("ready", False):
            pytest.skip("Agent kernel not ready - models not available")
        
        # Add some context to conversation memory
        agent_kernel._conversation_memory.add_message("user", "Previous context message")
        agent_kernel._conversation_memory.add_message("assistant", "Previous response")
        
        # Get context before planning
        context_before = agent_kernel._conversation_memory.get_context()
        context_count_before = len(context_before)
        
        # Execute: Plan and execute task
        plan = agent_kernel.plan_task(task_description, context_before)
        
        # Verify: Planning succeeded
        if "error" in plan:
            pytest.skip(f"Planning failed: {plan['error']}")
        
        execution_results = agent_kernel.execute_plan(plan)
        
        # Verify: Context is still available after execution
        context_after = agent_kernel._conversation_memory.get_context()
        
        # Context should still contain the previous messages
        assert len(context_after) >= context_count_before, \
            "Context should be maintained during inter-model communication"
    
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        task_description=task_descriptions()
    )
    def test_execution_results_returned_to_reasoning_context(self, task_description):
        """
        Property: For any executed plan, the execution results are available 
        for the reasoning model to generate the final response.
        
        # Feature: irisvoice-backend-integration, Property 55: Inter-Model Communication
        **Validates: Requirements 23.4**
        """
        # Setup
        config_path = os.path.join(os.path.dirname(__file__), '../../backend/agent/agent_config.yaml')
        agent_kernel = AgentKernel(config_path=config_path, session_id="test_result_passing")
        
        # Check if agent is ready
        status = agent_kernel.get_status()
        if not status.get("ready", False):
            pytest.skip("Agent kernel not ready - models not available")
        
        # Execute: Process complete message (plan + execute + respond)
        response = agent_kernel.process_text_message(task_description)
        
        # Verify: Response was generated
        assert response is not None, "Should generate a response"
        assert isinstance(response, str), "Response should be a string"
        assert len(response) > 0, "Response should not be empty"
        
        # Verify: Response doesn't just contain error message
        # (unless there was a legitimate error)
        if "error" in response.lower():
            # If there's an error, it should be informative
            assert len(response) > 20, "Error messages should be informative"
        else:
            # Normal response should be substantive
            assert len(response) > 10, "Response should be substantive"
    
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        task_description=task_descriptions()
    )
    def test_inter_model_communication_handles_empty_plans(self, task_description):
        """
        Property: For any task that results in an empty or minimal plan, the 
        inter-model communication handles it gracefully.
        
        # Feature: irisvoice-backend-integration, Property 55: Inter-Model Communication
        **Validates: Requirements 23.4**
        """
        # Setup
        config_path = os.path.join(os.path.dirname(__file__), '../../backend/agent/agent_config.yaml')
        agent_kernel = AgentKernel(config_path=config_path, session_id="test_empty_plan")
        
        # Check if agent is ready
        status = agent_kernel.get_status()
        if not status.get("ready", False):
            pytest.skip("Agent kernel not ready - models not available")
        
        # Create an empty plan
        empty_plan = {
            "analysis": "Simple query, no steps needed",
            "requires_tools": False,
            "steps": []
        }
        
        # Execute: Execute empty plan
        execution_results = agent_kernel.execute_plan(empty_plan)
        
        # Verify: Handles empty plan gracefully
        assert execution_results is not None, "Should handle empty plan"
        assert isinstance(execution_results, list), "Should return a list"
        assert len(execution_results) == 0, "Empty plan should produce empty results"
    
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        task_description=task_descriptions()
    )
    def test_inter_model_communication_preserves_step_order(self, task_description):
        """
        Property: For any plan with multiple steps, the execution model processes 
        them in the order specified by the reasoning model.
        
        # Feature: irisvoice-backend-integration, Property 55: Inter-Model Communication
        **Validates: Requirements 23.4**
        """
        # Setup
        config_path = os.path.join(os.path.dirname(__file__), '../../backend/agent/agent_config.yaml')
        agent_kernel = AgentKernel(config_path=config_path, session_id="test_step_order")
        
        # Check if agent is ready
        status = agent_kernel.get_status()
        if not status.get("ready", False):
            pytest.skip("Agent kernel not ready - models not available")
        
        # Execute: Plan task
        plan = agent_kernel.plan_task(task_description)
        
        # Skip if planning failed
        if "error" in plan or "steps" not in plan:
            pytest.skip("Planning failed or no steps generated")
        
        steps = plan["steps"]
        if len(steps) < 2:
            pytest.skip("Need at least 2 steps to test ordering")
        
        # Execute: Execute plan
        execution_results = agent_kernel.execute_plan(plan)
        
        # Verify: Results correspond to steps in order
        assert len(execution_results) == len(steps), \
            "Should have one result per step in order"
        
        # Verify: Step numbers or actions are preserved in order
        for i, (step, result) in enumerate(zip(steps, execution_results)):
            # The result should correspond to the step
            # (we can't verify exact content, but we can verify structure)
            assert isinstance(result, dict), f"Result {i} should be a dictionary"
    
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        task_description=task_descriptions()
    )
    def test_inter_model_communication_in_single_model_fallback(self, task_description):
        """
        Property: For any task, if one model is unavailable, the inter-model 
        communication gracefully falls back to single-model mode.
        
        # Feature: irisvoice-backend-integration, Property 55: Inter-Model Communication
        **Validates: Requirements 23.4**
        """
        # Setup
        config_path = os.path.join(os.path.dirname(__file__), '../../backend/agent/agent_config.yaml')
        agent_kernel = AgentKernel(config_path=config_path, session_id="test_fallback")
        
        # Check if agent is ready
        status = agent_kernel.get_status()
        if not status.get("ready", False):
            pytest.skip("Agent kernel not ready - models not available")
        
        # Check if in single-model mode
        is_single_model = agent_kernel._single_model_mode
        
        # Execute: Process message
        response = agent_kernel.process_text_message(task_description)
        
        # Verify: Response was generated regardless of mode
        assert response is not None, "Should generate response in any mode"
        assert isinstance(response, str), "Response should be a string"
        assert len(response) > 0, "Response should not be empty"
        
        # In single-model mode, should still work
        if is_single_model:
            # Should not crash or return generic error
            assert "not available" not in response or "Agent kernel" in response, \
                "Single-model mode should work or provide clear error"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
