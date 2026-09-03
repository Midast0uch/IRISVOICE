# IRISVOICE — Agent Developer Guide

> Read this file first in every developer mode session before touching any code.
> It tells you what the project is, where everything lives, and the rules you must follow.

---

## What IRISVOICE Is

A local AI voice assistant with a React/Tauri desktop frontend and a Python/FastAPI backend.
The user speaks or types → IRIS understands → responds via text and LuxTTS voice.
You (the agent) can read/write source files, run commands, and commit to your own git branch.

---

## Stack At a Glance

| Layer | Tech |
|---|---|
| Frontend | Next.js 16, React 19, TypeScript, Tailwind, Framer Motion, Tauri 2 |
| Backend | FastAPI + Uvicorn, Python 3.10+, WebSockets |
| Database | SQLCipher (`data/memory.db`) — single shared connection, never open your own |
| LLM | LM Studio (OpenAI-compatible), Ollama, or VPS — configured per session |
| TTS | LuxTTS (voice clone) with pyttsx3 fallback |
| Wake word | Picovoice Porcupine v4 |
| STT | RealtimeSTT + faster-whisper |

---

## Directory Map

```
IRISVOICE/
├── app/                    Next.js pages
│   ├── page.tsx            Main window (IrisOrb + ChatView)
│   ├── dashboard/          Dashboard window
│   └── layout.tsx          Root layout + providers
├── components/             React components
│   ├── iris/IrisOrb.tsx    The central orb UI element
│   ├── chat-view.tsx       Full conversation panel
│   ├── dashboard-wing.tsx  Slide-out dashboard panel
│   └── wheel-view/         4-level nav wheel
├── hooks/
│   └── useIRISWebSocket.ts All WS state + message handling
├── contexts/
│   └── NavigationContext.tsx  Global state provider
├── backend/
│   ├── main.py             FastAPI app, WebSocket /ws/{session_id}
│   ├── iris_gateway.py     Central message router (ALL WS message handling)
│   ├── ws_manager.py       WebSocket connection pool
│   ├── agent/
│   │   ├── agent_kernel.py  Dual-LLM loop (reasoning + execution)
│   │   ├── tool_bridge.py   All tool execution (file, git, shell, vision, GUI)
│   │   ├── tts.py           LuxTTS + pyttsx3 synthesis
│   │   └── personality.py   System prompt / personality config
│   ├── audio/
│   │   ├── engine.py        AudioEngine singleton (Porcupine + frame routing)
│   │   ├── pipeline.py      sounddevice I/O streams
│   │   └── voice_command.py STT recording handler
│   ├── voice/
│   │   └── porcupine_detector.py  Wake word detection
│   ├── memory/             Three-tier + Mycelium memory system
│   │   ├── db.py            SQLCipher connection + schema
│   │   ├── interface.py     Public memory API (use this, not db.py directly)
│   │   ├── semantic.py      Semantic memory tier
│   │   ├── episodic.py      Episodic memory tier
│   │   └── mycelium/        Coordinate-graph memory layer (active spec)
│   └── sessions/           Per-session JSON state files
├── data/
│   ├── memory.db            Encrypted DB (do not delete)
│   └── voice_clone_ref.wav  TTS voice reference
├── models/
│   └── wake_words/          .ppn wake word files (Porcupine v4)
├── .kilo/specs/            Feature specifications (source of truth)
│   ├── iris-mycelium-layer/ ACTIVE — 33 tasks, see tasks.md
│   └── ...completed specs
├── PROJECT.md              This file
└── CLAUDE.md               Spec Execute Mode workflow instructions
```

---

## The 10 Files That Matter Most

| File | What it does |
|---|---|
| `backend/iris_gateway.py` | Routes every WebSocket message — if something doesn't reach the agent, the bug is here |
| `backend/agent/agent_kernel.py` | The brain: dual-LLM loop, tool calling, memory context, TTS dispatch |
| `backend/agent/tool_bridge.py` | Every tool the agent can call: file I/O, git, shell, vision, GUI, browser |
| `hooks/useIRISWebSocket.ts` | All frontend WS state: voiceState, isChatTyping, lastTextResponse, isChatTyping |
| `contexts/NavigationContext.tsx` | Pipes WS state to every component via useNavigation() hook |
| `components/chat-view.tsx` | The conversation UI — messages, typing indicator, thinking blocks |
| `components/iris/IrisOrb.tsx` | The central orb — double-click triggers voice, animates on voice states |
| `backend/audio/engine.py` | AudioEngine singleton — Porcupine wake word + TTS interrupt flags |
| `backend/memory/db.py` | SQLCipher database — schema for all 20+ memory tables |
| `.kilo/specs/iris-mycelium-layer/tasks.md` | Active implementation spec — 33 tasks across 12 phases |

---

## How to Run the Project

```bash
# Start both frontend and backend (recommended)
npm run dev

# Frontend only (port 3000)
npm run dev:frontend

# Backend only (port 8000)
npm run dev:backend
# or: python start-backend.py

# Build for production
npm run build
```

---

## Tools Available to You (developer mode)

All tools are in `tool_bridge.py` and callable from your agent context.

### File I/O
- `read_file(path)` — read any source file
- `write_file(path, content)` — write/overwrite a file
- `list_directory(path)` — list files in a directory
- `create_directory(path)` — create a new directory
- `delete_file(path)` — delete a file or directory

### Git (sandboxed to project root)
- `git_status()` — see what's changed
- `git_diff(staged?)` — see the actual diff
- `git_log(n?)` — recent commits
- `git_commit(message)` — stage all + commit
- `git_create_branch(branch)` — create + switch to new branch
- `git_checkout(branch)` — switch to existing branch
- `git_push()` — push current branch to origin

### Shell
- `run_command(command, cwd?)` — run npm, python, pytest, etc. (120s timeout, sandboxed to project)

### System / GUI
- `open_url(url)`, `search(query)`, `get_system_info()`
- `gui_click`, `gui_type`, `take_screenshot`, `vision_*`

---

## Git Workflow for Developer Mode

Your branch: **`iris-agent-dev`** (create it if it doesn't exist)

```
1. git_checkout("iris-agent-dev")   — or git_create_branch("iris-agent-dev")
2. read the relevant files
3. write_file() your changes
4. git_commit("feat: description of what you did")
5. git_push()
6. Report what you changed and why
```

Never commit directly to `main` or `IRISVOICEv.3`.
The human reviews your branch and merges when satisfied.

---

## Spec Execute Mode

When implementing a spec, read `CLAUDE.md` first — it defines the exact workflow.
Short version:
1. Load all files in `.kilo/specs/{spec-name}/`
2. Find first `<!-- status: pending -->` in `tasks.md` — start there
3. Change to `<!-- status: in_progress -->`, implement, mark `<!-- status: done: summary -->`
4. One task per cycle. Never skip. Never implement ahead.

Active spec: **`iris-mycelium-layer`** — 33 tasks, check tasks.md for current position.

---

## Hard Rules (never break these)

1. **Database**: Only access `data/memory.db` through `backend/memory/db.py` — never open a second connection.
2. **No print()**: Use `import logging; logger = logging.getLogger(__name__)`.
3. **Type hints**: Required on all public methods.
4. **Constants**: Every value must match `requirements.md` and `design*.md` — never invent numbers.
5. **try/except on Mycelium**: All `mycelium/` operations wrapped in try/except so they never block memory.
6. **Session isolation**: Per-session state lives in `backend/sessions/{session_id}/` JSON files.
7. **Single audio engine**: `AudioEngine` is a singleton — one instance per process.
8. **Tests must pass**: `backend/memory/tests/` must pass before marking any memory task done.

---

## WebSocket Message Flow

```
Frontend action
  → useIRISWebSocket.ts sendMessage(type, payload)
    → ws /ws/{session_id}
      → backend/main.py receive
        → iris_gateway.py route by type
          → _handle_chat          (text_message)
          → _handle_voice         (voice_command_start/end)
          → _handle_settings      (confirm_card, get_state)
          → _handle_navigation    (select_category, select_section)
          → _process_voice_transcription  (after STT completes)
```

Response path: `agent_kernel.process_text_message()` → `iris_gateway` → `ws_manager.send_to_client()` → frontend `lastTextResponse` → `chat-view.tsx`.

---

## Current Active Work (as of last commit)

Branch `IRISVOICEv.3`. Recent commits:
- feat: collapsible thinking block in ChatView + re-enable model reasoning
- fix: remove all max_tokens caps + disable thinking on all LM Studio calls
- fix: orb animation on chat + Qwen3 thinking leak + token starvation
- feat: voice-only TTS/STT, spoken summaries, and interrupt support
- fix: decouple TTS from ChatView — voice-only path triggers speech

**Pending work:**
- `iris-mycelium-layer` spec — check tasks.md for current position
- DashboardWing embedded browser (iframe component)
- Launcher developer mode wiring (system prompt + branch injection)
