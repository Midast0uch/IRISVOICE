"""
IRIS FastAPI Backend Server
Main application entry point with WebSocket endpoint
"""
import json
import os
import uuid
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from backend.models import (
    Category, 
    IRISState, 
    ColorTheme, 
    get_subnodes_for_category,
    SUBNODE_CONFIGS
)
from backend.state_manager import get_state_manager
from backend.ws_manager import get_websocket_manager
from backend.audio import get_audio_engine, VoiceState
from backend.agent import (
    get_personality_engine,
    get_tts_manager,
    get_conversation_memory,
    get_wake_config
)
from backend.mcp import (
    get_server_manager,
    get_tool_registry,
    ServerConfig,
    BrowserServer,
    AppLauncherServer,
    SystemServer,
    FileManagerServer,
    GUIAutomationServer
)
from backend.system import (
    get_power_manager,
    get_display_manager,
    get_storage_manager,
    get_network_manager
)
from backend.customize import (
    get_startup_manager,
    get_behavior_manager,
    get_notification_manager
)
from backend.monitor import (
    get_analytics_manager,
    get_log_manager,
    get_diagnostics_manager,
    get_update_manager
)


# ============================================================================
# Voice Configuration Helper
# ============================================================================

def apply_voice_config(category: str, field_id: str, value: any):
    """
    Apply voice field updates to the AudioEngine.
    Called when voice category fields are updated.
    """
    if category != "voice":
        return
    
    audio_engine = get_audio_engine()
    if not audio_engine:
        return
    
    # Map field IDs to AudioEngine config
    config_updates = {}
    
    # INPUT fields
    if field_id == "input_device":
        config_updates["input_device"] = value if value != "Default" else None
    elif field_id == "input_sensitivity":
        config_updates["input_sensitivity"] = float(value) / 50.0
    elif field_id == "vad":
        config_updates["vad_enabled"] = bool(value)
    
    # OUTPUT fields
    elif field_id == "output_device":
        config_updates["output_device"] = value if value != "Default" else None
    elif field_id == "master_volume":
        config_updates["master_volume"] = float(value) / 100.0
    elif field_id == "latency_compensation":
        config_updates["latency_compensation"] = int(value)
    
    # PROCESSING fields
    elif field_id == "noise_reduction":
        config_updates["noise_reduction"] = bool(value)
    elif field_id == "echo_cancellation":
        config_updates["echo_cancellation"] = bool(value)
    elif field_id == "voice_enhancement":
        config_updates["voice_enhancement"] = bool(value)
    elif field_id == "automatic_gain":
        config_updates["automatic_gain"] = bool(value)
    
    # MODEL fields
    elif field_id == "temperature":
        config_updates["temperature"] = float(value)
    elif field_id == "max_tokens":
        config_updates["max_tokens"] = int(value)
    elif field_id == "context_window":
        config_updates["context_window"] = int(value)
    elif field_id == "endpoint":
        config_updates["model_endpoint"] = str(value)
    
    if config_updates:
        print(f"[VoiceConfig] Updating audio engine: {config_updates}")
        audio_engine.update_config(**config_updates)


# ============================================================================
# Agent Configuration Helper
# ============================================================================

def apply_agent_config(category: str, field_id: str, value: any):
    """
    Apply agent field updates to agent subsystems.
    Called when agent category fields are updated.
    """
    if category != "agent":
        return
    
    print(f"[AgentConfig] Updating {field_id} = {value}")
    
    # IDENTITY fields -> Personality Engine
    if field_id in ["assistant_name", "personality", "knowledge", "response_length"]:
        personality = get_personality_engine()
        # Map field names
        key_map = {
            "assistant_name": "assistant_name",
            "personality": "personality",
            "knowledge": "knowledge_focus",
            "response_length": "response_length"
        }
        if field_id in key_map:
            personality.update_profile(**{key_map[field_id]: value})
    
    # WAKE fields -> Wake Config
    elif field_id in ["wake_phrase", "detection_sensitivity", "activation_sound", "sleep_timeout"]:
        wake_config = get_wake_config()
        # Map field names
        key_map = {
            "wake_phrase": "wake_phrase",
            "detection_sensitivity": "detection_sensitivity",
            "activation_sound": "activation_sound",
            "sleep_timeout": "sleep_timeout"
        }
        if field_id in key_map:
            wake_config.update_config(**{key_map[field_id]: value})
    
    # SPEECH fields -> TTS Manager
    elif field_id in ["tts_voice", "speaking_rate", "pitch_adjustment", "pause_duration"]:
        tts = get_tts_manager()
        # Map field names
        key_map = {
            "tts_voice": "tts_voice",
            "speaking_rate": "speaking_rate",
            "pitch_adjustment": "pitch_adjustment",
            "pause_duration": "pause_duration"
        }
        if field_id in key_map:
            tts.update_config(**{key_map[field_id]: value})
    
    # MEMORY fields -> Conversation Memory
    elif field_id == "context_window":
        memory = get_conversation_memory()
        memory.max_context_tokens = int(value)


# ============================================================================
# Lifespan - Startup/Shutdown
# ============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan - load state on startup, save on shutdown"""
    # Startup
    print(">> IRIS Backend starting up...")
    state_manager = get_state_manager()
    await state_manager.load_all()
    print(f"[OK] Loaded state with theme: {state_manager.state.active_theme.glow}")
    
    # Initialize audio engine with saved voice config
    voice_config = state_manager.get_category_field_values("voice")
    if voice_config:
        print("[OK] Initializing audio engine with saved voice config...")
        audio_engine = get_audio_engine()
        # ... voice config mapping ...
        config_map = {
            "input_device": voice_config.get("input_device"),
            "input_sensitivity": voice_config.get("input_sensitivity", 50) / 50.0 if isinstance(voice_config.get("input_sensitivity"), (int, float)) else 1.0,
            "vad_enabled": voice_config.get("vad", True),
            "output_device": voice_config.get("output_device"),
            "master_volume": voice_config.get("master_volume", 70) / 100.0 if isinstance(voice_config.get("master_volume"), (int, float)) else 0.7,
            "latency_compensation": voice_config.get("latency_compensation", 0),
            "noise_reduction": voice_config.get("noise_reduction", True),
            "echo_cancellation": voice_config.get("echo_cancellation", True),
            "voice_enhancement": voice_config.get("voice_enhancement", False),
            "automatic_gain": voice_config.get("automatic_gain", True),
            "temperature": voice_config.get("temperature", 0.7),
            "max_tokens": voice_config.get("max_tokens", 2048),
            "context_window": voice_config.get("context_window", 8192),
            "model_endpoint": voice_config.get("endpoint", "http://localhost:1234"),
        }
        filtered_config = {k: v for k, v in config_map.items() if v is not None}
        audio_engine.update_config(**filtered_config)
        print(f"[OK] Audio engine configured")
        
        # Register WebSocket callbacks for wake word and listening state
        ws_manager = get_websocket_manager()
        
        def on_wake_detected(phrase: str, confidence: float):
            """Broadcast wake detection to all clients"""
            asyncio.create_task(ws_manager.broadcast({
                "type": "wake_detected",
                "phrase": phrase,
                "confidence": confidence
            }))
        
        def on_state_change(new_state: VoiceState):
            """Broadcast listening state changes to all clients"""
            asyncio.create_task(ws_manager.broadcast({
                "type": "listening_state",
                "state": new_state.value
            }))
        
        audio_engine.on_wake_detected(on_wake_detected)
        audio_engine.on_state_change(on_state_change)
        print("[OK] Audio engine WebSocket callbacks registered")
    
    # Initialize agent components with saved config
    agent_config = state_manager.get_category_field_values("agent")
    if agent_config:
        print("[OK] Initializing agent components...")
        
        # Personality
        personality = get_personality_engine()
        if any(k in agent_config for k in ["assistant_name", "personality", "knowledge", "response_length"]):
            personality.update_profile(
                assistant_name=agent_config.get("assistant_name", "IRIS"),
                personality=agent_config.get("personality", "Friendly"),
                knowledge_focus=agent_config.get("knowledge", "General"),
                response_length=agent_config.get("response_length", "Balanced")
            )
            print(f"[OK] Personality configured: {personality.get_profile()}")
        
        # Wake config
        wake = get_wake_config()
        if any(k in agent_config for k in ["wake_phrase", "detection_sensitivity", "activation_sound", "sleep_timeout"]):
            wake.update_config(
                wake_phrase=agent_config.get("wake_phrase", "Hey IRIS"),
                detection_sensitivity=float(agent_config.get("detection_sensitivity", 70)) / 100.0 if isinstance(agent_config.get("detection_sensitivity"), (int, float)) else 0.7,
                activation_sound=agent_config.get("activation_sound", True),
                sleep_timeout=agent_config.get("sleep_timeout", 60)
            )
            print(f"[OK] Wake config configured")
        
        # TTS
        tts = get_tts_manager()
        if any(k in agent_config for k in ["tts_voice", "speaking_rate", "pitch_adjustment", "pause_duration"]):
            tts.update_config(
                tts_voice=agent_config.get("tts_voice", "Nova"),
                speaking_rate=float(agent_config.get("speaking_rate", 1.0)) if isinstance(agent_config.get("speaking_rate"), (int, float)) else 1.0,
                pitch_adjustment=agent_config.get("pitch_adjustment", 0),
                pause_duration=float(agent_config.get("pause_duration", 0.2)) if isinstance(agent_config.get("pause_duration"), (int, float)) else 0.2
            )
            print(f"[OK] TTS configured: {tts.get_config()}")
        
        # Memory
        memory = get_conversation_memory()
        if "context_window" in agent_config:
            memory.max_context_tokens = int(agent_config["context_window"])
            print(f"[OK] Memory context window: {memory.max_context_tokens}")
    
    # Initialize MCP (Model Context Protocol) servers
    print("[OK] Initializing MCP servers...")
    server_manager = get_server_manager()
    tool_registry = get_tool_registry()
    
    # Register built-in MCP servers
    builtin_servers = [
        ("browser", BrowserServer()),
        ("app_launcher", AppLauncherServer()),
        ("system", SystemServer()),
        ("file_manager", FileManagerServer()),
    ]
    
    for name, server in builtin_servers:
        # Register tools from built-in server
        for tool in server.get_tools():
            tool_registry.register_local_tool(
                name=tool.name,
                func=lambda args, s=server, t=tool.name: asyncio.run(s.execute_tool(t, args)),
                description=tool.description
            )
        print(f"[OK] Registered built-in MCP server: {name} ({len(server.get_tools())} tools)")
    
    # Register GUI Automation server (UI-TARS integration)
    print("[OK] Initializing GUI Automation server...")
    
    # Load GUI automation config from state manager
    automate_config = state_manager.get_category_field_values("automate")
    gui_config = {
        "ui_tars_provider": "native_python",
        "model_provider": "anthropic",
        "api_key": "",
        "max_steps": 25,
        "safety_confirmation": True,
        "debug_mode": True
    }
    if automate_config:
        # Map automate config fields to gui config
        gui_config["ui_tars_provider"] = automate_config.get("ui_tars_provider", "native_python")
        gui_config["model_provider"] = automate_config.get("model_provider", "anthropic")
        gui_config["api_key"] = automate_config.get("api_key", "")
        gui_config["max_steps"] = automate_config.get("max_steps", 25)
        gui_config["safety_confirmation"] = automate_config.get("safety_confirmation", True)
        gui_config["debug_mode"] = automate_config.get("debug_mode", True)
    
    gui_automation = GUIAutomationServer(
        use_native=gui_config["ui_tars_provider"] in ["native_python", "api_cloud"],
        use_vision=gui_config["model_provider"] in ["anthropic", "volcengine", "local"] and bool(gui_config["api_key"]),
        vision_provider=gui_config["model_provider"],
        vision_api_key=gui_config["api_key"],
        max_steps=gui_config["max_steps"],
        safety_confirmation=gui_config["safety_confirmation"],
        debug_mode=gui_config["debug_mode"]
    )
    
    for tool in gui_automation.get_tools():
        tool_registry.register_local_tool(
            name=tool.name,
            func=lambda args, s=gui_automation, t=tool.name: asyncio.run(s.execute_tool(t, args)),
            description=tool.description
        )
    print(f"[OK] Registered GUI Automation server ({len(gui_automation.get_tools())} tools)")
    
    # Register external MCP servers from config (if any)
    automate_config = state_manager.get_category_field_values("automate")
    if automate_config:
        # Could load external server configs here
        pass
    
    print(f"[OK] MCP initialized with {len(tool_registry.get_all_tools())} total tools")
    
    # Send backend_ready signal to all connected clients
    ws_manager = get_websocket_manager()
    await ws_manager.broadcast({
        "type": "backend_ready",
        "timestamp": datetime.now().isoformat()
    })
    print("[OK] Backend ready signal sent")
    
    yield
    
    # Shutdown
    print("\n[STOP] IRIS Backend shutting down...")
    
    # Stop audio engine
    audio_engine = get_audio_engine()
    if audio_engine:
        audio_engine.stop()
        print("[OK] Audio engine stopped")
    
    # Save all categories
    for category in SUBNODE_CONFIGS.keys():
        await state_manager.save_category(category)
    await state_manager.save_theme()
    print("[OK] State saved")


# ============================================================================
# FastAPI App
# ============================================================================

app = FastAPI(
    title="IRIS Backend",
    description="FastAPI backend for IRIS Desktop Widget",
    version="1.0.0",
    lifespan=lifespan
)

# CORS - allow frontend to connect
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, restrict to your frontend URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================================
# HTTP Routes
# ============================================================================

@app.get("/")
async def root():
    """Health check endpoint"""
    return {
        "status": "online",
        "service": "IRIS Backend",
        "version": "1.0.0"
    }


@app.get("/api/state")
async def get_state():
    """Get current application state (for initial load or refresh)"""
    state_manager = get_state_manager()
    return {
        "status": "success",
        "state": state_manager.state.model_dump()
    }


@app.get("/api/subnodes/{category}")
async def get_subnodes(category: str):
    """Get subnode configuration for a category"""
    subnodes = get_subnodes_for_category(category)
    if not subnodes:
        return {"status": "error", "message": f"Unknown category: {category}"}
    
    # Convert to dict for JSON response
    return {
        "status": "success",
        "category": category,
        "subnodes": [s.model_dump() for s in subnodes]
    }


# ============================================================================
# Voice API Endpoints
# ============================================================================

@app.get("/api/voice/devices")
async def get_audio_devices():
    """Get list of available audio input/output devices"""
    try:
        from backend.audio.pipeline import AudioPipeline
        devices = AudioPipeline.list_devices()
        
        input_devices = [d for d in devices if d["input"]]
        output_devices = [d for d in devices if d["output"]]
        
        return {
            "status": "success",
            "input_devices": input_devices,
            "output_devices": output_devices
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/api/voice/test/input")
async def test_input_device():
    """Test the currently configured input device"""
    try:
        audio_engine = get_audio_engine()
        if not audio_engine:
            return {"status": "error", "message": "Audio engine not available"}
        
        # TODO: Implement actual input test (record 3 seconds, analyze)
        return {
            "status": "success",
            "message": "Input device test started",
            "device": audio_engine.config.get("input_device", "Default")
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/api/voice/test/output")
async def test_output_device():
    """Test the currently configured output device with a tone"""
    try:
        audio_engine = get_audio_engine()
        if not audio_engine or not audio_engine.pipeline:
            return {"status": "error", "message": "Audio engine not available"}
        
        # Generate test tone (1kHz sine wave, 1 second)
        import numpy as np
        sample_rate = 16000
        duration = 1.0
        t = np.linspace(0, duration, int(sample_rate * duration))
        tone = np.sin(2 * np.pi * 1000 * t) * 0.3  # 1kHz at 30% volume
        
        # Play tone
        audio_engine.pipeline.play_audio(tone)
        
        return {
            "status": "success",
            "message": "Output device test tone played",
            "device": audio_engine.config.get("output_device", "Default")
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/api/voice/test/connection")
async def test_model_connection():
    """Test connection to LFM 2.5 Audio model"""
    try:
        audio_engine = get_audio_engine()
        if not audio_engine or not audio_engine.model_manager:
            return {"status": "error", "message": "Model manager not available"}
        
        # Check if model is downloaded/loaded
        info = audio_engine.model_manager.get_info()
        
        if not info["downloaded"]:
            return {
                "status": "not_downloaded",
                "message": "Model not downloaded",
                "info": info
            }
        
        if not info["loaded"]:
            # Try to load
            loaded = audio_engine.model_manager.load_model()
            if not loaded:
                return {
                    "status": "error",
                    "message": "Failed to load model",
                    "info": info
                }
        
        return {
            "status": "success",
            "message": "Model connection successful",
            "info": audio_engine.model_manager.get_info()
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/api/voice/model/download")
async def download_model():
    """Start LFM 2.5 Audio model download"""
    try:
        audio_engine = get_audio_engine()
        if not audio_engine or not audio_engine.model_manager:
            return {"status": "error", "message": "Model manager not available"}
        
        # Check if already downloaded
        info = audio_engine.model_manager.get_info()
        if info["downloaded"]:
            return {
                "status": "already_downloaded",
                "message": "Model already downloaded",
                "info": info
            }
        
        # Start download in background
        import asyncio
        
        async def download_with_progress():
            def progress(p):
                print(f"[Model Download] Progress: {p:.1f}%")
            
            success = await audio_engine.model_manager.download_model(
                progress_callback=progress
            )
            return success
        
        # Start download task
        asyncio.create_task(download_with_progress())
        
        return {
            "status": "started",
            "message": "Model download started",
            "info": info
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/api/voice/status")
async def get_voice_status():
    """Get current voice/audio engine status and LFM models"""
    try:
        audio_engine = get_audio_engine()
        
        # LFM Models list with download status
        lfm_models = [
            {
                "id": "lfm-2.5-audio",
                "name": "LFM 2.5 Audio",
                "description": "Lightweight speech model for voice interaction",
                "size_mb": 150,
                "downloaded": audio_engine.model_manager.get_info().get("downloaded", False) if audio_engine and audio_engine.model_manager else False,
                "loaded": audio_engine.model_manager.get_info().get("loaded", False) if audio_engine and audio_engine.model_manager else False,
                "progress": 0,  # Download progress (0-100)
            }
        ]
        
        if not audio_engine:
            return {
                "status": "not_initialized",
                "message": "Audio engine not initialized",
                "lfm_models": lfm_models
            }
        
        return {
            "status": "success",
            "engine_status": audio_engine.get_status(),
            "lfm_models": lfm_models
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/api/voice/start")
async def start_voice_engine():
    """Start the voice processing engine"""
    try:
        audio_engine = get_audio_engine()
        if not audio_engine:
            return {"status": "error", "message": "Audio engine not available"}
        
        success = audio_engine.start()
        return {
            "status": "success" if success else "error",
            "message": "Voice engine started" if success else "Failed to start",
            "state": audio_engine.state.value
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/api/voice/stop")
async def stop_voice_engine():
    """Stop the voice processing engine"""
    try:
        audio_engine = get_audio_engine()
        if not audio_engine:
            return {"status": "error", "message": "Audio engine not available"}
        
        audio_engine.stop()
        return {
            "status": "success",
            "message": "Voice engine stopped",
            "state": audio_engine.state.value
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ============================================================================
# Agent API Endpoints
# ============================================================================

@app.get("/api/agent/personality")
async def get_personality():
    """Get current personality profile"""
    try:
        personality = get_personality_engine()
        return {
            "status": "success",
            "profile": personality.get_profile(),
            "system_prompt": personality.get_system_prompt()
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/api/agent/personality/test")
async def test_personality(prompt: str = "Hello, who are you?"):
    """Test personality with a sample prompt"""
    try:
        personality = get_personality_engine()
        system_prompt = personality.get_system_prompt()
        
        return {
            "status": "success",
            "system_prompt": system_prompt,
            "test_prompt": prompt,
            "note": "Full inference would require LLM integration"
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/api/agent/tts/voices")
async def get_tts_voices():
    """Get available TTS voices"""
    try:
        tts = get_tts_manager()
        return {
            "status": "success",
            "voices": tts.get_voice_info()
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/api/agent/tts/speak")
async def tts_speak(text: str, save_to_file: Optional[str] = None):
    """Synthesize text to speech"""
    try:
        tts = get_tts_manager()
        
        if save_to_file:
            success = tts.synthesize_to_file(text, save_to_file)
            return {
                "status": "success" if success else "error",
                "message": f"Audio saved to {save_to_file}" if success else "Synthesis failed",
                "text": text
            }
        else:
            audio = tts.synthesize(text)
            return {
                "status": "success" if audio is not None else "error",
                "message": "Audio generated" if audio is not None else "Synthesis failed",
                "samples": len(audio) if audio is not None else 0,
                "text": text
            }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/api/agent/memory/status")
async def get_memory_status():
    """Get conversation memory status"""
    try:
        memory = get_conversation_memory()
        return {
            "status": "success",
            "token_count": memory.get_token_count(),
            "visualization": memory.get_context_visualization(),
            "summary": memory.get_summary()
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/api/agent/memory/clear")
async def clear_memory():
    """Clear conversation memory"""
    try:
        memory = get_conversation_memory()
        memory.clear()
        return {
            "status": "success",
            "message": "Conversation memory cleared"
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/api/agent/memory/export")
async def export_memory(filepath: str = "conversation_export.json"):
    """Export conversation to file"""
    try:
        memory = get_conversation_memory()
        success = memory.export_to_file(filepath)
        return {
            "status": "success" if success else "error",
            "message": f"Exported to {filepath}" if success else "Export failed",
            "filepath": filepath
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/api/agent/memory/import")
async def import_memory(filepath: str):
    """Import conversation from file"""
    try:
        memory = get_conversation_memory()
        success = memory.import_from_file(filepath)
        return {
            "status": "success" if success else "error",
            "message": f"Imported from {filepath}" if success else "Import failed",
            "filepath": filepath
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/api/agent/wake")
async def get_wake_config_endpoint():
    """Get wake word configuration"""
    try:
        wake = get_wake_config()
        return {
            "status": "success",
            "config": wake.get_config(),
            "supported_phrases": wake.SUPPORTED_PHRASES
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/api/agent/status")
async def get_agent_status():
    """Get complete agent status"""
    try:
        personality = get_personality_engine()
        tts = get_tts_manager()
        memory = get_conversation_memory()
        wake = get_wake_config()
        
        return {
            "status": "success",
            "personality": personality.get_profile(),
            "tts": tts.get_config(),
            "memory": memory.get_token_count(),
            "wake": wake.get_config()
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ============================================================================
# MCP (Model Context Protocol) API Endpoints
# ============================================================================

@app.get("/api/mcp/tools")
async def get_mcp_tools():
    """Get all available MCP tools"""
    try:
        registry = get_tool_registry()
        return {
            "status": "success",
            "tools": registry.get_all_tools(),
            "favorites": registry.get_favorite_tools(),
            "success_rate": registry.get_success_rate()
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/api/mcp/tools/search")
async def search_mcp_tools(query: str):
    """Search MCP tools by name or description"""
    try:
        registry = get_tool_registry()
        results = registry.search_tools(query)
        return {
            "status": "success",
            "query": query,
            "results": results,
            "count": len(results)
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/api/mcp/tools/execute")
async def execute_mcp_tool(tool_name: str, arguments: dict):
    """Execute an MCP tool"""
    try:
        registry = get_tool_registry()
        
        # Check if tool exists
        tool = registry.get_tool(tool_name)
        if not tool:
            return {
                "status": "error",
                "message": f"Tool not found: {tool_name}"
            }
        
        # Execute local tool
        if tool.get("local"):
            result = await registry.execute_local_tool(tool_name, arguments)
            success = result is not None and not isinstance(result, dict) or not result.get("error")
            registry.record_execution(tool_name, "local", arguments, result, success)
            
            return {
                "status": "success" if success else "error",
                "tool": tool_name,
                "arguments": arguments,
                "result": result
            }
        else:
            # External server tool - would need server manager
            return {
                "status": "error",
                "message": "External server tools not yet implemented"
            }
            
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/api/mcp/history")
async def get_mcp_history(limit: int = 10):
    """Get recent tool execution history"""
    try:
        registry = get_tool_registry()
        history = registry.get_execution_history(limit)
        return {
            "status": "success",
            "history": [
                {
                    "tool": h.tool_name,
                    "server": h.server_name,
                    "success": h.success,
                    "timestamp": h.timestamp
                }
                for h in history
            ]
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/api/mcp/history/clear")
async def clear_mcp_history():
    """Clear tool execution history"""
    try:
        registry = get_tool_registry()
        registry.clear_history()
        return {
            "status": "success",
            "message": "Execution history cleared"
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/api/mcp/status")
async def get_mcp_status():
    """Get MCP system status"""
    try:
        server_manager = get_server_manager()
        registry = get_tool_registry()
        
        return {
            "status": "success",
            "servers": {
                "registered": [s.name for s in server_manager.get_servers()],
                "connected": server_manager.get_connected_servers()
            },
            "tools": {
                "total": len(registry.get_all_tools()),
                "favorites": registry.get_favorite_tools(),
                "success_rate": registry.get_success_rate()
            }
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ============================================================================
# SYSTEM Node API Endpoints
# ============================================================================

# ----------------------------------------------------------------------------
# Power Management
# ----------------------------------------------------------------------------

@app.post("/api/system/power/shutdown")
async def system_shutdown(delay: int = 0):
    """Shutdown the system"""
    try:
        power = get_power_manager()
        result = await power.shutdown(delay)
        return {"status": "success" if result.get("success") else "error", **result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/api/system/power/restart")
async def system_restart(delay: int = 0):
    """Restart the system"""
    try:
        power = get_power_manager()
        result = await power.restart(delay)
        return {"status": "success" if result.get("success") else "error", **result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/api/system/power/sleep")
async def system_sleep():
    """Put system to sleep"""
    try:
        power = get_power_manager()
        result = await power.sleep()
        return {"status": "success" if result.get("success") else "error", **result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/api/system/power/lock")
async def system_lock():
    """Lock the screen"""
    try:
        power = get_power_manager()
        result = await power.lock_screen()
        return {"status": "success" if result.get("success") else "error", **result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/api/system/power/profile")
async def set_power_profile(profile: str):
    """Set power profile (Balanced, Performance, Battery)"""
    try:
        from backend.system.power import PowerProfile
        power = get_power_manager()
        
        try:
            profile_enum = PowerProfile(profile)
        except ValueError:
            return {"status": "error", "message": f"Invalid profile: {profile}"}
        
        result = power.set_power_profile(profile_enum)
        return {"status": "success" if result.get("success") else "error", **result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/api/system/power/battery")
async def get_battery_status():
    """Get battery status"""
    try:
        power = get_power_manager()
        result = power.get_battery_status()
        return {"status": "success" if result.get("success") else "error", **result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/api/system/power/status")
async def get_power_status():
    """Get complete power status"""
    try:
        power = get_power_manager()
        return {"status": "success", **power.get_status()}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ----------------------------------------------------------------------------
# Display Management
# ----------------------------------------------------------------------------

@app.get("/api/system/display/brightness")
async def get_brightness():
    """Get current brightness level"""
    try:
        display = get_display_manager()
        return {"status": "success", "brightness": display.get_brightness()}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/api/system/display/brightness")
async def set_brightness(level: int):
    """Set screen brightness (0-100)"""
    try:
        display = get_display_manager()
        result = display.set_brightness(level)
        return {"status": "success" if result.get("success") else "error", **result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/api/system/display/resolutions")
async def get_resolutions():
    """Get available screen resolutions"""
    try:
        display = get_display_manager()
        resolutions = display.get_resolutions()
        return {"status": "success", "resolutions": resolutions}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/api/system/display/resolution")
async def set_resolution(width: int, height: int):
    """Set screen resolution"""
    try:
        display = get_display_manager()
        result = display.set_resolution(width, height)
        return {"status": "success" if result.get("success") else "error", **result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/api/system/display/nightmode")
async def set_night_mode(enabled: bool):
    """Toggle night mode / blue light filter"""
    try:
        display = get_display_manager()
        result = display.set_night_mode(enabled)
        return {"status": "success" if result.get("success") else "error", **result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/api/system/display/monitors")
async def get_monitors():
    """Get list of connected monitors"""
    try:
        display = get_display_manager()
        monitors = display.get_monitors()
        return {"status": "success", "monitors": monitors}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/api/system/display/status")
async def get_display_status():
    """Get complete display status"""
    try:
        display = get_display_manager()
        return {"status": "success", **display.get_status()}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ----------------------------------------------------------------------------
# Storage Management
# ----------------------------------------------------------------------------

@app.get("/api/system/storage/drives")
async def get_storage_drives():
    """Get all storage drives"""
    try:
        storage = get_storage_manager()
        drives = storage.get_all_drives()
        return {"status": "success", "drives": drives}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/api/system/storage/usage")
async def get_disk_usage(path: str = "/"):
    """Get disk usage for a path"""
    try:
        storage = get_storage_manager()
        result = storage.get_disk_usage(path)
        return {"status": "success" if result.get("success") else "error", **result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/api/system/storage/quickfolders")
async def get_quick_folders():
    """Get quick folders (Desktop, Downloads, Documents) info"""
    try:
        storage = get_storage_manager()
        folders = storage.get_quick_folders()
        return {"status": "success", "folders": folders}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/api/system/storage/cleanup")
async def cleanup_storage():
    """Clean up temporary files"""
    try:
        storage = get_storage_manager()
        result = storage.cleanup_temp_files()
        return {"status": "success" if result.get("success") else "error", **result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/api/system/storage/external")
async def get_external_drives():
    """Get external/removable drives"""
    try:
        storage = get_storage_manager()
        drives = storage.get_external_drives()
        return {"status": "success", "drives": drives}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/api/system/storage/open")
async def open_folder(path: str):
    """Open a folder in file manager"""
    try:
        storage = get_storage_manager()
        result = storage.open_folder(path)
        return {"status": "success" if result.get("success") else "error", **result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/api/system/storage/status")
async def get_storage_status():
    """Get complete storage status"""
    try:
        storage = get_storage_manager()
        return {"status": "success", **storage.get_status()}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ----------------------------------------------------------------------------
# Network Management
# ----------------------------------------------------------------------------

@app.get("/api/system/network/wifi")
async def get_wifi_status():
    """Get WiFi status"""
    try:
        network = get_network_manager()
        result = network.get_wifi_status()
        return {"status": "success" if result.get("success") else "error", **result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/api/system/network/wifi")
async def set_wifi(enabled: bool):
    """Enable/disable WiFi"""
    try:
        network = get_network_manager()
        result = network.set_wifi_enabled(enabled)
        return {"status": "success" if result.get("success") else "error", **result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/api/system/network/ethernet")
async def get_ethernet_status():
    """Get Ethernet connection status"""
    try:
        network = get_network_manager()
        result = network.get_ethernet_status()
        return {"status": "success" if result.get("success") else "error", **result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/api/system/network/vpn")
async def set_vpn(vpn_type: str):
    """Connect to VPN (None, Work, Personal)"""
    try:
        from .system.network import VPNType
        network = get_network_manager()
        
        try:
            vpn_enum = VPNType(vpn_type)
        except ValueError:
            return {"status": "error", "message": f"Invalid VPN type: {vpn_type}"}
        
        result = network.connect_vpn(vpn_enum)
        return {"status": "success" if result.get("success") else "error", **result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/api/system/network/bandwidth")
async def get_bandwidth():
    """Get current bandwidth usage"""
    try:
        network = get_network_manager()
        result = network.get_bandwidth_usage()
        return {"status": "success" if result.get("success") else "error", **result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/api/system/network/test")
async def test_network(host: str = "8.8.8.8"):
    """Test network connectivity"""
    try:
        network = get_network_manager()
        result = network.test_connection(host)
        return {"status": "success" if result.get("success") else "error", **result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/api/system/network/interfaces")
async def get_network_interfaces():
    """Get network interface information"""
    try:
        network = get_network_manager()
        result = network.get_network_info()
        return {"status": "success" if result.get("success") else "error", **result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/api/system/network/status")
async def get_network_status():
    """Get complete network status"""
    try:
        network = get_network_manager()
        return {"status": "success", **network.get_status()}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ----------------------------------------------------------------------------
# System Status (All-in-one)
# ----------------------------------------------------------------------------

@app.get("/api/system/status")
async def get_system_status():
    """Get complete system status (power, display, storage, network)"""
    try:
        power = get_power_manager()
        display = get_display_manager()
        storage = get_storage_manager()
        network = get_network_manager()
        
        return {
            "status": "success",
            "power": power.get_status(),
            "display": display.get_status(),
            "storage": storage.get_status(),
            "network": network.get_status()
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ============================================================================
# CUSTOMIZE Node API Endpoints
# ============================================================================

# ----------------------------------------------------------------------------
# Startup Settings
# ----------------------------------------------------------------------------

@app.get("/api/customize/startup")
async def get_startup_settings():
    """Get startup configuration"""
    try:
        startup = get_startup_manager()
        return {
            "status": "success",
            "config": startup.get_config(),
            "auto_launch_enabled": startup.is_auto_launch_enabled()
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/api/customize/startup")
async def update_startup_settings(
    launch_at_startup: bool = None,
    startup_behavior: str = None,
    welcome_message: bool = None,
    default_state: str = None
):
    """Update startup configuration"""
    try:
        startup = get_startup_manager()
        
        update_kwargs = {}
        if launch_at_startup is not None:
            update_kwargs["launch_at_startup"] = launch_at_startup
        if startup_behavior is not None:
            update_kwargs["startup_behavior"] = startup_behavior
        if welcome_message is not None:
            update_kwargs["welcome_message"] = welcome_message
        if default_state is not None:
            update_kwargs["default_state"] = default_state
        
        startup.update_config(**update_kwargs)
        
        return {
            "status": "success",
            "config": startup.get_config(),
            "auto_launch_enabled": startup.is_auto_launch_enabled()
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ----------------------------------------------------------------------------
# Behavior Settings
# ----------------------------------------------------------------------------

@app.get("/api/customize/behavior")
async def get_behavior_settings():
    """Get behavior configuration"""
    try:
        behavior = get_behavior_manager()
        return {
            "status": "success",
            "config": behavior.get_config(),
            "can_undo": behavior.can_undo(),
            "can_redo": behavior.can_redo()
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/api/customize/behavior")
async def update_behavior_settings(
    confirm_destructive: bool = None,
    undo_history: int = None,
    error_notifications: str = None,
    auto_save: bool = None
):
    """Update behavior configuration"""
    try:
        behavior = get_behavior_manager()
        
        update_kwargs = {}
        if confirm_destructive is not None:
            update_kwargs["confirm_destructive"] = confirm_destructive
        if undo_history is not None:
            update_kwargs["undo_history"] = undo_history
        if error_notifications is not None:
            update_kwargs["error_notifications"] = error_notifications
        if auto_save is not None:
            update_kwargs["auto_save"] = auto_save
        
        behavior.update_config(**update_kwargs)
        
        return {
            "status": "success",
            "config": behavior.get_config()
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/api/customize/behavior/undo")
async def get_undo_history(limit: int = 10):
    """Get undo history"""
    try:
        behavior = get_behavior_manager()
        return {
            "status": "success",
            "history": behavior.get_undo_history(limit),
            "can_undo": behavior.can_undo(),
            "can_redo": behavior.can_redo()
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/api/customize/behavior/undo")
async def perform_undo():
    """Perform undo action"""
    try:
        behavior = get_behavior_manager()
        action = behavior.undo()
        
        if action:
            return {
                "status": "success",
                "action": {
                    "id": action.id,
                    "type": action.action_type,
                    "description": action.description
                },
                "can_undo": behavior.can_undo(),
                "can_redo": behavior.can_redo()
            }
        else:
            return {
                "status": "error",
                "message": "Nothing to undo"
            }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/api/customize/behavior/redo")
async def perform_redo():
    """Perform redo action"""
    try:
        behavior = get_behavior_manager()
        action = behavior.redo()
        
        if action:
            return {
                "status": "success",
                "action": {
                    "id": action.id,
                    "type": action.action_type,
                    "description": action.description
                },
                "can_undo": behavior.can_undo(),
                "can_redo": behavior.can_redo()
            }
        else:
            return {
                "status": "error",
                "message": "Nothing to redo"
            }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/api/customize/behavior/clear")
async def clear_behavior_history():
    """Clear undo/redo history"""
    try:
        behavior = get_behavior_manager()
        behavior.clear_history()
        return {
            "status": "success",
            "message": "History cleared"
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ----------------------------------------------------------------------------
# Notification Settings
# ----------------------------------------------------------------------------

@app.get("/api/customize/notifications")
async def get_notification_settings():
    """Get notification configuration"""
    try:
        notifications = get_notification_manager()
        return {
            "status": "success",
            "config": notifications.get_config(),
            "dnd_active": notifications.is_dnd_active(),
            "notifications_allowed": notifications.should_show_notification()
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/api/customize/notifications")
async def update_notification_settings(
    dnd_enabled: bool = None,
    dnd_schedule: str = None,
    notification_sound: str = None,
    banner_style: str = None,
    app_notifications: bool = None
):
    """Update notification configuration"""
    try:
        notifications = get_notification_manager()
        
        update_kwargs = {}
        if dnd_enabled is not None:
            update_kwargs["dnd_enabled"] = dnd_enabled
        if dnd_schedule is not None:
            update_kwargs["dnd_schedule"] = dnd_schedule
        if notification_sound is not None:
            update_kwargs["notification_sound"] = notification_sound
        if banner_style is not None:
            update_kwargs["banner_style"] = banner_style
        if app_notifications is not None:
            update_kwargs["app_notifications"] = app_notifications
        
        notifications.update_config(**update_kwargs)
        
        return {
            "status": "success",
            "config": notifications.get_config(),
            "dnd_active": notifications.is_dnd_active()
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/api/customize/notifications/test")
async def test_notification(title: str = "Test", message: str = "This is a test notification"):
    """Send a test notification"""
    try:
        notifications = get_notification_manager()
        result = notifications.show_notification(title, message)
        return {
            "status": "success" if result.get("success") else "error",
            **result
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ============================================================================
# MONITOR Node API Endpoints
# ============================================================================

# ----------------------------------------------------------------------------
# Analytics
# ----------------------------------------------------------------------------

@app.get("/api/monitor/analytics")
async def get_analytics():
    """Get usage analytics"""
    try:
        analytics = get_analytics_manager()
        return {
            "status": "success",
            "session_stats": analytics.get_session_stats(),
            "latency_metrics": analytics.get_latency_metrics()
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/api/monitor/analytics/recent")
async def get_recent_analytics(limit: int = 10):
    """Get recent usage records"""
    try:
        analytics = get_analytics_manager()
        return {
            "status": "success",
            "records": analytics.get_recent_records(limit)
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/api/monitor/analytics/reset")
async def reset_analytics():
    """Reset session analytics"""
    try:
        analytics = get_analytics_manager()
        analytics.reset_session()
        return {
            "status": "success",
            "message": "Analytics reset"
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ----------------------------------------------------------------------------
# Logs
# ----------------------------------------------------------------------------

@app.get("/api/monitor/logs")
async def get_logs(source: str = None, level: str = None, limit: int = 100):
    """Get system logs"""
    try:
        logs = get_log_manager()
        return {
            "status": "success",
            "logs": logs.get_logs(source=source, level=level, limit=limit)
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/api/monitor/logs/by-source")
async def get_logs_by_source():
    """Get logs grouped by source"""
    try:
        logs = get_log_manager()
        return {
            "status": "success",
            "logs_by_source": logs.get_logs_by_source()
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/api/monitor/logs/export")
async def export_logs(filepath: str = None, source: str = None, level: str = None):
    """Export logs to file"""
    try:
        logs = get_log_manager()
        result = logs.export_logs(filepath, source, level)
        return {"status": "success" if result.get("success") else "error", **result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/api/monitor/logs/clear")
async def clear_logs(source: str = None):
    """Clear logs"""
    try:
        logs = get_log_manager()
        result = logs.clear_logs(source)
        return {"status": "success" if result.get("success") else "error", **result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ----------------------------------------------------------------------------
# Diagnostics
# ----------------------------------------------------------------------------

@app.get("/api/monitor/health")
async def get_health_status():
    """Get health check summary"""
    try:
        diagnostics = get_diagnostics_manager()
        return {
            "status": "success",
            **diagnostics.get_health_summary()
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/api/monitor/health/check")
async def run_health_checks():
    """Run comprehensive health checks"""
    try:
        diagnostics = get_diagnostics_manager()
        checks = await diagnostics.run_health_checks()
        return {
            "status": "success",
            "checks": [{"component": c.component, "status": c.status, 
                       "message": c.message, "latency_ms": c.latency_ms} for c in checks]
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/api/monitor/benchmark/lfm")
async def benchmark_lfm():
    """Run LFM model benchmark"""
    try:
        diagnostics = get_diagnostics_manager()
        result = await diagnostics.benchmark_lfm()
        return {"status": "success" if result.get("success") else "error", **result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/api/monitor/test/mcp")
async def test_mcp_tools():
    """Test MCP tools"""
    try:
        diagnostics = get_diagnostics_manager()
        result = await diagnostics.test_mcp_tools()
        return {"status": "success" if result.get("success") else "error", **result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/api/monitor/system-info")
async def get_system_info():
    """Get system information"""
    try:
        diagnostics = get_diagnostics_manager()
        return {
            "status": "success",
            "info": diagnostics.get_system_info()
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ----------------------------------------------------------------------------
# Updates
# ----------------------------------------------------------------------------

@app.get("/api/monitor/updates")
async def get_update_settings():
    """Get update configuration"""
    try:
        updates = get_update_manager()
        return {
            "status": "success",
            "config": updates.get_config(),
            "current_version": updates.get_current_version()
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/api/monitor/updates")
async def update_update_settings(
    update_channel: str = None,
    auto_update: bool = None
):
    """Update update configuration"""
    try:
        updates = get_update_manager()
        
        update_kwargs = {}
        if update_channel is not None:
            update_kwargs["update_channel"] = update_channel
        if auto_update is not None:
            update_kwargs["auto_update"] = auto_update
        
        updates.update_config(**update_kwargs)
        
        return {
            "status": "success",
            "config": updates.get_config()
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/api/monitor/updates/check")
async def check_for_updates():
    """Check for available updates"""
    try:
        updates = get_update_manager()
        result = await updates.check_for_updates()
        return {"status": "success" if result.get("success") else "error", **result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/api/monitor/updates/changelog")
async def get_changelog(version: str = None):
    """Get changelog"""
    try:
        updates = get_update_manager()
        return {
            "status": "success",
            **updates.get_changelog(version)
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/api/monitor/updates/channels")
async def get_update_channels():
    """Get available update channels"""
    try:
        updates = get_update_manager()
        return {
            "status": "success",
            **updates.get_update_channels()
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ============================================================================
# WebSocket Handler
# ============================================================================

async def handle_message(websocket: WebSocket, client_id: str, message: dict) -> None:
    """
    Process incoming WebSocket messages.
    Routes to appropriate handler based on message type.
    """
    msg_type = message.get("type")
    payload = message.get("payload", {})
    
    state_manager = get_state_manager()
    ws_manager = get_websocket_manager()
    
    # ------------------------------------------------------------------------
    # select_category: Switch to a main category view
    # ------------------------------------------------------------------------
    if msg_type == "select_category":
        category_str = payload.get("category")
        if category_str:
            try:
                category = Category(category_str)
                state_manager.set_category(category)
                
                # Get subnodes for this category
                subnodes = get_subnodes_for_category(category_str)
                
                # Send confirmation to client
                await ws_manager.send_to_client(client_id, {
                    "type": "category_changed",
                    "category": category_str,
                    "subnodes": [s.model_dump() for s in subnodes]
                })
                
                # Broadcast to other clients
                await ws_manager.broadcast({
                    "type": "state_sync",
                    "state": state_manager.state.model_dump()
                }, exclude={client_id})
                
            except ValueError:
                await ws_manager.send_error(client_id, f"Invalid category: {category_str}")
    
    # ------------------------------------------------------------------------
    # select_subnode: Activate a subnode (show mini-nodes)
    # ------------------------------------------------------------------------
    elif msg_type == "select_subnode":
        subnode_id = payload.get("subnode_id")
        if subnode_id:
            state_manager.set_subnode(subnode_id)
            
            await ws_manager.send_to_client(client_id, {
                "type": "subnode_changed",
                "subnode_id": subnode_id
            })
    
    # ------------------------------------------------------------------------
    # field_update: Update a field value (with validation)
    # ------------------------------------------------------------------------
    elif msg_type == "field_update":
        subnode_id = payload.get("subnode_id")
        field_id = payload.get("field_id")
        value = payload.get("value")
        
        if all([subnode_id, field_id is not None, value is not None]):
            valid = state_manager.update_field(subnode_id, field_id, value)
            
            if valid:
                await ws_manager.send_to_client(client_id, {
                    "type": "field_updated",
                    "subnode_id": subnode_id,
                    "field_id": field_id,
                    "value": value,
                    "valid": True
                })
                
                # Auto-save after field update
                category = state_manager._get_category_for_subnode(subnode_id)
                await state_manager.save_category(category)
                
                # Apply voice configuration if voice category
                apply_voice_config(category, field_id, value)
                
                # Apply agent configuration if agent category
                apply_agent_config(category, field_id, value)
                
                # Broadcast theme update if it's a color field
                if field_id == "glow_color" and isinstance(value, str):
                    theme = state_manager.state.active_theme
                    await ws_manager.broadcast({
                        "type": "theme_updated",
                        "glow": value,
                        "font": theme.font,
                        "primary": value,
                        "state_colors_enabled": theme.state_colors_enabled,
                        "idle_color": theme.idle_color,
                        "listening_color": theme.listening_color,
                        "processing_color": theme.processing_color,
                        "error_color": theme.error_color
                    })
                    
            else:
                await ws_manager.send_error(
                    client_id, 
                    f"Invalid value for {field_id}",
                    field_id=field_id
                )
    
    # ------------------------------------------------------------------------
    # confirm_mini_node: Confirm a mini-node (add to orbit)
    # ------------------------------------------------------------------------
    elif msg_type == "confirm_mini_node":
        subnode_id = payload.get("subnode_id")
        values = payload.get("values", {})
        
        if subnode_id:
            # Update theme if glow_color in values
            if "glow_color" in values and isinstance(values["glow_color"], str):
                state_manager.update_theme(glow_color=values["glow_color"])
            
            # Derive category from subnode_id
            category = state_manager._get_category_for_subnode(subnode_id)
            
            # Confirm the subnode
            orbit_angle = state_manager.confirm_subnode(category, subnode_id, values)
            
            # Save state
            await state_manager.save_category(category)
            await state_manager.save_theme()
            
            await ws_manager.send_to_client(client_id, {
                "type": "mini_node_confirmed",
                "subnode_id": subnode_id,
                "orbit_angle": orbit_angle
            })
            
            # Broadcast state sync
            await ws_manager.broadcast({
                "type": "state_sync",
                "state": state_manager.state.model_dump()
            }, exclude={client_id})
    
    # ------------------------------------------------------------------------
    # update_theme: Update theme colors directly
    # ------------------------------------------------------------------------
    elif msg_type == "update_theme":
        glow_color = payload.get("glow_color")
        font_color = payload.get("font_color")
        state_colors = payload.get("state_colors")
        
        update_kwargs = {}
        if glow_color:
            update_kwargs["glow_color"] = glow_color
        if font_color:
            update_kwargs["font_color"] = font_color
        if state_colors is not None:
            update_kwargs["state_colors"] = state_colors
        
        state_manager.update_theme(**update_kwargs)
        
        await state_manager.save_theme()
        
        # Broadcast theme change to all clients
        theme = state_manager.state.active_theme
        await ws_manager.broadcast({
            "type": "theme_updated",
            "glow": theme.glow,
            "font": theme.font,
            "primary": theme.primary,
            "state_colors_enabled": theme.state_colors_enabled,
            "idle_color": theme.idle_color,
            "listening_color": theme.listening_color,
            "processing_color": theme.processing_color,
            "error_color": theme.error_color
        })
    
    # ------------------------------------------------------------------------
    # request_state: Send full current state
    # ------------------------------------------------------------------------
    elif msg_type == "request_state":
        await ws_manager.send_to_client(client_id, {
            "type": "initial_state",
            "state": state_manager.state.model_dump()
        })
    
    # ------------------------------------------------------------------------
    # ping/pong: Keep connection alive
    # ------------------------------------------------------------------------
    elif msg_type == "ping":
        await ws_manager.send_to_client(client_id, {"type": "pong"})
    
    # ------------------------------------------------------------------------
    # Unknown message type
    # ------------------------------------------------------------------------
    else:
        await ws_manager.send_error(client_id, f"Unknown message type: {msg_type}")


# ============================================================================
# WebSocket Endpoint
# ============================================================================

@app.websocket("/ws/iris")
async def websocket_endpoint(websocket: WebSocket):
    """
    Main WebSocket endpoint for IRIS.
    Handles connection, message loop, and disconnection.
    """
    # Generate unique client ID
    client_id = str(uuid.uuid4())[:8]
    ws_manager = get_websocket_manager()
    state_manager = get_state_manager()
    
    # Accept connection
    connected = await ws_manager.connect(websocket, client_id)
    if not connected:
        return
    
    try:
        # Send initial state
        await ws_manager.send_to_client(client_id, {
            "type": "initial_state",
            "state": state_manager.state.model_dump()
        })
        
        # Message loop
        while True:
            try:
                # Receive message
                data = await websocket.receive_text()
                
                try:
                    message = json.loads(data)
                except json.JSONDecodeError:
                    await ws_manager.send_error(client_id, "Invalid JSON")
                    continue
                
                # Handle message
                await handle_message(websocket, client_id, message)
                
            except WebSocketDisconnect:
                break
            except Exception as e:
                print(f"Error processing message from {client_id}: {e}")
                await ws_manager.send_error(client_id, f"Server error: {str(e)}")
    
    except Exception as e:
        print(f"WebSocket error for {client_id}: {e}")
    
    finally:
        # Clean up
        ws_manager.disconnect(client_id)


# ============================================================================
# Startup
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    
    # Get port from environment or default to 8000
    port = int(os.environ.get("IRIS_PORT", 8000))
    host = os.environ.get("IRIS_HOST", "127.0.0.1")
    
    print(f"""
╔══════════════════════════════════════════╗
║            IRIS Backend Server           ║
╠══════════════════════════════════════════╣
║  WebSocket: ws://{host}:{port}/ws/iris    ║
║  HTTP API:  http://{host}:{port}/         ║
╚══════════════════════════════════════════╝
    """)
    
    uvicorn.run(
        "backend.main:app",
        host=host,
        port=port,
        reload=True,
        log_level="info"
    )
