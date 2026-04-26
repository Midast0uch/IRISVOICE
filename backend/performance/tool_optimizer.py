"""
Tool Execution Optimizer
Ensures tool execution within 10 seconds with parallel execution support.
"""
import asyncio
import logging
import time
from typing import Dict, List, Any, Optional, Callable, Awaitable
from collections import deque
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class ToolStatus(Enum):
    """Tool execution status."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"


@dataclass
class ToolMetrics:
    """Track tool execution metrics."""
    samples: deque = field(default_factory=lambda: deque(maxlen=1000))
    timeouts: int = 0
    failures: int = 0
    successes: int = 0
    
    def record_success(self, execution_time_s: float):
        """Record a successful execution."""
        self.samples.append(execution_time_s)
        self.successes += 1
    
    def record_timeout(self):
        """Record a timeout."""
        self.timeouts += 1
    
    def record_failure(self):
        """Record a failure."""
        self.failures += 1
    
    def get_p95(self) -> float:
        """Get 95th percentile execution time."""
        if not self.samples:
            return 0.0
        sorted_samples = sorted(self.samples)
        idx = int(len(sorted_samples) * 0.95)
        return sorted_samples[idx]
    
    def get_mean(self) -> float:
        """Get mean execution time."""
        if not self.samples:
            return 0.0
        return sum(self.samples) / len(self.samples)
    
    def get_max(self) -> float:
        """Get maximum execution time."""
        if not self.samples:
            return 0.0
        return max(self.samples)
    
    def get_success_rate(self) -> float:
        """Get success rate."""
        total = self.successes + self.failures + self.timeouts
        return self.successes / total if total > 0 else 0.0


@dataclass
class ToolExecution:
    """Represents a tool execution."""
    tool_name: str
    params: Dict[str, Any]
    status: ToolStatus = ToolStatus.PENDING
    result: Optional[Any] = None
    error: Optional[str] = None
    start_time: float = field(default_factory=time.time)
    end_time: Optional[float] = None
    
    def duration(self) -> float:
        """Get execution duration in seconds."""
        if self.end_time:
            return self.end_time - self.start_time
        return time.time() - self.start_time


class ToolOptimizer:
    """
    Optimizes tool execution with parallel execution and timeout handling.
    
    Features:
    - Parallel tool execution where possible
    - Timeout handling (10s default)
    - Execution time monitoring
    - Retry logic for transient failures
    """
    
    # Configuration
    DEFAULT_TIMEOUT_S = 10.0  # Default timeout for tool execution
    MAX_PARALLEL_TOOLS = 5  # Maximum parallel tool executions
    MAX_RETRIES = 2  # Maximum retries for failed tools
    
    def __init__(self):
        self.tool_metrics: Dict[str, ToolMetrics] = {}
        self._semaphore = asyncio.Semaphore(self.MAX_PARALLEL_TOOLS)
    
    def _get_metrics(self, tool_name: str) -> ToolMetrics:
        """Get or create metrics for a tool."""
        if tool_name not in self.tool_metrics:
            self.tool_metrics[tool_name] = ToolMetrics()
        return self.tool_metrics[tool_name]
    
    async def execute_tool(
        self,
        tool_name: str,
        params: Dict[str, Any],
        execution_callback: Callable[[str, Dict[str, Any]], Awaitable[Any]],
        timeout: Optional[float] = None
    ) -> ToolExecution:
        """
        Execute a single tool with timeout and retry.
        
        Args:
            tool_name: Name of the tool
            params: Tool parameters
            execution_callback: Async function to execute the tool
            timeout: Optional timeout override
        
        Returns:
            ToolExecution result
        """
        timeout = timeout or self.DEFAULT_TIMEOUT_S
        metrics = self._get_metrics(tool_name)
        execution = ToolExecution(tool_name=tool_name, params=params)
        
        async with self._semaphore:
            execution.status = ToolStatus.RUNNING
            
            for attempt in range(self.MAX_RETRIES + 1):
                try:
                    # Execute with timeout
                    result = await asyncio.wait_for(
                        execution_callback(tool_name, params),
                        timeout=timeout
                    )
                    
                    # Success
                    execution.status = ToolStatus.COMPLETED
                    execution.result = result
                    execution.end_time = time.time()
                    
                    metrics.record_success(execution.duration())
                    
                    logger.debug(
                        f"Tool {tool_name} completed in {execution.duration():.2f}s"
                    )
                    
                    return execution
                
                except asyncio.TimeoutError:
                    execution.status = ToolStatus.TIMEOUT
                    execution.error = f"Tool execution timed out after {timeout}s"
                    execution.end_time = time.time()
                    
                    metrics.record_timeout()
                    
                    logger.warning(
                        f"Tool {tool_name} timed out after {timeout}s (attempt {attempt + 1}/{self.MAX_RETRIES + 1})"
                    )
                    
                    # Don't retry on timeout
                    return execution
                
                except Exception as e:
                    execution.error = str(e)
                    
                    if attempt < self.MAX_RETRIES:
                        logger.warning(
                            f"Tool {tool_name} failed (attempt {attempt + 1}/{self.MAX_RETRIES + 1}): {e}"
                        )
                        await asyncio.sleep(0.5 * (attempt + 1))  # Exponential backoff
                        continue
                    else:
                        execution.status = ToolStatus.FAILED
                        execution.end_time = time.time()
                        
                        metrics.record_failure()
                        
                        logger.error(
                            f"Tool {tool_name} failed after {self.MAX_RETRIES + 1} attempts: {e}",
                            exc_info=True
                        )
                        
                        return execution
        
        return execution
    
    async def execute_tools_parallel(
        self,
        tools: List[Dict[str, Any]],
        execution_callback: Callable[[str, Dict[str, Any]], Awaitable[Any]],
        timeout: Optional[float] = None
    ) -> List[ToolExecution]:
        """
        Execute multiple tools in parallel.
        
        Args:
            tools: List of tool specifications [{"name": "tool1", "params": {...}}, ...]
            execution_callback: Async function to execute each tool
            timeout: Optional timeout override
        
        Returns:
            List of ToolExecution results
        """
        tasks = []
        for tool in tools:
            task = self.execute_tool(
                tool["name"],
                tool.get("params", {}),
                execution_callback,
                timeout
            )
            tasks.append(task)
        
        # Execute all tools in parallel
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Convert exceptions to failed executions
        executions = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                execution = ToolExecution(
                    tool_name=tools[i]["name"],
                    params=tools[i].get("params", {}),
                    status=ToolStatus.FAILED,
                    error=str(result),
                    end_time=time.time()
                )
                executions.append(execution)
            else:
                executions.append(result)
        
        return executions
    
    def get_metrics(self, tool_name: Optional[str] = None) -> Dict[str, Any]:
        """Get performance metrics for a tool or all tools."""
        if tool_name:
            metrics = self._get_metrics(tool_name)
            return {
                "tool_name": tool_name,
                "p95_execution_time_s": metrics.get_p95(),
                "mean_execution_time_s": metrics.get_mean(),
                "max_execution_time_s": metrics.get_max(),
                "success_rate": metrics.get_success_rate(),
                "successes": metrics.successes,
                "failures": metrics.failures,
                "timeouts": metrics.timeouts,
                "total_samples": len(metrics.samples),
            }
        else:
            return {
                tool: self.get_metrics(tool)
                for tool in self.tool_metrics.keys()
            }
    
    def is_meeting_target(self, tool_name: Optional[str] = None) -> bool:
        """Check if we're meeting the execution time target."""
        if tool_name:
            metrics = self._get_metrics(tool_name)
            p95 = metrics.get_p95()
            return p95 <= self.DEFAULT_TIMEOUT_S if p95 > 0 else True
        else:
            # Check all tools
            return all(
                self.is_meeting_target(tool)
                for tool in self.tool_metrics.keys()
            )


# Global instance
_optimizer: Optional[ToolOptimizer] = None


def get_tool_optimizer() -> ToolOptimizer:
    """Get or create the singleton ToolOptimizer."""
    global _optimizer
    if _optimizer is None:
        _optimizer = ToolOptimizer()
    return _optimizer
