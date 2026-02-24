"""
Diagnostics Manager - Health checks, LFM benchmark, MCP tests
"""
import time
import platform
from typing import Dict, Any, List, Optional
from dataclasses import dataclass


@dataclass
class HealthCheck:
    """Result of a health check"""
    component: str
    status: str  # "healthy", "warning", "error"
    message: str
    latency_ms: float = 0


class DiagnosticsManager:
    """
    Manages system diagnostics:
    - Health checks for all components
    - LFM model benchmark
    - MCP connectivity tests
    - System information
    """
    
    _instance: Optional['DiagnosticsManager'] = None
    _initialized: bool = False
    
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if DiagnosticsManager._initialized:
            return
        
        self._last_health_check: List[HealthCheck] = []
        DiagnosticsManager._initialized = True
    
    async def run_health_checks(self) -> List[HealthCheck]:
        """Run comprehensive health checks"""
        checks = []
        
        # Check Audio Engine
        checks.append(await self._check_audio_engine())
        
        # Check LFM Model
        checks.append(await self._check_lfm_model())
        
        # Check MCP
        checks.append(await self._check_mcp())
        
        # Check System
        checks.append(self._check_system())
        
        self._last_health_check = checks
        return checks
    
    async def _check_audio_engine(self) -> HealthCheck:
        """Check audio engine status"""
        start = time.time()
        try:
            from ..audio import get_audio_engine
            engine = get_audio_engine()
            status = engine.get_status()
            
            latency_ms = (time.time() - start) * 1000
            
            if status.get("is_running"):
                return HealthCheck("audio_engine", "healthy", "Audio engine running", latency_ms)
            else:
                return HealthCheck("audio_engine", "warning", "Audio engine not running", latency_ms)
        except Exception as e:
            return HealthCheck("audio_engine", "error", str(e), (time.time() - start) * 1000)
    
    async def _check_lfm_model(self) -> HealthCheck:
        """Check LFM model status"""
        start = time.time()
        try:
            from ..audio import get_audio_engine
            engine = get_audio_engine()
            
            if engine.model_manager and engine.model_manager.is_loaded:
                return HealthCheck("lfm_model", "healthy", "Model loaded", (time.time() - start) * 1000)
            else:
                return HealthCheck("lfm_model", "warning", "Model not loaded", (time.time() - start) * 1000)
        except Exception as e:
            return HealthCheck("lfm_model", "error", str(e), (time.time() - start) * 1000)
    
    async def _check_mcp(self) -> HealthCheck:
        """Check MCP status"""
        start = time.time()
        try:
            from ..mcp import get_tool_registry
            registry = get_tool_registry()
            tools = registry.get_all_tools()
            
            latency_ms = (time.time() - start) * 1000
            
            if len(tools) > 0:
                return HealthCheck("mcp", "healthy", f"{len(tools)} tools available", latency_ms)
            else:
                return HealthCheck("mcp", "warning", "No tools registered", latency_ms)
        except Exception as e:
            return HealthCheck("mcp", "error", str(e), (time.time() - start) * 1000)
    
    def _check_system(self) -> HealthCheck:
        """Check system resources"""
        try:
            import psutil
            
            cpu_percent = psutil.cpu_percent(interval=0.1)
            memory = psutil.virtual_memory()
            
            status = "healthy"
            message = f"CPU: {cpu_percent}%, Memory: {memory.percent}%"
            
            if cpu_percent > 90 or memory.percent > 90:
                status = "warning"
            
            return HealthCheck("system", status, message)
        except ImportError:
            return HealthCheck("system", "healthy", "System check (psutil not installed)")
        except Exception as e:
            return HealthCheck("system", "error", str(e))
    
    async def benchmark_lfm(self) -> Dict[str, Any]:
        """Run LFM model benchmark"""
        try:
            from ..audio import get_audio_engine
            engine = get_audio_engine()
            
            if not engine.model_manager or not engine.model_manager.is_loaded:
                return {"success": False, "error": "Model not loaded"}
            
            # Generate test audio (1 second of silence)
            import numpy as np
            test_audio = np.zeros(16000, dtype=np.float32)
            
            # Run inference and measure
            start = time.time()
            output_audio, transcript = engine.model_manager.inference(
                audio_input=test_audio,
                mode="conversation",
                max_tokens=256
            )
            inference_time = time.time() - start
            
            return {
                "success": True,
                "inference_time_ms": round(inference_time * 1000, 2),
                "audio_samples": len(test_audio),
                "output_generated": output_audio is not None,
                "transcript": transcript[:100] if transcript else None
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def test_mcp_tools(self) -> Dict[str, Any]:
        """Test MCP tool execution"""
        try:
            from ..mcp import get_tool_registry
            registry = get_tool_registry()
            
            # Get all tools
            tools = registry.get_all_tools()
            
            # Test a simple tool (get_system_info if available)
            test_results = []
            for tool in tools[:5]:  # Test first 5 tools
                try:
                    if tool.get("local"):
                        result = await registry.execute_local_tool(tool["name"], {})
                        test_results.append({
                            "tool": tool["name"],
                            "success": result is not None and not isinstance(result, dict) or not result.get("error")
                        })
                except Exception as e:
                    test_results.append({"tool": tool["name"], "success": False, "error": str(e)})
            
            return {
                "success": True,
                "tools_tested": len(test_results),
                "results": test_results
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def get_system_info(self) -> Dict[str, Any]:
        """Get system information"""
        return {
            "platform": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "python_version": platform.python_version()
        }
    
    def get_health_summary(self) -> Dict[str, Any]:
        """Get summary of last health check"""
        if not self._last_health_check:
            return {"status": "unknown", "checks_run": 0}
        
        statuses = [c.status for c in self._last_health_check]
        
        if any(s == "error" for s in statuses):
            overall = "error"
        elif any(s == "warning" for s in statuses):
            overall = "warning"
        else:
            overall = "healthy"
        
        return {
            "status": overall,
            "checks_run": len(self._last_health_check),
            "components": {c.component: {"status": c.status, "message": c.message} 
                          for c in self._last_health_check}
        }


def get_diagnostics_manager() -> DiagnosticsManager:
    """Get the singleton DiagnosticsManager instance"""
    return DiagnosticsManager()
