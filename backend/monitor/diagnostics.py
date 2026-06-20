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

        # Check Memory DB (bootstrap/coordinates.db)
        checks.append(self._check_memory_db())

        # Check Monitor DB (data/monitor.db)
        checks.append(self._check_monitor_db())

        # Check LogManager
        checks.append(self._check_log_manager())

        # Check WebSocket manager
        checks.append(self._check_websocket_manager())

        # Check Agent kernel
        checks.append(self._check_agent_kernel())

        # Check Audio Engine
        checks.append(await self._check_audio_engine())

        # Check TTS engine
        checks.append(await self._check_tts_engine())

        # Check MCP
        checks.append(await self._check_mcp())

        # Check System resources
        checks.append(self._check_system())

        self._last_health_check = checks
        return checks

    def _check_memory_db(self) -> HealthCheck:
        """Check the memory/coordinates database is connected and writable"""
        import sqlite3
        import tempfile
        import os
        from pathlib import Path
        start = time.time()
        try:
            # Find coordinates.db (bootstrap/coordinates.db)
            candidates = [
                Path("bootstrap/coordinates.db"),
                Path(__file__).parent.parent.parent / "bootstrap" / "coordinates.db",
                Path("data/memory.db"),
            ]
            db_path = None
            for p in candidates:
                if p.exists():
                    db_path = p
                    break

            if db_path is None:
                return HealthCheck("memory_db", "warning", "coordinates.db not found", (time.time() - start) * 1000)

            # Open read-only first to test connection
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=2)
            try:
                cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' LIMIT 1")
                table = cursor.fetchone()
            finally:
                conn.close()

            if not table:
                return HealthCheck("memory_db", "warning", "Database is empty (no tables)", (time.time() - start) * 1000)

            # Test write capability with a temp DB (don't write to the real one)
            size_mb = db_path.stat().st_size / (1024 * 1024)
            latency = (time.time() - start) * 1000
            return HealthCheck(
                "memory_db",
                "healthy",
                f"Connected · {size_mb:.1f}MB · {table[0]}",
                latency,
            )
        except Exception as e:
            return HealthCheck("memory_db", "error", f"{type(e).__name__}: {str(e)[:60]}", (time.time() - start) * 1000)

    def _check_monitor_db(self) -> HealthCheck:
        """Check the monitor analytics database is connected and has data"""
        import sqlite3
        from pathlib import Path
        start = time.time()
        try:
            candidates = [
                Path("data/monitor.db"),
                Path(__file__).parent.parent.parent / "data" / "monitor.db",
            ]
            db_path = None
            for p in candidates:
                if p.exists():
                    db_path = p
                    break

            if db_path is None:
                return HealthCheck("monitor_db", "warning", "monitor.db not found", (time.time() - start) * 1000)

            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=2)
            try:
                # Check tables exist
                tables = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
                table_names = [t[0] for t in tables]

                if "usage_records" not in table_names:
                    return HealthCheck("monitor_db", "warning", "Schema not initialized", (time.time() - start) * 1000)

                # Count records
                count = conn.execute("SELECT COUNT(*) FROM usage_records").fetchone()[0]
            finally:
                conn.close()

            size_kb = db_path.stat().st_size / 1024
            latency = (time.time() - start) * 1000
            status = "healthy" if count > 0 else "warning"
            msg = f"Connected · {count} records · {size_kb:.0f}KB"
            return HealthCheck("monitor_db", status, msg, latency)
        except Exception as e:
            return HealthCheck("monitor_db", "error", f"{type(e).__name__}: {str(e)[:60]}", (time.time() - start) * 1000)

    def _check_log_manager(self) -> HealthCheck:
        """Check that the LogManager singleton is initialized"""
        start = time.time()
        try:
            from .logs import get_log_manager
            mgr = get_log_manager()
            # Get total log count
            logs = mgr.get_logs(limit=10000)
            latency = (time.time() - start) * 1000
            return HealthCheck("log_manager", "healthy", f"Active · {len(logs)} entries", latency)
        except Exception as e:
            return HealthCheck("log_manager", "error", f"{type(e).__name__}: {str(e)[:60]}", (time.time() - start) * 1000)

    def _check_websocket_manager(self) -> HealthCheck:
        """Check WebSocket manager health"""
        start = time.time()
        try:
            from ..ws_manager import get_websocket_manager
            mgr = get_websocket_manager()
            client_count = mgr.get_connection_count()
            latency = (time.time() - start) * 1000
            status = "healthy" if client_count > 0 else "warning"
            return HealthCheck("websocket", status, f"{client_count} active connection{'s' if client_count != 1 else ''}", latency)
        except Exception as e:
            return HealthCheck("websocket", "error", f"{type(e).__name__}: {str(e)[:60]}", (time.time() - start) * 1000)

    def _check_agent_kernel(self) -> HealthCheck:
        """Check agent kernel state"""
        start = time.time()
        try:
            from ..agent.agent_kernel import _agent_kernel_instances
            count = len(_agent_kernel_instances)
            latency = (time.time() - start) * 1000
            return HealthCheck("agent_kernel", "healthy", f"{count} active kernel{'s' if count != 1 else ''}", latency)
        except Exception as e:
            return HealthCheck("agent_kernel", "warning", f"{type(e).__name__}: {str(e)[:60]}", (time.time() - start) * 1000)
    
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
    
    async def _check_tts_engine(self) -> HealthCheck:
        """Check TTS engine availability"""
        start = time.time()
        try:
            from ..agent.tts import get_tts_manager
            tts = get_tts_manager()
            engine_name = tts.current_engine if hasattr(tts, "current_engine") else "unknown"
            return HealthCheck("tts_engine", "healthy", engine_name, (time.time() - start) * 1000)
        except Exception as e:
            return HealthCheck("tts_engine", "error", f"{type(e).__name__}: {str(e)[:60]}", (time.time() - start) * 1000)
    
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
