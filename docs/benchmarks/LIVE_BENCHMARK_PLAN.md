# Live Benchmark Plan — Domain 19 Caducean DER Governor

## Objective
Measure real-world agent performance with the Domain 19 integration active: memory usage, latency, tool selection quality, and Caducean phase modulation under live inference — through the **actual IRIS frontend UI**.

## Prerequisites (You Provide)
- **API key** — for remote inference backend (configured via the IRIS frontend UI settings, never hardcoded)
- **Base URL** — OpenAI-compatible endpoint (e.g., `https://api.cohere.com/compatibility/v1`)
- **Model name** — which model to benchmark against (e.g., `command-a-03-2025`)

## What We Will Measure

| Metric | Target | How |
|--------|--------|-----|
| Response latency (time-to-first-token) | <2s p95 | Browser console timestamp diff |
| End-to-end response time | <5s p95 | Total round-trip via UI |
| Memory growth per session | <50 MB | Backend log analysis |
| Tool call accuracy | >90% | Manual review of UI responses |
| Caducean phase transitions | 4 phases hit | ξ readout logging |
| EML state injection | Visible in system prompt | Prompt audit log |
| recall_memory usage | ≥1 call per 5 prompts | Tool bridge audit |
| Trajectory DB writes | 1 per DER step | SQLite row count |
| C++ Caducean latency | <1μs | In-app microbenchmark |

## Test Prompts (20-round benchmark suite)

```
Round  1: "What files are in my project?"                      → file tool
Round  2: "Search the web for Python async best practices"     → web tool
Round  3: "Read the README and summarize it"                   → file + reasoning
Round  4: "Find a bug in this code" (injected snippet)          → reasoning + file
Round  5: "Remember that I prefer dark mode"                     → memory store
Round  6: "What did I ask you to remember?"                    → memory recall
Round  7: "Create a todo list for my project"                    → file write
Round  8: "Check my git status"                                → git tool
Round  9: "Run pytest on the backend"                          → shell tool
Round 10: "Take a screenshot and describe it"                  → vision tool
Round 11: "Open Chrome and search for IRISVOICE"               → browser + web
Round 12: "What tools do you have available?"                  → introspection
Round 13: "Help me debug why the backend won't start"          → multi-step reasoning
Round 14: "List all test files and tell me which are slow"     → file + analysis
Round 15: "Write a Python function to calculate fibonacci"     → code generation
Round 16: "Save that function to backend/utils/fib.py"          → file write
Round 17: "What phase is the Caducean governor in right now?"  → introspection
Round 18: "Show me my recent memory trajectory"                → memory query
Round 19: "Research how to improve the DER loop"              → auto_research trigger
Round 20: "Summarize everything we've done in this session"    → memory + reasoning
```

## Workflow

This benchmark is performed entirely through the IRIS frontend UI using browser automation.

### 1. Backend Launch
```bash
python start-backend.py
```
- Backend starts **without** any hardcoded API credentials
- API key + endpoint are configured **on demand** via the IRIS settings UI

### 2. Frontend Launch
```bash
npm run dev        # Next.js dev server (hot reload)
# or
npm run start:prod # production build, lighter than dev
```

### 3. Configure Inference via UI (browser)
1. Open `http://localhost:3000` in Chrome (via MCP DevTools)
2. Navigate to **Settings → Agent → Model Selection** card
3. Set Provider to **"api"**
4. Enter the API key and base URL
5. Select model name
6. Confirm the card
7. Return to chat view

### 4. Run Benchmark Suite
For each of the 20 prompts:
1. Type the prompt into the chat input
2. Hit Enter / send
3. Measure the time-to-first-token (first chunk response) and end-to-end time
4. Note the response quality and any tool calls made
5. Record the results in the benchmark table

### 5. Collect Runtime Metrics
- **Backend logs**: `backend/logs/` — capture inference timing, tool calls, memory
- **Network tab**: Browser DevTools — capture WebSocket round-trip timing
- **Console logs**: Browser DevTools `console.log` output from IRIS

### Metrics Collection

| Metric | Collection Method |
|--------|------------------|
| Time-to-first-token | Browser DevTools Network tab (WS message timestamps) |
| End-to-end latency | Browser DevTools Network tab (send → final response) |
| Tool calls made | Visible in the chat response UI |
| Memory usage | `backend/logs/` — tracemalloc or RSS snapshots |
| Caducean phase | System prompt introspection (Round 17) |
| Trajectory writes | SQLite query on `data/caducean_trajectories.db` |

### Final Report
After 20 rounds, compile:
1. **Latency histogram** (p50, p95, p99 from browser network capture)
2. **Phase distribution** (how many rounds spent in each quadrant)
3. **Tool usage matrix** (which tools fired when)
4. **Memory profile** (peak, leak rate)
5. **Trajectory table size** (rows written during benchmark)
6. **Qualitative observations** (response quality, errors, edge cases)

## Safety Guardrails
- No API keys or credentials are hardcoded in any file
- All configuration happens through the IRIS frontend UI
- Shell commands run in the IRIS project directory (sandboxed)
- Screenshots saved to `benchmarks/output/` for audit trail

## Next Step
1. Start the backend and frontend
2. Open Chrome browser to `http://localhost:3000`
3. Navigate the IRIS UI to configure the Cohere API
4. Run the 20-round suite through the chat interface
5. Compile the final report
