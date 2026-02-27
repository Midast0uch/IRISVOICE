#!/usr/bin/env python3
"""
VPS Gateway

This module provides a gateway for routing model inference to remote VPS servers
or falling back to local execution. It supports both REST API and WebSocket
communication protocols with automatic health monitoring and fallback.

Key Features:
- Remote model inference offloading to VPS
- Automatic fallback to local execution when VPS unavailable
- Health monitoring with periodic checks
- Load balancing across multiple VPS endpoints
- Request/response serialization and deserialization
- Authentication header injection
- Timeout handling with configurable duration
"""

import asyncio
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any
from enum import Enum

import httpx
from pydantic import BaseModel, Field

from backend.core.logging_config import get_component_logger
from .model_router import ModelRouter

logger = get_component_logger("vps_gateway")


class VPSProtocol(str, Enum):
    """Communication protocol for VPS."""
    REST = "rest"
    WEBSOCKET = "websocket"


class LoadBalancingStrategy(str, Enum):
    """Load balancing strategy for multiple VPS endpoints."""
    ROUND_ROBIN = "round_robin"
    LEAST_LOADED = "least_loaded"


class LoadBalancingStrategy(str, Enum):
    """Load balancing strategy for multiple VPS endpoints."""
    ROUND_ROBIN = "round_robin"
    LEAST_LOADED = "least_loaded"



class VPSConfig(BaseModel):
    """Configuration for VPS Gateway.
    
    Attributes:
        enabled: Whether VPS routing is enabled
        endpoints: List of VPS endpoint URLs (e.g., ["https://vps1.example.com:8000"])
        auth_token: Bearer token for authentication
        timeout: Request timeout in seconds (default 30)
        health_check_interval: Health check interval in seconds (default 60)
        fallback_to_local: Fall back to local execution when VPS unavailable (default True)
        load_balancing: Enable load balancing across multiple endpoints (default False)
        load_balancing_strategy: Strategy for load balancing - "round_robin" or "least_loaded" (default "round_robin")
        protocol: Communication protocol - "rest" or "websocket" (default "rest")
        offload_tools: Offload tool execution to VPS in addition to model inference (default False)
    """
    enabled: bool = False
    endpoints: List[str] = Field(default_factory=list)
    auth_token: Optional[str] = None
    timeout: int = 30
    health_check_interval: int = 60
    fallback_to_local: bool = True
    load_balancing: bool = False
    load_balancing_strategy: LoadBalancingStrategy = LoadBalancingStrategy.ROUND_ROBIN
    protocol: VPSProtocol = VPSProtocol.REST
    offload_tools: bool = False


class VPSHealthStatus(BaseModel):
    """Health status for a VPS endpoint.
    
    Attributes:
        endpoint: VPS endpoint URL
        available: Whether the endpoint is currently available
        last_check: Timestamp of last health check
        last_success: Timestamp of last successful health check
        consecutive_failures: Number of consecutive health check failures
        latency_ms: Last measured latency in milliseconds
        active_requests: Number of currently active requests to this endpoint
        error_message: Last error message if unavailable
    """
    endpoint: str
    available: bool = False
    last_check: datetime = Field(default_factory=datetime.now)
    last_success: Optional[datetime] = None
    consecutive_failures: int = 0
    latency_ms: Optional[float] = None
    active_requests: int = 0
    error_message: Optional[str] = None


class VPSInferenceRequest(BaseModel):
    """Request payload for VPS inference.
    
    Attributes:
        model: Model identifier ("lfm2-8b" or "lfm2.5-1.2b-instruct")
        prompt: Input prompt for the model
        context: Conversation history, personality, and other context
        parameters: Model parameters (temperature, max_tokens, etc.)
        session_id: Session identifier for tracking
        tool_calls: Optional tool execution requests
    """
    model: str
    prompt: str
    context: Dict[str, Any] = Field(default_factory=dict)
    parameters: Dict[str, Any] = Field(default_factory=dict)
    session_id: str
    tool_calls: Optional[List[Dict[str, Any]]] = None


class VPSInferenceResponse(BaseModel):
    """Response payload from VPS inference.
    
    Attributes:
        text: Generated text from the model
        model: Model used for inference
        latency_ms: Inference latency in milliseconds
        tool_calls: Tool calls requested by the model
        tool_results: Tool execution results (if offload_tools enabled)
        metadata: Additional metadata (tokens, finish_reason, etc.)
    """
    text: str
    model: str
    latency_ms: float
    tool_calls: Optional[List[Dict[str, Any]]] = None
    tool_results: Optional[List[Dict[str, Any]]] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class VPSGateway:
    """Gateway for routing model inference to remote VPS or local execution.
    
    The VPS Gateway enables offloading heavy model inference to remote servers
    while maintaining automatic fallback to local execution when VPS is unavailable.
    
    Features:
    - Remote inference routing with authentication
    - Automatic health monitoring and fallback
    - Load balancing across multiple endpoints
    - Request/response serialization
    - Timeout handling
    - Comprehensive logging
    
    Example:
        >>> config = VPSConfig(
        ...     enabled=True,
        ...     endpoints=["https://vps.example.com:8000"],
        ...     auth_token="secret-token",
        ...     timeout=30
        ... )
        >>> gateway = VPSGateway(config, model_router)
        >>> await gateway.initialize()
        >>> response = await gateway.infer(
        ...     model="lfm2-8b",
        ...     prompt="Hello, world!",
        ...     context={},
        ...     params={}
        ... )
    """
    
    def __init__(self, config: VPSConfig, model_router: ModelRouter):
        """Initialize VPS Gateway.
        
        Args:
            config: VPS configuration
            model_router: ModelRouter instance for local fallback
        """
        self._config = config
        self._model_router = model_router
        self._http_client: Optional[httpx.AsyncClient] = None
        self._health_status: Dict[str, VPSHealthStatus] = {}
        self._health_check_task: Optional[asyncio.Task] = None
        self._endpoint_index = 0  # For round-robin load balancing
        
        logger.info(
            "VPS Gateway initialized",
            enabled=config.enabled,
            endpoints=config.endpoints,
            protocol=config.protocol,
            load_balancing=config.load_balancing
        )
    
    async def initialize(self) -> None:
        """Initialize the VPS Gateway.
        
        Sets up HTTP client, initializes health status for all endpoints,
        and starts the health check background task.
        """
        if not self._config.enabled:
            logger.info("VPS Gateway disabled, skipping initialization")
            return
        
        # Initialize HTTP client
        self._http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(self._config.timeout),
            follow_redirects=True
        )
        
        # Initialize health status for all endpoints
        for endpoint in self._config.endpoints:
            self._health_status[endpoint] = VPSHealthStatus(endpoint=endpoint)
        
        # Perform initial health check
        await self._check_all_endpoints_health()
        
        # Start health check background task
        if self._config.health_check_interval > 0:
            self._health_check_task = asyncio.create_task(self._health_check_loop())
        
        logger.info(
            "VPS Gateway initialized successfully",
            endpoints=len(self._config.endpoints),
            available_endpoints=sum(1 for s in self._health_status.values() if s.available)
        )
    
    async def shutdown(self) -> None:
        """Shutdown the VPS Gateway.
        
        Cancels health check task and closes HTTP client.
        """
        logger.info("Shutting down VPS Gateway")
        
        # Cancel health check task
        if self._health_check_task:
            self._health_check_task.cancel()
            try:
                await self._health_check_task
            except asyncio.CancelledError:
                pass
        
        # Close HTTP client
        if self._http_client:
            await self._http_client.aclose()
        
        logger.info("VPS Gateway shutdown complete")
    
    async def infer(
        self,
        model: str,
        prompt: str,
        context: Dict[str, Any],
        params: Dict[str, Any],
        session_id: str = "default"
    ) -> str:
        """Route inference request to VPS or local execution.
        
        Args:
            model: Model identifier ("lfm2-8b" or "lfm2.5-1.2b-instruct")
            prompt: Input prompt for the model
            context: Conversation history and context
            params: Model parameters (temperature, max_tokens, etc.)
            session_id: Session identifier
        
        Returns:
            Generated text from the model
        
        Raises:
            RuntimeError: If both VPS and local execution fail
        """
        # Check if VPS is enabled and available
        if self._config.enabled and self.is_vps_available():
            endpoint = await self._select_endpoint()
            if endpoint:
                try:
                    logger.debug(
                        "Routing inference to VPS",
                        model=model,
                        endpoint=endpoint,
                        session_id=session_id
                    )
                    return await self.infer_remote(endpoint, model, prompt, context, params, session_id)
                except Exception as e:
                    logger.error(
                        "VPS inference failed, falling back to local",
                        error=str(e),
                        endpoint=endpoint,
                        model=model
                    )
                    # Mark endpoint as unavailable (only if not already updated by infer_remote)
                    if endpoint in self._health_status:
                        # Only update if the endpoint is still marked as available
                        # (infer_remote already updated it on timeout/error)
                        if self._health_status[endpoint].available:
                            self._health_status[endpoint].available = False
                            self._health_status[endpoint].consecutive_failures += 1
                            self._health_status[endpoint].error_message = str(e)
                    
                    # Fall through to local execution if fallback enabled
                    if not self._config.fallback_to_local:
                        raise
        
        # Fall back to local execution
        logger.debug(
            "Using local inference",
            model=model,
            vps_enabled=self._config.enabled,
            vps_available=self.is_vps_available(),
            session_id=session_id
        )
        return await self.infer_local(model, prompt, context, params)
    
    async def infer_remote(
        self,
        endpoint: str,
        model: str,
        prompt: str,
        context: Dict[str, Any],
        params: Dict[str, Any],
        session_id: str = "default"
    ) -> str:
        """Execute inference on remote VPS.
        
        Args:
            endpoint: VPS endpoint URL
            model: Model identifier
            prompt: Input prompt
            context: Context dictionary
            params: Model parameters
            session_id: Session identifier
        
        Returns:
            Generated text from the model
        
        Raises:
            httpx.TimeoutException: If request times out
            httpx.HTTPError: If HTTP request fails
            ValueError: If response is invalid
        """
        if not self._http_client:
            raise RuntimeError("VPS Gateway not initialized")
        
        # Increment active requests counter
        if endpoint in self._health_status:
            self._health_status[endpoint].active_requests += 1
        
        try:
            # Create inference request
            request = VPSInferenceRequest(
                model=model,
                prompt=prompt,
                context=context,
                parameters=params,
                session_id=session_id
            )
            
            # Prepare headers with authentication
            headers = {}
            if self._config.auth_token:
                headers["Authorization"] = f"Bearer {self._config.auth_token}"
            headers["Content-Type"] = "application/json"
            
            # Send request based on protocol
            if self._config.protocol == VPSProtocol.REST:
                start_time = datetime.now()
                
                try:
                    response = await self._http_client.post(
                        f"{endpoint}/api/v1/infer",
                        json=request.dict(),
                        headers=headers
                    )
                    response.raise_for_status()
                    
                    # Parse response
                    response_data = response.json()
                    inference_response = VPSInferenceResponse(**response_data)
                    
                    # Update health status
                    latency_ms = (datetime.now() - start_time).total_seconds() * 1000
                    if endpoint in self._health_status:
                        self._health_status[endpoint].available = True
                        self._health_status[endpoint].last_success = datetime.now()
                        self._health_status[endpoint].consecutive_failures = 0
                        self._health_status[endpoint].latency_ms = latency_ms
                        self._health_status[endpoint].error_message = None
                    
                    logger.info(
                        "VPS inference successful",
                        endpoint=endpoint,
                        model=model,
                        latency_ms=latency_ms,
                        session_id=session_id
                    )
                    
                    return inference_response.text
                
                except httpx.TimeoutException as e:
                    # Update health status on timeout
                    if endpoint in self._health_status:
                        self._health_status[endpoint].available = False
                        self._health_status[endpoint].consecutive_failures += 1
                        self._health_status[endpoint].error_message = f"Timeout after {self._config.timeout}s"
                    
                    logger.error(
                        "VPS inference timeout - falling back to local execution",
                        endpoint=endpoint,
                        model=model,
                        timeout=self._config.timeout,
                        session_id=session_id,
                        consecutive_failures=self._health_status[endpoint].consecutive_failures if endpoint in self._health_status else 0
                    )
                    raise
                
                except httpx.HTTPError as e:
                    # Update health status on HTTP error
                    if endpoint in self._health_status:
                        self._health_status[endpoint].available = False
                        self._health_status[endpoint].consecutive_failures += 1
                        self._health_status[endpoint].error_message = str(e)
                    
                    logger.error(
                        "VPS HTTP error - falling back to local execution",
                        endpoint=endpoint,
                        model=model,
                        error=str(e),
                        status_code=getattr(e.response, 'status_code', None) if hasattr(e, 'response') else None,
                        session_id=session_id,
                        consecutive_failures=self._health_status[endpoint].consecutive_failures if endpoint in self._health_status else 0
                    )
                    raise
            
            else:  # WebSocket protocol
                # WebSocket implementation would go here
                # For now, raise NotImplementedError
                raise NotImplementedError("WebSocket protocol not yet implemented")
        
        finally:
            # Decrement active requests counter
            if endpoint in self._health_status:
                self._health_status[endpoint].active_requests = max(
                    0, self._health_status[endpoint].active_requests - 1
                )
    
    async def infer_local(
        self,
        model: str,
        prompt: str,
        context: Dict[str, Any],
        params: Dict[str, Any]
    ) -> str:
        """Execute inference using local ModelRouter.
        
        Args:
            model: Model identifier
            prompt: Input prompt
            context: Context dictionary (may contain conversation_history)
            params: Model parameters
        
        Returns:
            Generated text from the model
        
        Raises:
            RuntimeError: If local model is not available
        """
        # Get the appropriate model from ModelRouter
        if "lfm2-8b" in model.lower() or "reasoning" in context.get("task_type", ""):
            model_wrapper = self._model_router.get_reasoning_model()
        elif "lfm2.5-1.2b" in model.lower() or "execution" in context.get("task_type", ""):
            model_wrapper = self._model_router.get_execution_model()
        else:
            # Default routing based on message
            model_id = self._model_router.route_message(prompt, context)
            model_wrapper = self._model_router.models.get(model_id)
        
        if not model_wrapper:
            raise RuntimeError(f"Local model not available: {model}")
        
        # Generate response using local model
        logger.debug(
            "Executing local inference",
            model=model_wrapper.model_id,
            prompt_length=len(prompt)
        )
        
        # Extract conversation history from context if available
        conversation_history = context.get("conversation_history", None)
        
        # Prepare generation kwargs from params
        gen_kwargs = {
            "max_new_tokens": params.get("max_tokens", 512),
            "temperature": params.get("temperature", 0.7),
            "top_p": params.get("top_p", 0.9),
            "do_sample": params.get("do_sample", True),
        }
        
        # Use the model wrapper's generate method
        response = model_wrapper.generate(
            prompt=prompt,
            conversation_history=conversation_history,
            **gen_kwargs
        )
        
        return response
    
    async def check_vps_health(self, endpoint: str) -> bool:
        """Check health of a specific VPS endpoint.
        
        Args:
            endpoint: VPS endpoint URL
        
        Returns:
            True if endpoint is healthy, False otherwise
        """
        if not self._http_client:
            return False
        
        try:
            # Prepare headers with authentication
            headers = {}
            if self._config.auth_token:
                headers["Authorization"] = f"Bearer {self._config.auth_token}"
            
            start_time = datetime.now()
            
            # Send health check request
            response = await self._http_client.get(
                f"{endpoint}/api/v1/health",
                headers=headers,
                timeout=5.0  # Short timeout for health checks
            )
            response.raise_for_status()
            
            # Calculate latency
            latency_ms = (datetime.now() - start_time).total_seconds() * 1000
            
            # Update health status
            if endpoint in self._health_status:
                self._health_status[endpoint].available = True
                self._health_status[endpoint].last_check = datetime.now()
                self._health_status[endpoint].last_success = datetime.now()
                self._health_status[endpoint].consecutive_failures = 0
                self._health_status[endpoint].latency_ms = latency_ms
                self._health_status[endpoint].error_message = None
            
            logger.debug(
                "VPS health check passed",
                endpoint=endpoint,
                latency_ms=latency_ms
            )
            
            return True
        
        except Exception as e:
            # Update health status
            if endpoint in self._health_status:
                self._health_status[endpoint].available = False
                self._health_status[endpoint].last_check = datetime.now()
                self._health_status[endpoint].consecutive_failures += 1
                self._health_status[endpoint].error_message = str(e)
            
            logger.warning(
                "VPS health check failed",
                endpoint=endpoint,
                error=str(e),
                consecutive_failures=self._health_status[endpoint].consecutive_failures if endpoint in self._health_status else 0
            )
            
            return False
    
    async def _check_all_endpoints_health(self) -> None:
        """Check health of all configured endpoints."""
        if not self._config.endpoints:
            return
        
        tasks = [self.check_vps_health(endpoint) for endpoint in self._config.endpoints]
        await asyncio.gather(*tasks, return_exceptions=True)
    
    async def _health_check_loop(self) -> None:
        """Background task for periodic health checks."""
        logger.info(
            "Starting VPS health check loop",
            interval=self._config.health_check_interval
        )
        
        while True:
            try:
                await asyncio.sleep(self._config.health_check_interval)
                await self._check_all_endpoints_health()
            except asyncio.CancelledError:
                logger.info("VPS health check loop cancelled")
                break
            except Exception as e:
                logger.error(
                    "Error in VPS health check loop",
                    error=str(e)
                )
    
    async def _select_endpoint(self) -> Optional[str]:
        """Select an available VPS endpoint based on configured strategy.
        
        Supports two strategies:
        - round_robin: Cycle through available endpoints in order
        - least_loaded: Select endpoint with lowest latency or fewest active requests
        
        Returns:
            Selected endpoint URL, or None if no endpoints available
        """
        available_endpoints = [
            endpoint for endpoint, status in self._health_status.items()
            if status.available
        ]
        
        if not available_endpoints:
            logger.warning("No available VPS endpoints")
            return None
        
        # Single endpoint - no need for load balancing
        if len(available_endpoints) == 1:
            return available_endpoints[0]
        
        # Load balancing disabled - return first available
        if not self._config.load_balancing:
            return available_endpoints[0]
        
        # Apply load balancing strategy
        if self._config.load_balancing_strategy == LoadBalancingStrategy.ROUND_ROBIN:
            # Round-robin: cycle through endpoints
            endpoint = available_endpoints[self._endpoint_index % len(available_endpoints)]
            self._endpoint_index += 1
            logger.debug(
                "Selected endpoint using round-robin",
                endpoint=endpoint,
                index=self._endpoint_index - 1
            )
            return endpoint
        
        elif self._config.load_balancing_strategy == LoadBalancingStrategy.LEAST_LOADED:
            # Least-loaded: select endpoint with lowest load
            # Load is calculated as: active_requests + (latency_ms / 1000)
            # This balances both request count and endpoint performance
            
            def calculate_load(endpoint: str) -> float:
                status = self._health_status[endpoint]
                # Base load from active requests
                load = float(status.active_requests)
                # Add latency component (convert ms to seconds for weighting)
                if status.latency_ms is not None:
                    load += status.latency_ms / 1000.0
                else:
                    # If no latency data, assume moderate latency (500ms)
                    load += 0.5
                return load
            
            # Find endpoint with minimum load
            selected_endpoint = min(available_endpoints, key=calculate_load)
            selected_load = calculate_load(selected_endpoint)
            
            logger.debug(
                "Selected endpoint using least-loaded",
                endpoint=selected_endpoint,
                load=selected_load,
                active_requests=self._health_status[selected_endpoint].active_requests,
                latency_ms=self._health_status[selected_endpoint].latency_ms
            )
            return selected_endpoint
        
        else:
            # Unknown strategy - fall back to first available
            logger.warning(
                "Unknown load balancing strategy, using first available",
                strategy=self._config.load_balancing_strategy
            )
            return available_endpoints[0]
    
    def is_vps_available(self) -> bool:
        """Check if at least one VPS endpoint is available.
        
        Returns:
            True if at least one endpoint is available, False otherwise
        """
        return any(status.available for status in self._health_status.values())
    
    def get_status(self) -> Dict[str, Any]:
        """Get current VPS Gateway status.
        
        Returns:
            Dictionary containing gateway status information
        """
        return {
            "enabled": self._config.enabled,
            "protocol": self._config.protocol,
            "load_balancing": self._config.load_balancing,
            "load_balancing_strategy": self._config.load_balancing_strategy if self._config.load_balancing else None,
            "endpoints": len(self._config.endpoints),
            "available_endpoints": sum(1 for s in self._health_status.values() if s.available),
            "health_status": {
                endpoint: {
                    "available": status.available,
                    "last_check": status.last_check.isoformat() if status.last_check else None,
                    "last_success": status.last_success.isoformat() if status.last_success else None,
                    "consecutive_failures": status.consecutive_failures,
                    "latency_ms": status.latency_ms,
                    "active_requests": status.active_requests,
                    "error_message": status.error_message
                }
                for endpoint, status in self._health_status.items()
            }
        }
