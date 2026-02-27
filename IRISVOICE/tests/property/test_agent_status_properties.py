"""
Property-based tests for agent status information.
Tests universal properties that should hold for agent status reporting,
including ready status, model counts, tool bridge availability, and VPS Gateway status.
"""
import pytest
from hypothesis import given, settings, strategies as st, seed
import sys
import os
from unittest.mock import Mock, patch
from datetime import datetime

# Add backend to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from backend.agent.agent_kernel import AgentKernel


# ============================================================================
# Test Data Generators (Hypothesis Strategies)
# ============================================================================

@st.composite
def session_id_generator(draw):
    """Generate valid session IDs."""
    return draw(st.one_of(
        st.text(min_size=1, max_size=50, alphabet=st.characters(
            whitelist_categories=('Lu', 'Ll', 'Nd'),
            whitelist_characters='-_'
        )),
        st.uuids().map(str)
    ))


@st.composite
def model_status_generator(draw):
    """Generate model status configurations."""
    num_models = draw(st.integers(min_value=0, max_value=3))
    models = {}
    
    for i in range(num_models):
        model_name = draw(st.sampled_from([
            "reasoning", "execution", "lfm2-8b", "lfm2.5-1.2b-instruct"
        ]))
        models[model_name] = {
            "loaded": draw(st.booleans()),
            "available": draw(st.booleans()),
            "model_id": model_name
        }
    
    return models


@st.composite
def tool_bridge_status_generator(draw):
    """Generate tool bridge status."""
    return {
        "available": draw(st.booleans()),
        "tools_count": draw(st.integers(min_value=0, max_value=50))
    }


@st.composite
def vps_gateway_status_generator(draw):
    """Generate VPS Gateway status."""
    enabled = draw(st.booleans())
    
    if not enabled:
        return {
            "enabled": False,
            "available_endpoints": 0
        }
    
    num_endpoints = draw(st.integers(min_value=0, max_value=5))
    available_endpoints = draw(st.integers(min_value=0, max_value=num_endpoints))
    
    return {
        "enabled": True,
        "protocol": draw(st.sampled_from(["rest", "websocket"])),
        "load_balancing": draw(st.booleans()),
        "endpoints": num_endpoints,
        "available_endpoints": available_endpoints,
        "health_status": {}
    }


@st.composite
def initialization_error_generator(draw):
    """Generate initialization errors."""
    has_error = draw(st.booleans())
    if has_error:
        return draw(st.sampled_from([
            "Failed to load models",
            "Model initialization timeout",
            "Insufficient memory",
            "Configuration error",
            None
        ]))
    return None


# ============================================================================
# Property 46: Agent Status Information
# Feature: irisvoice-backend-integration, Property 46: Agent Status Information
# Validates: Requirements 18.1-18.7
# ============================================================================

class TestAgentStatusInformation:
    """
    Property 46: Agent Status Information
    
    For any agent_status request, the backend returns a message containing:
    - ready status (bool)
    - models_loaded count (int)
    - total_models count (int)
    - tool_bridge_available status (bool)
    - individual model status (dict)
    - single_model_mode flag (bool)
    - error field (None or string)
    - vps_gateway status (dict)
    
    This tests:
    - Requirement 18.1: Agent status request handling
    - Requirement 18.2: Ready status reporting
    - Requirement 18.3: Models loaded count
    - Requirement 18.4: Total models count
    - Requirement 18.5: Tool bridge availability status
    - Requirement 18.6: Individual model status included
    - Requirement 18.7: Status information completeness
    """
    
    @settings(max_examples=20, deadline=None)
    @seed(42)  # Fixed seed for reproducibility
    @given(
        session_id=session_id_generator(),
        model_status=model_status_generator(),
        tool_bridge_status=tool_bridge_status_generator(),
        vps_status=vps_gateway_status_generator(),
        init_error=initialization_error_generator()
    )
    def test_status_contains_all_required_fields(
        self, session_id, model_status, tool_bridge_status, vps_status, init_error
    ):
        """
        Property: For any agent status request, all required fields are present.
        
        # Feature: irisvoice-backend-integration, Property 46: Agent Status Information
        **Validates: Requirements 18.1, 18.7**
        """
        # Setup: Create kernel with mocked components
        with patch('backend.agent.agent_kernel.ModelRouter') as mock_router_class, \
             patch('backend.agent.agent_kernel.VPSGateway') as mock_vps_class:
            
            # Setup mock model router
            mock_router = Mock()
            mock_router.get_all_models_status.return_value = model_status
            
            loaded_models = [name for name, status in model_status.items() 
                           if status.get("loaded", False)]
            mock_router.get_loaded_models.return_value = loaded_models
            
            # Setup reasoning and execution models
            reasoning_available = any(
                name in ["reasoning", "lfm2-8b"] and status.get("available", False)
                for name, status in model_status.items()
            )
            execution_available = any(
                name in ["execution", "lfm2.5-1.2b-instruct"] and status.get("available", False)
                for name, status in model_status.items()
            )
            
            mock_router.get_reasoning_model.return_value = Mock() if reasoning_available else None
            mock_router.get_execution_model.return_value = Mock() if execution_available else None
            mock_router_class.return_value = mock_router
            
            # Setup mock VPS Gateway
            mock_vps = Mock()
            mock_vps.get_status.return_value = vps_status
            mock_vps_class.return_value = mock_vps
            
            # Create kernel
            kernel = AgentKernel(session_id=session_id)
            kernel._initialization_error = init_error
            
            # Setup tool bridge mock
            if tool_bridge_status["available"]:
                kernel._tool_bridge = Mock()
                kernel._tool_bridge.get_status.return_value = tool_bridge_status
            else:
                kernel._tool_bridge = None
            
            # Execute: Get status
            status = kernel.get_status()
            
            # Verify: All required fields are present
            assert "ready" in status, "Status must include 'ready' field"
            assert "models_loaded" in status, "Status must include 'models_loaded' field"
            assert "total_models" in status, "Status must include 'total_models' field"
            assert "tool_bridge_available" in status, "Status must include 'tool_bridge_available' field"
            assert "model_status" in status, "Status must include 'model_status' field"
            assert "single_model_mode" in status, "Status must include 'single_model_mode' field"
            assert "error" in status, "Status must include 'error' field"
            assert "vps_gateway" in status, "Status must include 'vps_gateway' field"
    
    @settings(max_examples=20, deadline=None)
    @seed(42)
    @given(
        session_id=session_id_generator(),
        model_status=model_status_generator(),
        tool_bridge_status=tool_bridge_status_generator(),
        vps_status=vps_gateway_status_generator()
    )
    def test_status_fields_have_correct_types(
        self, session_id, model_status, tool_bridge_status, vps_status
    ):
        """
        Property: For any agent status, all fields have correct types.
        
        # Feature: irisvoice-backend-integration, Property 46: Agent Status Information
        **Validates: Requirements 18.1, 18.7**
        """
        # Setup: Create kernel with mocked components
        with patch('backend.agent.agent_kernel.ModelRouter') as mock_router_class, \
             patch('backend.agent.agent_kernel.VPSGateway') as mock_vps_class:
            
            mock_router = Mock()
            mock_router.get_all_models_status.return_value = model_status
            loaded_models = [name for name, status in model_status.items() 
                           if status.get("loaded", False)]
            mock_router.get_loaded_models.return_value = loaded_models
            mock_router.get_reasoning_model.return_value = Mock() if model_status else None
            mock_router.get_execution_model.return_value = None
            mock_router_class.return_value = mock_router
            
            mock_vps = Mock()
            mock_vps.get_status.return_value = vps_status
            mock_vps_class.return_value = mock_vps
            
            kernel = AgentKernel(session_id=session_id)
            
            if tool_bridge_status["available"]:
                kernel._tool_bridge = Mock()
                kernel._tool_bridge.get_status.return_value = tool_bridge_status
            
            # Execute: Get status
            status = kernel.get_status()
            
            # Verify: Field types are correct
            assert isinstance(status["ready"], bool), "ready must be a boolean"
            assert isinstance(status["models_loaded"], int), "models_loaded must be an integer"
            assert isinstance(status["total_models"], int), "total_models must be an integer"
            assert isinstance(status["tool_bridge_available"], bool), "tool_bridge_available must be a boolean"
            assert isinstance(status["model_status"], dict), "model_status must be a dictionary"
            assert isinstance(status["single_model_mode"], bool), "single_model_mode must be a boolean"
            assert status["error"] is None or isinstance(status["error"], str), \
                "error must be None or a string"
            assert isinstance(status["vps_gateway"], dict), "vps_gateway must be a dictionary"
    
    @settings(max_examples=20, deadline=None)
    @seed(42)
    @given(
        session_id=session_id_generator(),
        model_status=model_status_generator()
    )
    def test_models_loaded_count_is_accurate(self, session_id, model_status):
        """
        Property: For any agent status, models_loaded count matches actual loaded models.
        
        # Feature: irisvoice-backend-integration, Property 46: Agent Status Information
        **Validates: Requirements 18.3**
        """
        # Setup: Create kernel with mocked components
        with patch('backend.agent.agent_kernel.ModelRouter') as mock_router_class, \
             patch('backend.agent.agent_kernel.VPSGateway') as mock_vps_class:
            
            mock_router = Mock()
            mock_router.get_all_models_status.return_value = model_status
            
            # Calculate expected loaded models
            loaded_models = [name for name, status in model_status.items() 
                           if status.get("loaded", False)]
            mock_router.get_loaded_models.return_value = loaded_models
            mock_router.get_reasoning_model.return_value = Mock() if loaded_models else None
            mock_router.get_execution_model.return_value = None
            mock_router_class.return_value = mock_router
            
            mock_vps = Mock()
            mock_vps.get_status.return_value = {"enabled": False, "available_endpoints": 0}
            mock_vps_class.return_value = mock_vps
            
            kernel = AgentKernel(session_id=session_id)
            
            # Execute: Get status
            status = kernel.get_status()
            
            # Verify: models_loaded count is accurate
            expected_count = len(loaded_models)
            assert status["models_loaded"] == expected_count, \
                f"models_loaded should be {expected_count}, got {status['models_loaded']}"
    
    @settings(max_examples=20, deadline=None)
    @seed(42)
    @given(
        session_id=session_id_generator(),
        model_status=model_status_generator()
    )
    def test_total_models_count_is_accurate(self, session_id, model_status):
        """
        Property: For any agent status, total_models count matches total models.
        
        # Feature: irisvoice-backend-integration, Property 46: Agent Status Information
        **Validates: Requirements 18.4**
        """
        # Setup: Create kernel with mocked components
        with patch('backend.agent.agent_kernel.ModelRouter') as mock_router_class, \
             patch('backend.agent.agent_kernel.VPSGateway') as mock_vps_class:
            
            mock_router = Mock()
            mock_router.get_all_models_status.return_value = model_status
            mock_router.get_loaded_models.return_value = []
            mock_router.get_reasoning_model.return_value = None
            mock_router.get_execution_model.return_value = None
            mock_router_class.return_value = mock_router
            
            mock_vps = Mock()
            mock_vps.get_status.return_value = {"enabled": False, "available_endpoints": 0}
            mock_vps_class.return_value = mock_vps
            
            kernel = AgentKernel(session_id=session_id)
            
            # Execute: Get status
            status = kernel.get_status()
            
            # Verify: total_models count is accurate
            expected_count = len(model_status)
            assert status["total_models"] == expected_count, \
                f"total_models should be {expected_count}, got {status['total_models']}"
    
    @settings(max_examples=20, deadline=None)
    @seed(42)
    @given(
        session_id=session_id_generator(),
        model_status=model_status_generator()
    )
    def test_ready_status_reflects_model_availability(self, session_id, model_status):
        """
        Property: For any agent status, ready is true if at least one model is available.
        
        # Feature: irisvoice-backend-integration, Property 46: Agent Status Information
        **Validates: Requirements 18.2**
        """
        # Setup: Create kernel with mocked components
        with patch('backend.agent.agent_kernel.ModelRouter') as mock_router_class, \
             patch('backend.agent.agent_kernel.VPSGateway') as mock_vps_class:
            
            mock_router = Mock()
            mock_router.get_all_models_status.return_value = model_status
            mock_router.get_loaded_models.return_value = []
            
            # Determine if any model is available
            reasoning_available = any(
                name in ["reasoning", "lfm2-8b"] and status.get("available", False)
                for name, status in model_status.items()
            )
            execution_available = any(
                name in ["execution", "lfm2.5-1.2b-instruct"] and status.get("available", False)
                for name, status in model_status.items()
            )
            
            mock_router.get_reasoning_model.return_value = Mock() if reasoning_available else None
            mock_router.get_execution_model.return_value = Mock() if execution_available else None
            mock_router_class.return_value = mock_router
            
            mock_vps = Mock()
            mock_vps.get_status.return_value = {"enabled": False, "available_endpoints": 0}
            mock_vps_class.return_value = mock_vps
            
            kernel = AgentKernel(session_id=session_id)
            
            # Execute: Get status
            status = kernel.get_status()
            
            # Verify: ready status reflects model availability
            expected_ready = reasoning_available or execution_available
            assert status["ready"] == expected_ready, \
                f"ready should be {expected_ready} (reasoning: {reasoning_available}, execution: {execution_available})"
    
    @settings(max_examples=20, deadline=None)
    @seed(42)
    @given(
        session_id=session_id_generator(),
        tool_bridge_status=tool_bridge_status_generator()
    )
    def test_tool_bridge_availability_is_reported(self, session_id, tool_bridge_status):
        """
        Property: For any agent status, tool_bridge_available reflects actual availability.
        
        # Feature: irisvoice-backend-integration, Property 46: Agent Status Information
        **Validates: Requirements 18.5**
        """
        # Setup: Create kernel with mocked components
        with patch('backend.agent.agent_kernel.ModelRouter') as mock_router_class, \
             patch('backend.agent.agent_kernel.VPSGateway') as mock_vps_class:
            
            mock_router = Mock()
            mock_router.get_all_models_status.return_value = {}
            mock_router.get_loaded_models.return_value = []
            mock_router.get_reasoning_model.return_value = None
            mock_router.get_execution_model.return_value = None
            mock_router_class.return_value = mock_router
            
            mock_vps = Mock()
            mock_vps.get_status.return_value = {"enabled": False, "available_endpoints": 0}
            mock_vps_class.return_value = mock_vps
            
            kernel = AgentKernel(session_id=session_id)
            
            # Setup tool bridge based on status
            if tool_bridge_status["available"]:
                kernel._tool_bridge = Mock()
                kernel._tool_bridge.get_status.return_value = tool_bridge_status
            else:
                kernel._tool_bridge = None
            
            # Execute: Get status
            status = kernel.get_status()
            
            # Verify: tool_bridge_available reflects actual availability
            expected_available = tool_bridge_status["available"]
            assert status["tool_bridge_available"] == expected_available, \
                f"tool_bridge_available should be {expected_available}"
    
    @settings(max_examples=20, deadline=None)
    @seed(42)
    @given(
        session_id=session_id_generator(),
        model_status=model_status_generator()
    )
    def test_individual_model_status_is_included(self, session_id, model_status):
        """
        Property: For any agent status, individual model status is included.
        
        # Feature: irisvoice-backend-integration, Property 46: Agent Status Information
        **Validates: Requirements 18.6**
        """
        # Setup: Create kernel with mocked components
        with patch('backend.agent.agent_kernel.ModelRouter') as mock_router_class, \
             patch('backend.agent.agent_kernel.VPSGateway') as mock_vps_class:
            
            mock_router = Mock()
            mock_router.get_all_models_status.return_value = model_status
            mock_router.get_loaded_models.return_value = []
            mock_router.get_reasoning_model.return_value = None
            mock_router.get_execution_model.return_value = None
            mock_router_class.return_value = mock_router
            
            mock_vps = Mock()
            mock_vps.get_status.return_value = {"enabled": False, "available_endpoints": 0}
            mock_vps_class.return_value = mock_vps
            
            kernel = AgentKernel(session_id=session_id)
            
            # Execute: Get status
            status = kernel.get_status()
            
            # Verify: Individual model status is included
            assert isinstance(status["model_status"], dict), \
                "model_status must be a dictionary"
            assert status["model_status"] == model_status, \
                "model_status should match the router's model status"
    
    @settings(max_examples=20, deadline=None)
    @seed(42)
    @given(
        session_id=session_id_generator(),
        vps_status=vps_gateway_status_generator()
    )
    def test_vps_gateway_status_is_included(self, session_id, vps_status):
        """
        Property: For any agent status, VPS Gateway status is included.
        
        # Feature: irisvoice-backend-integration, Property 46: Agent Status Information
        **Validates: Requirements 18.7**
        """
        # Setup: Create kernel with mocked components
        with patch('backend.agent.agent_kernel.ModelRouter') as mock_router_class, \
             patch('backend.agent.agent_kernel.VPSGateway') as mock_vps_class:
            
            mock_router = Mock()
            mock_router.get_all_models_status.return_value = {}
            mock_router.get_loaded_models.return_value = []
            mock_router.get_reasoning_model.return_value = None
            mock_router.get_execution_model.return_value = None
            mock_router_class.return_value = mock_router
            
            mock_vps = Mock()
            mock_vps.get_status.return_value = vps_status
            mock_vps_class.return_value = mock_vps
            
            kernel = AgentKernel(session_id=session_id)
            
            # Execute: Get status
            status = kernel.get_status()
            
            # Verify: VPS Gateway status is included
            assert "vps_gateway" in status, "Status must include vps_gateway"
            assert isinstance(status["vps_gateway"], dict), \
                "vps_gateway must be a dictionary"
            assert status["vps_gateway"] == vps_status, \
                "vps_gateway should match the gateway's status"
    
    @settings(max_examples=20, deadline=None)
    @seed(42)
    @given(
        session_id=session_id_generator(),
        init_error=initialization_error_generator()
    )
    def test_initialization_errors_are_reported(self, session_id, init_error):
        """
        Property: For any agent status, initialization errors are reported.
        
        # Feature: irisvoice-backend-integration, Property 46: Agent Status Information
        **Validates: Requirements 18.7**
        """
        # Setup: Create kernel with mocked components
        with patch('backend.agent.agent_kernel.ModelRouter') as mock_router_class, \
             patch('backend.agent.agent_kernel.VPSGateway') as mock_vps_class:
            
            mock_router = Mock()
            mock_router.get_all_models_status.return_value = {}
            mock_router.get_loaded_models.return_value = []
            mock_router.get_reasoning_model.return_value = None
            mock_router.get_execution_model.return_value = None
            mock_router_class.return_value = mock_router
            
            mock_vps = Mock()
            mock_vps.get_status.return_value = {"enabled": False, "available_endpoints": 0}
            mock_vps_class.return_value = mock_vps
            
            kernel = AgentKernel(session_id=session_id)
            kernel._initialization_error = init_error
            
            # Execute: Get status
            status = kernel.get_status()
            
            # Verify: Initialization error is reported
            assert status["error"] == init_error, \
                f"error should be {init_error}, got {status['error']}"
    
    @settings(max_examples=20, deadline=None)
    @seed(42)
    @given(
        session_id=session_id_generator(),
        model_status=model_status_generator()
    )
    def test_single_model_mode_flag_is_reported(self, session_id, model_status):
        """
        Property: For any agent status, single_model_mode flag is reported.
        
        # Feature: irisvoice-backend-integration, Property 46: Agent Status Information
        **Validates: Requirements 18.7**
        """
        # Setup: Create kernel with mocked components
        with patch('backend.agent.agent_kernel.ModelRouter') as mock_router_class, \
             patch('backend.agent.agent_kernel.VPSGateway') as mock_vps_class:
            
            mock_router = Mock()
            mock_router.get_all_models_status.return_value = model_status
            mock_router.get_loaded_models.return_value = []
            mock_router.get_reasoning_model.return_value = None
            mock_router.get_execution_model.return_value = None
            mock_router_class.return_value = mock_router
            
            mock_vps = Mock()
            mock_vps.get_status.return_value = {"enabled": False, "available_endpoints": 0}
            mock_vps_class.return_value = mock_vps
            
            kernel = AgentKernel(session_id=session_id)
            
            # Execute: Get status
            status = kernel.get_status()
            
            # Verify: single_model_mode flag is present and is a boolean
            assert "single_model_mode" in status, \
                "Status must include single_model_mode flag"
            assert isinstance(status["single_model_mode"], bool), \
                "single_model_mode must be a boolean"
    
    @settings(max_examples=20, deadline=None)
    @seed(42)
    @given(
        session_id=session_id_generator(),
        model_status=model_status_generator(),
        tool_bridge_status=tool_bridge_status_generator(),
        vps_status=vps_gateway_status_generator(),
        init_error=initialization_error_generator()
    )
    def test_status_is_always_a_dict(
        self, session_id, model_status, tool_bridge_status, vps_status, init_error
    ):
        """
        Property: For any agent status request, the result is always a dictionary.
        
        # Feature: irisvoice-backend-integration, Property 46: Agent Status Information
        **Validates: Requirements 18.1**
        """
        # Setup: Create kernel with mocked components
        with patch('backend.agent.agent_kernel.ModelRouter') as mock_router_class, \
             patch('backend.agent.agent_kernel.VPSGateway') as mock_vps_class:
            
            mock_router = Mock()
            mock_router.get_all_models_status.return_value = model_status
            loaded_models = [name for name, status in model_status.items() 
                           if status.get("loaded", False)]
            mock_router.get_loaded_models.return_value = loaded_models
            mock_router.get_reasoning_model.return_value = Mock() if model_status else None
            mock_router.get_execution_model.return_value = None
            mock_router_class.return_value = mock_router
            
            mock_vps = Mock()
            mock_vps.get_status.return_value = vps_status
            mock_vps_class.return_value = mock_vps
            
            kernel = AgentKernel(session_id=session_id)
            kernel._initialization_error = init_error
            
            if tool_bridge_status["available"]:
                kernel._tool_bridge = Mock()
                kernel._tool_bridge.get_status.return_value = tool_bridge_status
            
            # Execute: Get status
            status = kernel.get_status()
            
            # Verify: Status is always a dictionary
            assert isinstance(status, dict), \
                "get_status() must always return a dictionary"
