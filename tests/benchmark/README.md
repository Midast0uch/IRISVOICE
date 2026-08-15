# IRIS UI Benchmark Harness

## Prerequisites

```bash
npm install
npx playwright install chromium
```

## Provider Setup

Before benchmarking, configure the backend to use the provider you want to test.

### Local Model (LM Studio / llama.cpp)
1. Open IRIS Settings → Configure → Models
2. Set provider to `LM Studio` and point to `http://localhost:1234`
3. Select your loaded model (e.g. `LFM2-8B`)
4. Run: `npm run benchmark:local`

### Chutes AI (API)
1. Copy `.env.benchmark.example` to `.env.benchmark`
2. Fill in your Chutes API key from https://chutes.ai/
3. Configure IRIS Settings → Models → Provider: `API`
4. Set Base URL: `https://api.chutes.ai/v1`
5. Set Model: `chutes-ai/llama-3.3-70b` (or your preferred Chutes model)
6. Paste your API key
7. Run: `npm run benchmark:api`

**Security**: `.env.benchmark` and `backend/sessions/` are in `.gitignore`. Never commit API keys.

## Running

```bash
# Default (uses whatever provider IRIS is currently configured for)
npm run benchmark

# Local model only
npm run benchmark:local

# API provider only
npm run benchmark:api

# Watch the browser (headed mode)
npm run benchmark:headed

# Custom URL
IRIS_BENCHMARK_URL=http://your-iris-instance:3000 npx playwright test tests/benchmark
```

## What it measures

| Metric | Definition |
|--------|------------|
| **TTFT** | Time from pressing Enter to first assistant content appearing in DOM |
| **E2E** | Time from pressing Enter to typing indicator disappearing (response complete) |

Results are appended to `test-results/benchmark-latency.jsonl` (one JSON line per run). The model name and tokens/sec are captured from the backend `inference_event` broadcast.

## Tests

- `baseline latency with simple prompts` — 3 standard prompts, logs averages
- `streaming stability — rapid consecutive sends` — 3 rapid-fire prompts, asserts all succeed

## Integration with [LAYERS] backend observability

The benchmark DOM measurements (TTFT/E2E) can be cross-referenced with the backend `[LAYERS]` log line emitted by `agent_kernel.py` per turn. Look for matching `turn_id` in the backend logs.
