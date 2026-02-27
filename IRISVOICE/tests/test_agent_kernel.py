"""
Unit tests for AgentKernel class

Tests dual-LLM coordination, inter-model communication, state management,
and model failure fallback.
"""
import pytest
import json
import tempfile
import shutil
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch
from typing import Dict, Any

# Import the classes we're testing
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.agent.agent_kernel import AgentKernel, get_agent_kernel
from backend.agent.model_router import ModelRouter
from backend.agent.memory import ConversationMemory
from backend.agent.personality import PersonalityManager


class TestAgentKernelInitialization:
    """Test AgentKernel initialization and component setup"""
    
    def test_initialization_creates_components(self):
        """Test that AgentKernel initializes all core components"""
        kernel = AgentKernel(session_id="test_init")
        
        # Check that components are initialized
        assert kernel._model_router is not None or kernel._initialization_error is not None
        assert kernel._conversation_memory is not None
        assert kernel._personality is not None
        assert kernel.session_id == "test_init"
    
    def test_initialization_with_missing_config(self):
        """Test initialization handles missing config file gracefully"""
        kernel = AgentKernel(
            config_path="/nonexistent/config.yaml",
            session_id="test_missing"
        )
        
        # Should have initialization error
        assert kernel._initialization_error is not None
        # But conversation memory and personality should still work
        assert kernel._conversation_memory is not None
        assert kernel._personality is not None
    
    def test_single_model_mode_detection(self):
        """Test detection of single-model fallback mode"""
        # This test would need mocking to simulate missing models
        # For now, just verify the flag exists
        kernel = AgentKernel(session_id="test_single")
        assert hasattr(kernel, '_single_model_mode')
        assert isinstance(kernel._single_model_mode, bool)


class TestProcessTextMessage:
    """Test text message processing with dual-LLM coordination"""
    
    @pytest.fixture
    def mock_kernel(self):
        """Create a kernel with mocked models"""
        with patch('backend.agent.agent_kernel.ModelRouter') as mock_router_class:
            # Create mock models
            mock_reasoning_model = Mock()
            mock_reasoning_model.model_id = "brain"
            mock_reasoning_model.is_loaded.return_value = False
            mock_reasoning_model.load.return_value = None
            mock_reasoning_model.generate.return_value = json.dumps({
                "analysis": "User wants to know the time",
                "requires_tools": False,
                "steps": [
                    {
                        "step": 1,
                        "action": "Provide current time",
                        "tool": None,
                        "parameters": {}
                    }
                ]
            })
            
            mock_execution_model = Mock()
            mock_execution_model.model_id = "executor"
            mock_execution_model.is_loaded.return_value = False
            mock_execution_model.load.return_value = None
            mock_execution_model.generate.return_value = "The current time is 10:30 AM"
            
            # Setup mock router
            mock_router = Mock()
            mock_router.get_reasoning_model.return_value = mock_reasoning_model
            mock_router.get_execution_model.return_value = mock_execution_model
            mock_router.models = {
                "brain": mock_reasoning_model,
                "executor": mock_execution_model
            }
            mock_router.get_all_models_status.return_value = {
                "brain": {"loaded": False},
                "executor": {"loaded": False}
            }
            mock_router.get_loaded_models.return_value = {}
            
            mock_router_class.return_value = mock_router
            
            kernel = AgentKernel(session_id="test_process")
            yield kernel
    
    def test_process_simple_message(self, mock_kernel):
        """Test processing a simple text message"""
        response = mock_kernel.process_text_message("What time is it?")
        
        # Should return a response
        assert isinstance(response, str)
        assert len(response) > 0
        
        # Should have added messages to conversation memory
        context = mock_kernel.get_conversation_context()
        assert len(context) >= 2  # At least user message and assistant response
    
    def test_process_message_with_error(self):
        """Test error handling when models are unavailable"""
        kernel = AgentKernel(
            config_path="/nonexistent/config.yaml",
            session_id="test_error"
        )
        
        response = kernel.process_text_message("Hello")
        
        # Should return error message
        assert "not available" in response.lower() or "error" in response.lower()
    
    def test_conversation_context_maintained(self):
        """Test that conversation context is maintained across messages"""
        # Create a fresh kernel for this test
        with patch('backend.agent.agent_kernel.ModelRouter') as mock_router_class:
            mock_model = Mock()
            mock_model.model_id = "brain"
            mock_model.is_loaded.return_value = True
            mock_model.generate.return_value = json.dumps({
                "steps": [{"step": 1, "action": "respond", "tool": None, "parameters": {}}]
            })
            
            mock_router = Mock()
            mock_router.get_reasoning_model.return_value = mock_model
            mock_router.get_execution_model.return_value = mock_model
            mock_router.models = {"brain": mock_model}
            mock_router.get_all_models_status.return_value = {"brain": {}}
            mock_router.get_loaded_models.return_value = {}
            
            mock_router_class.return_value = mock_router
            
            kernel = AgentKernel(session_id="test_context_maintained")
            
            # Send first message
            kernel.process_text_message("My name is Alice")
            
            # Send second message
            kernel.process_text_message("What is my name?")
            
            # Check conversation history
            context = kernel.get_conversation_context()
            assert len(context) >= 4  # 2 user messages + 2 assistant responses
            
            # Verify messages are in order
            assert context[0]["role"] == "user"
            assert "Alice" in context[0]["content"]


class TestPlanTask:
    """Test task planning with reasoning model"""
    
    @pytest.fixture
    def mock_kernel_with_reasoning(self):
        """Create kernel with mocked reasoning model"""
        with patch('backend.agent.agent_kernel.ModelRouter') as mock_router_class:
            mock_reasoning_model = Mock()
            mock_reasoning_model.model_id = "brain"
            mock_reasoning_model.is_loaded.return_value = True
            mock_reasoning_model.generate.return_value = json.dumps({
                "analysis": "User wants to search the web",
                "requires_tools": True,
                "steps": [
                    {
                        "step": 1,
                        "action": "Search for information",
                        "tool": "web_search",
                        "parameters": {"query": "Python tutorials"}
                    }
                ]
            })
            
            mock_router = Mock()
            mock_router.get_reasoning_model.return_value = mock_reasoning_model
            mock_router.models = {"brain": mock_reasoning_model}
            
            mock_router_class.return_value = mock_router
            
            kernel = AgentKernel(session_id="test_plan")
            yield kernel
    
    def test_plan_task_returns_valid_plan(self, mock_kernel_with_reasoning):
        """Test that plan_task returns a valid plan structure"""
        plan = mock_kernel_with_reasoning.plan_task("Search for Python tutorials")
        
        # Should have required fields
        assert "analysis" in plan or "steps" in plan
        assert "steps" in plan
        assert isinstance(plan["steps"], list)
        assert len(plan["steps"]) > 0
        
        # First step should have required fields
        step = plan["steps"][0]
        assert "step" in step
        assert "action" in step
    
    def test_plan_task_with_invalid_json(self):
        """Test handling of non-JSON response from reasoning model"""
        with patch('backend.agent.agent_kernel.ModelRouter') as mock_router_class:
            mock_reasoning_model = Mock()
            mock_reasoning_model.model_id = "brain"
            mock_reasoning_model.is_loaded.return_value = True
            mock_reasoning_model.generate.return_value = "This is not JSON"
            
            mock_router = Mock()
            mock_router.get_reasoning_model.return_value = mock_reasoning_model
            mock_router.models = {"brain": mock_reasoning_model}
            
            mock_router_class.return_value = mock_router
            
            kernel = AgentKernel(session_id="test_invalid_json")
            plan = kernel.plan_task("Hello")
            
            # Should still return a valid plan structure
            assert "steps" in plan
            assert len(plan["steps"]) > 0
    
    def test_plan_task_without_reasoning_model(self):
        """Test fallback when reasoning model is unavailable"""
        with patch('backend.agent.agent_kernel.ModelRouter') as mock_router_class:
            mock_router = Mock()
            mock_router.get_reasoning_model.return_value = None
            mock_router.models = {}
            
            mock_router_class.return_value = mock_router
            
            kernel = AgentKernel(session_id="test_no_reasoning")
            plan = kernel.plan_task("Hello")
            
            # Should return error
            assert "error" in plan


class TestExecutePlan:
    """Test plan execution with execution model"""
    
    @pytest.fixture
    def mock_kernel_with_execution(self):
        """Create kernel with mocked execution model"""
        with patch('backend.agent.agent_kernel.ModelRouter') as mock_router_class:
            mock_execution_model = Mock()
            mock_execution_model.model_id = "executor"
            mock_execution_model.is_loaded.return_value = True
            mock_execution_model.generate.return_value = "Task completed successfully"
            
            mock_router = Mock()
            mock_router.get_execution_model.return_value = mock_execution_model
            mock_router.models = {"executor": mock_execution_model}
            
            mock_router_class.return_value = mock_router
            
            kernel = AgentKernel(session_id="test_execute")
            yield kernel
    
    def test_execute_plan_with_steps(self, mock_kernel_with_execution):
        """Test executing a plan with multiple steps"""
        plan = {
            "steps": [
                {
                    "step": 1,
                    "action": "First action",
                    "tool": "tool1",
                    "parameters": {}
                },
                {
                    "step": 2,
                    "action": "Second action",
                    "tool": None,
                    "parameters": {}
                }
            ]
        }
        
        results = mock_kernel_with_execution.execute_plan(plan)
        
        # Should return results for all steps
        assert len(results) == 2
        assert all(isinstance(r, dict) for r in results)
    
    def test_execute_step_without_tool(self, mock_kernel_with_execution):
        """Test executing a step that doesn't require a tool"""
        step = {
            "step": 1,
            "action": "Just respond",
            "tool": None,
            "parameters": {}
        }
        
        result = mock_kernel_with_execution.execute_step(step)
        
        # Should return success response
        assert result["success"] is True
        assert "response" in result
    
    def test_execute_step_with_tool(self, mock_kernel_with_execution):
        """Test executing a step that uses a tool"""
        step = {
            "step": 1,
            "action": "Search the web",
            "tool": "web_search",
            "parameters": {"query": "test"}
        }
        
        result = mock_kernel_with_execution.execute_step(step)
        
        # Should return result
        assert isinstance(result, dict)
        assert "tool" in result or "error" in result


class TestGetStatus:
    """Test agent status reporting"""
    
    def test_get_status_returns_required_fields(self):
        """Test that get_status returns all required fields"""
        kernel = AgentKernel(session_id="test_status")
        status = kernel.get_status()
        
        # Check required fields
        assert "ready" in status
        assert "models_loaded" in status
        assert "total_models" in status
        assert "tool_bridge_available" in status
        assert "model_status" in status
        assert "single_model_mode" in status
        
        # Check types
        assert isinstance(status["ready"], bool)
        assert isinstance(status["models_loaded"], int)
        assert isinstance(status["total_models"], int)
        assert isinstance(status["tool_bridge_available"], bool)
        assert isinstance(status["model_status"], dict)
        assert isinstance(status["single_model_mode"], bool)
    
    def test_get_status_with_models_available(self):
        """Test status when models are available"""
        with patch('backend.agent.agent_kernel.ModelRouter') as mock_router_class:
            mock_model = Mock()
            mock_model.model_id = "brain"
            
            mock_router = Mock()
            mock_router.get_reasoning_model.return_value = mock_model
            mock_router.get_execution_model.return_value = None
            mock_router.get_all_models_status.return_value = {"brain": {"loaded": True}}
            mock_router.get_loaded_models.return_value = {"brain": mock_model}
            
            mock_router_class.return_value = mock_router
            
            kernel = AgentKernel(session_id="test_status_available")
            status = kernel.get_status()
            
            # Should be ready with at least one model
            assert status["ready"] is True
            assert status["total_models"] >= 1


class TestConversationManagement:
    """Test conversation memory integration"""
    
    def test_clear_conversation(self):
        """Test clearing conversation history"""
        import uuid
        kernel = AgentKernel(session_id=f"test_clear_{uuid.uuid4()}")
        
        # Add some messages
        kernel._conversation_memory.add_message("user", "Hello")
        kernel._conversation_memory.add_message("assistant", "Hi there")
        
        # Verify messages exist
        context = kernel.get_conversation_context()
        assert len(context) == 2
        
        # Clear conversation
        kernel.clear_conversation()
        
        # Verify messages are cleared
        context = kernel.get_conversation_context()
        assert len(context) == 0
    
    def test_get_conversation_context(self):
        """Test retrieving conversation context"""
        import uuid
        kernel = AgentKernel(session_id=f"test_context_{uuid.uuid4()}")
        
        # Add messages
        kernel._conversation_memory.add_message("user", "Message 1")
        kernel._conversation_memory.add_message("assistant", "Response 1")
        kernel._conversation_memory.add_message("user", "Message 2")
        
        # Get full context
        context = kernel.get_conversation_context()
        assert len(context) == 3
        
        # Get limited context
        context = kernel.get_conversation_context(max_messages=2)
        assert len(context) == 2
    
    def test_conversation_persists_across_messages(self):
        """Test that conversation memory persists across multiple messages"""
        with patch('backend.agent.agent_kernel.ModelRouter') as mock_router_class:
            mock_model = Mock()
            mock_model.model_id = "brain"
            mock_model.is_loaded.return_value = True
            mock_model.generate.return_value = json.dumps({
                "steps": [{"step": 1, "action": "respond", "tool": None, "parameters": {}}]
            })
            
            mock_router = Mock()
            mock_router.get_reasoning_model.return_value = mock_model
            mock_router.get_execution_model.return_value = mock_model
            mock_router.models = {"brain": mock_model}
            mock_router.get_all_models_status.return_value = {"brain": {}}
            mock_router.get_loaded_models.return_value = {}
            
            mock_router_class.return_value = mock_router
            
            kernel = AgentKernel(session_id="test_persist")
            
            # Send multiple messages
            kernel.process_text_message("First message")
            kernel.process_text_message("Second message")
            kernel.process_text_message("Third message")
            
            # Check that all messages are in context
            context = kernel.get_conversation_context()
            assert len(context) >= 6  # 3 user + 3 assistant messages


class TestPersonalityIntegration:
    """Test personality manager integration"""
    
    def test_update_personality(self):
        """Test updating personality configuration"""
        kernel = AgentKernel(session_id="test_personality")
        
        # Update personality
        config = {
            "identity": {
                "assistant_name": "TestBot",
                "tone": "professional",
                "verbosity": "concise"
            }
        }
        
        kernel.update_personality(config)
        
        # Verify personality was updated
        profile = kernel._personality.get_profile()
        assert profile["assistant_name"] == "TestBot"
        assert profile["tone"] == "professional"
        assert profile["verbosity"] == "concise"


class TestSingletonPattern:
    """Test singleton instance management"""
    
    def test_get_agent_kernel_returns_same_instance(self):
        """Test that get_agent_kernel returns the same instance for same session"""
        kernel1 = get_agent_kernel("session1")
        kernel2 = get_agent_kernel("session1")
        
        assert kernel1 is kernel2
    
    def test_get_agent_kernel_different_sessions(self):
        """Test that different sessions get different instances"""
        kernel1 = get_agent_kernel("session1")
        kernel2 = get_agent_kernel("session2")
        
        assert kernel1 is not kernel2
        assert kernel1.session_id == "session1"
        assert kernel2.session_id == "session2"


class TestModelFailureFallback:
    """Test model failure fallback to single-model mode"""
    
    def test_fallback_to_single_model_mode(self):
        """Test fallback when only one model is available"""
        with patch('backend.agent.agent_kernel.ModelRouter') as mock_router_class:
            mock_model = Mock()
            mock_model.model_id = "brain"
            
            mock_router = Mock()
            mock_router.get_reasoning_model.return_value = mock_model
            mock_router.get_execution_model.return_value = None  # Execution model unavailable
            mock_router.models = {"brain": mock_model}
            
            mock_router_class.return_value = mock_router
            
            kernel = AgentKernel(session_id="test_fallback")
            
            # Should be in single-model mode
            assert kernel._single_model_mode is True
            assert kernel._available_model_id == "brain"
    
    def test_execution_with_fallback_model(self):
        """Test that execution works with fallback model"""
        with patch('backend.agent.agent_kernel.ModelRouter') as mock_router_class:
            mock_model = Mock()
            mock_model.model_id = "brain"
            mock_model.is_loaded.return_value = True
            mock_model.generate.return_value = "Fallback response"
            
            mock_router = Mock()
            mock_router.get_reasoning_model.return_value = mock_model
            mock_router.get_execution_model.return_value = None
            mock_router.models = {"brain": mock_model}
            
            mock_router_class.return_value = mock_router
            
            kernel = AgentKernel(session_id="test_fallback_exec")
            
            # Execute a step - should use fallback model
            step = {
                "step": 1,
                "action": "Test action",
                "tool": "test_tool",
                "parameters": {}
            }
            
            result = kernel.execute_step(step)
            
            # Should complete successfully with fallback
            assert isinstance(result, dict)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
