# Live Testing Checklist — IRISVOICE

**Created:** 2026-05-27  
**Purpose:** Handoff document for the next agent session. Covers code verification, live UI testing, and Caducean/DER/Pacman/MCM benchmarks.  
**Status:** Backend + frontend running, code fixes verified (27/27 tests), awaiting live browser walkthrough.

---

## 1. What Was Fixed (Session 2026-05-27)

### Files Modified
| File | Changes |
|------|---------|
| `backend/agent/agent_kernel.py` | API provider branch in `infer()` (Cohere SDK + OpenAI-compat), agentic loop error handling, context window registry + `resolve_context_window()`, `_sync_context_window()`, swarm peer propagation fix (`_api_key`, `_api_base_url`, `_lmstudio_endpoint`) |
| `backend/iris_gateway.py` | `inference_mode` confirm_card guard (no more provider clobber), `memory` section handler for context_window override |
| `backend/memory/config.py` | `update_context_size()` for dynamic memory budget |
| `data/cards.ts` | Context window slider (min=1, max=128, "K tokens") |
| `.env` | Picovoice access key, HF token, wake word model |
| `.gitignore` | Added `.env` to prevent credential leaks |

### Test Results (Automated)
| Suite | Result |
|-------|--------|
| Kernel context window (15 tests) | 15/15 PASS |
| Provider switching (4 tests) | 4/4 PASS |
| E2E pipeline (personal mode) | PASS |
| E2E pipeline (developer mode) | PASS |
| DarkGlassDashboard no-clobber | PASS |
| Error messages (auth, rate limit) | PASS |
| Memory config sync | PASS |

---

## 2. Startup Checklist

### Backend
```bash
python start-backend.py
```
- [ ] Health endpoint responds: `curl http://localhost:8000/health`
- [ ] Mode endpoint responds: `curl http://localhost:8000/api/mode`
- [ ] Backend logs show no errors: `tail -50 backend/logs/irisvoice.log`
- [ ] Porcupine initialized: logs show `[PORCUPINE] Initialized with wake word config`
- [ ] Hey Iris wake word loaded: logs show `Auto-configured: 'Hey Iris' → models\wake_words\hey-iris_en_windows_v4_0_0.ppn`
- [ ] Audio engine started: logs show `[AUDIO ENGINE] Started successfully`

### Frontend
```bash
npm run dev
```
- [ ] Frontend responds: `curl http://localhost:3000 -o /dev/null -w "%{http_code}"` → 200
- [ ] WebSocket connects (browser console: no connection errors)

### Chrome (for MCP browser tools)
```bash
# Start Chrome with CDP debugging for Playwright
"C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 http://localhost:3000
```
- [ ] Browser MCP extension connected (click extension icon → Connect)
- [ ] OR Playwright MCP server running (`npx @playwright/mcp@latest`)

---

## 3. Provider Configuration Checklist (via UI)

### 3A. Configure Cohere API (Dashboard)
1. [ ] Open `http://localhost:3000`
2. [ ] Navigate to **Agent → Model Selection** card
3. [ ] Set Provider to **"api"**
4. [ ] Set API Base URL to `https://api.cohere.com/compatibility/v1`
5. [ ] Enter your Cohere API key
6. [ ] Set Reasoning Model to `command-r-plus`
7. [ ] Set Tool Execution Model to `command-r-plus`
8. [ ] Click **APPLY** (or confirm the card in WheelView)
9. [ ] Verify backend logs show: `Model selection updated: provider=cohere, context_window=128000`

### 3B. Verify No Clobber (DarkGlassDashboard)
1. [ ] After APPLY, check backend logs for `inference_mode card confirmed (no legacy mode field — provider routing delegated to model_selection section)`
2. [ ] This confirms the inference_mode handler did NOT override the provider to lmstudio

### 3C. Verify Context Window
1. [ ] Navigate to **Memory** section
2. [ ] Slide Context Window slider to desired value (e.g. 32 = 32K tokens)
3. [ ] Click APPLY
4. [ ] Verify backend logs show: `Memory context_window override → 32000 tokens`

### 3D. Switch Provider (mid-session test)
1. [ ] Switch to LM Studio: Provider → "lmstudio", Endpoint → `http://localhost:1234`
2. [ ] Click APPLY → verify logs: `OpenAI-compatible endpoint configured`
3. [ ] Switch back to Cohere → verify logs show correct context_window

---

## 4. Chat Pipeline Checklist

### 4A. Basic Message Flow
1. [ ] Type "Hello" in the chat → hit Enter
2. [ ] Response appears in the UI (even if error message due to test API key)
3. [ ] Backend logs show: `process_text_message` called
4. [ ] No crashes or silent failures

### 4B. Tool-Triggering Message
1. [ ] Type "What tools do you have available?" → hit Enter
2. [ ] Response lists tools or attempts tool execution
3. [ ] Backend logs show `_needs_planning()` triggered DER path

### 4C. Error Handling
1. [ ] If using test API key → response should show: `IRIS couldn't authenticate with the API. Check your API key in the agents card.`
2. [ ] Should NOT show: raw Python traceback, empty response, or infinite hang

### 4D. Streaming
1. [ ] Response chunks arrive incrementally (not all at once)
2. [ ] UI shows typing/streaming indicator during response
3. [ ] No dropped chunks mid-response

---

## 5. Mode Persistence Checklist

### 5A. Personal Mode
1. [ ] Switch to personal mode: `curl -X POST http://localhost:8000/api/mode -H "Content-Type: application/json" -d '{"mode":"personal"}'`
2. [ ] Run a chat message → verify response
3. [ ] Backend logs show correct mode

### 5B. Developer Mode
1. [ ] Switch to developer mode: `curl -X POST http://localhost:8000/api/mode -H "Content-Type: application/json" -d '{"mode":"developer"}'`
2. [ ] Run a chat message → verify response
3. [ ] Verify additional features visible (DCP Stats in Monitor tab, DER loop active)
4. [ ] Backend logs show `inference_event` messages (developer-only)

### 5C. Provider Persists Across Modes
1. [ ] Configure Cohere in personal mode
2. [ ] Switch to developer mode
3. [ ] Send a message → should still use Cohere (check logs for API provider path)

---

## 6. Caducean Governor + DER Loop + Pacman + MCM Benchmarks

These benchmarks measure the agent's reasoning architecture under live inference. Run through the UI chat interface.

### Architecture Quick Reference
- **DER Loop** (Director → Explorer → Reviewer): Structured execution brain. Director plans steps, Explorer executes, Reviewer scores.
- **Caducean Governor**: Phase-angle modulator (ξ). Controls exploration vs exploitation. 4 phases: explore, converge, crystallize, rest.
- **Pacman**: Context metabolism. Breaks content into coordinate signals, accumulates in graph, metabolizes for cheaper context over time.
- **MCM Orchestrator**: Memory routing layer. Routes memory operations through the coordinate database.

### How to Observe Each System

| System | Where to Observe |
|--------|-----------------|
| DER Loop | Backend logs: `[DER]`, `[Director]`, `[Reviewer]`, `[Explorer]` |
| Caducean | Backend logs: `xi=`, `phase=`, `caducean` |
| Pacman | Backend logs: `[Pacman]`, `fragment_and_store`, `episodic` |
| MCM Orchestrator | Backend logs: `[MCM]`, `mcm_orch`, `post_turn` |
| infer() path | Backend logs: `[AgentKernel.infer]` — shows which provider branch was hit |

### Benchmark Prompts (20 rounds)

**Round 1 — File Tool**
```
What files are in my project?
```
- [ ] Response lists files from the workspace
- [ ] Backend shows tool call (file listing)
- [ ] DER loop engaged (check for Director/Reviewer logs)

**Round 2 — Web Tool**
```
Search the web for Python async best practices
```
- [ ] Web search tool called
- [ ] Response contains real search results
- [ ] Latency: time-to-first-token < 2s

**Round 3 — File + Reasoning**
```
Read the README and summarize it
```
- [ ] File read tool called
- [ ] Summary is accurate and concise

**Round 4 — Multi-step Reasoning**
```
Find a bug in this code: def fib(n): return n if n < 2 else fib(n-1) + fib(n-2)
```
- [ ] Agent identifies inefficiency (exponential recursion)
- [ ] Suggests memoization or iteration

**Round 5 — Memory Store**
```
Remember that my favorite color is blue
```
- [ ] Memory store tool called
- [ ] Backend logs show memory write to coordinate database

**Round 6 — Memory Recall**
```
What did I ask you to remember?
```
- [ ] Memory recall tool called
- [ ] Response mentions "favorite color is blue"
- [ ] Backend logs show memory read from coordinate database

**Round 7 — File Write**
```
Create a file called temp_notes.txt with the text "benchmark test"
```
- [ ] File write tool called
- [ ] File exists on disk after response

**Round 8 — Shell Tool**
```
What is the current git branch?
```
- [ ] Shell/git tool called
- [ ] Response shows current branch name

**Round 9 — Complex Shell**
```
How many Python files are in the backend directory?
```
- [ ] Counting tool or shell command executed
- [ ] Response shows correct count

**Round 10 — Introspection**
```
What tools do you have available? List them all.
```
- [ ] Agent lists its available tools
- [ ] Response is accurate

**Round 11 — Multi-step Debug**
```
The backend health endpoint is returning 500. Walk me through how to debug this.
```
- [ ] Multi-step reasoning in response
- [ ] Mentions checking logs, verifying services, checking ports

**Round 12 — Code Generation**
```
Write a Python function to calculate fibonacci numbers efficiently
```
- [ ] Code is correct and efficient (memoized or iterative)
- [ ] Includes docstring

**Round 13 — File + Code**
```
Save that function to backend/utils/fib.py
```
- [ ] File write tool called
- [ ] File exists with correct content

**Round 14 — Caducean Introspection**
```
What phase is the Caducean governor in right now? What is the current xi value?
```
- [ ] Agent reports phase (explore/converge/crystallize/rest)
- [ ] Agent reports xi value or admits it's not directly accessible

**Round 15 — Memory Trajectory**
```
Show me my recent memory trajectory. What patterns have you learned about me?
```
- [ ] Memory query tool called
- [ ] Response references stored preferences or past interactions

**Round 16 — Auto Research**
```
Research how to improve the DER loop for faster tool execution
```
- [ ] Web search or internal analysis triggered
- [ ] Response contains actionable suggestions

**Round 17 — Session Summary**
```
Summarize everything we've done in this session
```
- [ ] References multiple earlier interactions
- [ ] Accurate summary of actions taken

**Round 18 — Context Window Test (large input)**
```
Here is a long piece of text to test context handling: [paste ~2000 words of text]. What are the key points?
```
- [ ] Agent correctly summarizes the long input
- [ ] No truncation or hallucination

**Round 19 — Tool Chaining**
```
Read the file backend/agent/agent_kernel.py, find the infer() method, and explain what it does
```
- [ ] File read + analysis combined
- [ ] Accurate description of infer() and its provider branches

**Round 20 — Stress Test**
```
List all Python files in the project, count their total lines, and tell me which file is the longest
```
- [ ] Multiple tool calls chained
- [ ] Correct file count and line count

### Benchmark Scoring Table

| Round | Prompt Summary | TTFT (s) | E2E (s) | Tools Used | Caducean Phase | DER Active | Score (1-5) |
|-------|---------------|----------|---------|------------|----------------|------------|-------------|
| 1 | File listing | | | | | | |
| 2 | Web search | | | | | | |
| 3 | Read + summarize | | | | | | |
| 4 | Find bug | | | | | | |
| 5 | Memory store | | | | | | |
| 6 | Memory recall | | | | | | |
| 7 | File write | | | | | | |
| 8 | Git status | | | | | | |
| 9 | File count | | | | | | |
| 10 | Tool introspection | | | | | | |
| 11 | Multi-step debug | | | | | | |
| 12 | Code generation | | | | | | |
| 13 | File + code | | | | | | |
| 14 | Caducean phase | | | | | | |
| 15 | Memory trajectory | | | | | | |
| 16 | Auto research | | | | | | |
| 17 | Session summary | | | | | | |
| 18 | Long context | | | | | | |
| 19 | Tool chaining | | | | | | |
| 20 | Stress test | | | | | | |

### Scoring Criteria (1-5)
- **5**: Perfect — correct tool, fast response, accurate output
- **4**: Good — minor issues, tool worked, response mostly accurate
- **3**: Acceptable — tool called but partial results or slow
- **2**: Poor — wrong tool, incomplete response, or significant delay
- **1**: Failed — no response, crash, or completely wrong

### Targets
| Metric | Target |
|--------|--------|
| Average score | ≥ 3.5 |
| TTFT p95 | < 2s |
| E2E p95 | < 5s |
| DER loop active (Rounds 1-20) | ≥ 15/20 |
| Caducean phases observed | ≥ 3 of 4 |
| Memory store/recall working | Rounds 5 + 6 pass |
| Tool calls successful | ≥ 90% of attempts |

---

## 7. Post-Benchmark Metrics Collection

### Backend Logs
```bash
# Inference timing
grep -i "infer\|latency\|time" backend/logs/irisvoice.log | tail -50

# Tool calls
grep -i "tool\|execute_tool\|tool_bridge" backend/logs/irisvoice.log | tail -50

# DER loop
grep -i "DER\|Director\|Reviewer\|Explorer" backend/logs/irisvoice.log | tail -50

# Caducean
grep -i "caducean\|xi=\|phase=" backend/logs/irisvoice.log | tail -50

# Pacman
grep -i "Pacman\|fragment\|episodic\|metabol" backend/logs/irisvoice.log | tail -50

# MCM
grep -i "MCM\|mcm_orch\|post_turn" backend/logs/irisvoice.log | tail -50

# Memory
grep -i "memory\|recall\|store\|coordinate" backend/logs/irisvoice.log | tail -50

# Context window
grep -i "context_window\|token_budget\|resolve_context" backend/logs/irisvoice.log | tail -50
```

### SQLite Queries
```sql
-- Trajectory DB writes during benchmark
SELECT COUNT(*) FROM trajectories WHERE timestamp > '{benchmark_start}';

-- Coordinate DB activity
SELECT COUNT(*) FROM events WHERE timestamp > '{benchmark_start}';

-- Memory entries
SELECT COUNT(*) FROM memories WHERE created_at > '{benchmark_start}';

-- Caducean trajectories
SELECT * FROM caducean_trajectories ORDER BY timestamp DESC LIMIT 20;
```

---

## 8. Known Issues / Notes

### Fixed This Session
- `infer()` now has API provider branch — DER loop works with Cohere/OpenAI/Groq
- `inference_mode` confirm_card no longer clobbers provider
- Context window auto-detects from model registry
- Swarm peer propagation includes API credentials
- Error messages surface friendly text instead of raw exceptions
- `.env` added to `.gitignore`

### Deferred
- IRIS Local full E2E (needs llama-cpp-python server running on port 8082)
- Frontend slider dynamic max (context_window slider max should match model's context window)
- Wake word model works but `models/wake_words/` directory needed to be created at project root
- Orbit/state_manager "No active category" error on confirm_card is cosmetic — kernel config IS applied

### Backend Running State
- Backend: port 8000, health OK, Picovoice + Hey Iris loaded
- Frontend: port 3000, Next.js dev server
- Chrome: `--remote-debugging-port=9222`
