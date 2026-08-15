# IRIS Connection Architecture: From Chat to Engine

## The Core Problem Visualized

```
WHAT YOU HAVE NOW:
─────────────────

 [User types]
      │
      ▼
 [WebSocket]  ←── drops here because something below fails silently
      │
      ▼
 [FastAPI]
      │
      ├── Which mode? Swarm? Local? API?   ← ambiguity point
      ├── Which model? LFM? LM Studio? VP? ← overlapping settings
      ├── Swarm mode set in inference?      ← conflict risk
      │
      ▼
 [Engine fires, but response never routes back]
      │
      ▼
 [Silence / WebSocket timeout]


WHAT YOU NEED:
──────────────

 [User types]
      │
      ▼
 [WebSocket — keep-alive + heartbeat]
      │
      ▼
 [FastAPI: ONE resolver that decides routing]
      │
      ├──► SWARM MODE?  ──► SwarmOrchestrator ──► response
      ├──► LOCAL MODEL? ──► LM Studio URL      ──► response
      └──► API MODE?    ──► API Endpoint        ──► response
                                │
                                ▼
                      [Single response collector]
                                │
                                ▼
                      [WebSocket sends back]
```

-----

## The Two Settings Problem

You described two settings areas that currently overlap:

```
INFERENCE SETTINGS          MODEL SETTINGS
──────────────────          ──────────────
  - Which local model         - Local model ON/OFF
  - LFM Studio URL            - LFM Studio URL
  - Swarm mode ← HERE         - API URL
                              - VPS
```

**The conflict:** Swarm mode is a *routing decision*, not an inference parameter.
When both sections can affect routing, the backend doesn’t know which one wins.

### Proposed Clean Separation:

```
┌─────────────────────────────────────────────────────┐
│                  SETTINGS SCHEMA                     │
├──────────────────────┬──────────────────────────────┤
│   ROUTING LAYER      │   INFERENCE LAYER            │
│   (what to use)      │   (how to use it)            │
├──────────────────────┼──────────────────────────────┤
│  mode: enum          │  local_model_id: string      │
│    SINGLE_API        │  lm_studio_url: string       │
│    SINGLE_LOCAL      │  api_key: string             │
│    SWARM_QUALITY     │  api_endpoint: string        │
│    SWARM_TURBO       │  vps_endpoint: string        │
│    SWARM_HYBRID      │  temperature: float          │
│                      │  max_tokens: int             │
│  director_source:    │                              │
│    local | api       │  swarm_worker_count: int     │
│                      │  gpu_layers: int             │
└──────────────────────┴──────────────────────────────┘

RULE: "mode" in ROUTING LAYER is the single source of truth.
      Backend reads mode FIRST, then pulls from INFERENCE LAYER
      only for the parameters that mode needs.
```

-----

## The Single Resolver Pattern

This is the most important change. One function in FastAPI that all messages go through:

```python
# backend/router.py

async def resolve_backend(
    message: str,
    config: IRISConfig
) -> AsyncGenerator[str, None]:
    """
    Single entry point. All chat messages come here first.
    Never call swarm/local/api directly from WebSocket handler.
    """

    mode = config.routing.mode  # ALWAYS read this first

    match mode:
        case "SINGLE_API":
            async for chunk in call_api(
                message,
                endpoint=config.inference.api_endpoint,
                key=config.inference.api_key
            ):
                yield chunk

        case "SINGLE_LOCAL":
            async for chunk in call_local(
                message,
                url=config.inference.lm_studio_url,
                model=config.inference.local_model_id
            ):
                yield chunk

        case "SWARM_QUALITY":
            async for chunk in call_swarm(
                message,
                config=config,
                director="qk3_ternary",    # your Q-K3 director
                workers="turbo_quant",     # your 100tok workers
                count=config.inference.swarm_worker_count
            ):
                yield chunk

        case "SWARM_TURBO":
            async for chunk in call_swarm(
                message,
                config=config,
                director="turbo_quant",
                workers="turbo_quant",
                count=config.inference.swarm_worker_count
            ):
                yield chunk

        case "SWARM_HYBRID":
            async for chunk in call_swarm(
                message,
                config=config,
                director="api",            # API director
                workers="local",           # local workers
                count=config.inference.swarm_worker_count
            ):
                yield chunk

        case _:
            yield "ERROR: Unknown mode. Check your config."
```

-----

## WebSocket: Why It Goes Silent and How to Fix It

```
THE DROP PATTERN:
─────────────────

Client sends message
     │
     ▼
WS receives, calls backend
     │
     ▼
Backend enters resolve_backend()
     │
     ▼
Something throws an exception ──► exception not caught
     │                                    │
     ▼                                    ▼
No response sent                  WS times out (30s default)
     │                                    │
     └─────────────────┬──────────────────┘
                       ▼
                 Connection drops
              (looks like WS bug,
               is actually silence)
```

### Fix: Wrap everything, never go silent

```python
# backend/websocket_handler.py

@app.websocket("/ws/chat")
async def chat_ws(websocket: WebSocket):
    await websocket.accept()

    # HEARTBEAT: keeps connection alive during long inference
    async def heartbeat():
        while True:
            try:
                await asyncio.sleep(15)
                await websocket.send_json({"type": "ping"})
            except:
                break

    heartbeat_task = asyncio.create_task(heartbeat())

    try:
        while True:
            data = await websocket.receive_json()
            message = data.get("message", "")
            config = load_config()  # reads your config file, not env

            # NEVER let this throw silently
            try:
                async for chunk in resolve_backend(message, config):
                    await websocket.send_json({
                        "type": "chunk",
                        "content": chunk
                    })
                await websocket.send_json({"type": "done"})

            except ModelLoadError as e:
                await websocket.send_json({
                    "type": "error",
                    "message": f"Model failed to load: {e}"
                })
            except RoutingError as e:
                await websocket.send_json({
                    "type": "error",
                    "message": f"Routing failed: {e}"
                })
            except Exception as e:
                # Catch-all: system never goes silent
                await websocket.send_json({
                    "type": "error",
                    "message": f"Unexpected error: {type(e).__name__}: {e}"
                })

    except WebSocketDisconnect:
        heartbeat_task.cancel()
```

-----

## Config File Pattern (No .env)

Since your frontend updates a config file from UI input fields:

```python
# backend/config.py

from dataclasses import dataclass
import json
from pathlib import Path

CONFIG_PATH = Path("iris_config.json")

@dataclass
class RoutingConfig:
    mode: str = "SINGLE_LOCAL"        # default safe mode
    director_source: str = "local"

@dataclass
class InferenceConfig:
    local_model_id: str = ""
    lm_studio_url: str = "http://localhost:1234/v1"
    api_endpoint: str = ""
    api_key: str = ""
    vps_endpoint: str = ""
    swarm_worker_count: int = 6
    temperature: float = 0.7
    max_tokens: int = 2048

@dataclass
class IRISConfig:
    routing: RoutingConfig
    inference: InferenceConfig

def load_config() -> IRISConfig:
    """Called fresh on every request — picks up UI changes immediately."""
    if not CONFIG_PATH.exists():
        return IRISConfig(
            routing=RoutingConfig(),
            inference=InferenceConfig()
        )
    raw = json.loads(CONFIG_PATH.read_text())
    return IRISConfig(
        routing=RoutingConfig(**raw.get("routing", {})),
        inference=InferenceConfig(**raw.get("inference", {}))
    )

def save_config(config: IRISConfig):
    """Frontend calls PUT /config — backend writes this file."""
    CONFIG_PATH.write_text(json.dumps({
        "routing": config.routing.__dict__,
        "inference": config.inference.__dict__
    }, indent=2))
```

```
Config file on disk: iris_config.json
{
  "routing": {
    "mode": "SWARM_QUALITY",
    "director_source": "local"
  },
  "inference": {
    "local_model_id": "qwen3-8b-q4",
    "lm_studio_url": "http://localhost:1234/v1",
    "swarm_worker_count": 6,
    "temperature": 0.7
  }
}
```

-----

## Swarm Mode: How the Modes Map to Your Hardware

```
Your 6 simultaneous models on RTX 4090:

SWARM_QUALITY:
┌─────────────────────────────────────────────────────┐
│  Director: Q-K3 Ternary (1 instance, quality gate)  │
│  Workers:  Turbo Quant x5 (parallel, 100tok each)   │
│                                                      │
│  Flow: task → workers generate → director reviews   │
│        director picks best → send to user           │
│                                                      │
│  Best for: complex tasks, accuracy matters          │
└─────────────────────────────────────────────────────┘

SWARM_TURBO:
┌─────────────────────────────────────────────────────┐
│  Director: Turbo Quant (1 instance)                  │
│  Workers:  Turbo Quant x5                            │
│                                                      │
│  Flow: task → all generate in parallel               │
│        director picks fastest/best → send           │
│                                                      │
│  Best for: speed, simple tasks, drafts              │
└─────────────────────────────────────────────────────┘

SWARM_HYBRID:
┌─────────────────────────────────────────────────────┐
│  Director: API (Claude/GPT, high quality)            │
│  Workers:  Local x6 (fast, cheap)                    │
│                                                      │
│  Flow: API director sets strategy + reviews          │
│        Local workers do the grunt work              │
│                                                      │
│  Best for: quality ceiling without full API cost    │
└─────────────────────────────────────────────────────┘
```

-----

## The Testing Ladder: Start Here, Not at the Top

The reason nothing worked end-to-end is that you built floors 1-8 of a building and then tried to live on floor 9 before installing the stairs. Here’s the ladder:

```
STEP 1: Bare WebSocket test
────────────────────────────
  POST /ws/chat with message: "ping"
  Backend returns: "pong" (hardcoded, no model)
  
  If this fails: WebSocket setup is broken.
  If this works: WebSocket is fine, problem is routing.


STEP 2: Single local model
────────────────────────────
  Set mode = "SINGLE_LOCAL"
  Send: "What is 2+2?"
  Expect: any response from LM Studio
  
  If this fails: LM Studio URL or model loading is broken.
  If this works: local inference path is confirmed.


STEP 3: Single API model
────────────────────────────
  Set mode = "SINGLE_API"
  Send: "What is 2+2?"
  Expect: any response from API
  
  If this fails: API key or endpoint config is broken.
  If this works: API path is confirmed.


STEP 4: SWARM_TURBO (simplest swarm)
─────────────────────────────────────
  Set mode = "SWARM_TURBO", workers = 2 (not 6)
  Send: "What is 2+2?"
  Expect: response from swarm
  
  Start with 2 workers, not 6. Easier to debug.
  If this works: scale to 6.


STEP 5: SWARM_QUALITY
─────────────────────────────────────
  Set mode = "SWARM_QUALITY"
  Director = Q-K3, workers = Turbo x5
  Send a real task.
  
  Only do this after step 4 works.


STEP 6: SWARM_HYBRID
─────────────────────────────────────
  Set mode = "SWARM_HYBRID"
  This is the hardest — two different connection types.
  Only after steps 1-5 all work.
```

-----

## On Dynamic State Management Solving This

You’re right, but specifically right in this way:

The routing chaos you’re experiencing is the discrete state machine problem in real life.
Your system is in one of many states (SWARM_QUALITY, loading models, API calling, streaming)
and you have no continuous view of where it actually is in its trajectory.

DSM in C++ would give you:

- A real-time phase coordinate for the system (not just “is it running?”)
- Momentum — if the system is mid-swarm with 3 workers done, the UI knows
  it’s in EXECUTING phase with high confidence of completing
- Self-correction — if 2 workers fail, the restoring force pushes toward
  a COMPRESS (consolidate with what you have) rather than hanging

```
With DSM as the routing layer:

User message arrives
      │
      ▼
Caducean reads (x, y, ξ, u)  ← where is the system in cognitive phase?
      │
      ├── ξ in PLANNING phase  → Director assembles swarm strategy
      ├── ξ in EXECUTING phase → Workers run in parallel
      ├── ξ in REVIEWING phase → Director gates output quality
      └── ξ in CONSOLIDATING  → Memory writes, then respond to user
                │
                ▼
         Response flows back through same phase-aware WebSocket
```

The WebSocket never drops because the system always knows its phase.
A failed worker is a perturbation, not a crash — the limit cycle pulls it back.

**But:** get steps 1-6 on the testing ladder working first.
DSM is the long-term architecture. A working chat is the thing you need today.

```

```