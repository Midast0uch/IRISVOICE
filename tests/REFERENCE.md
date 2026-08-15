# Top-Level Tests — Reference Index

> E2E, bugfix regression, frontend, and benchmark tests.

## Run All Top-Level Tests

```bash
python -m pytest tests/ -v
```

## Test Directories

| Directory | Purpose | Run Command |
|-----------|---------|-------------|
| `bugfix/` | Bugfix regression tests — run after any code change | `pytest tests/bugfix/ -v` |
| `agent/` | Agent-level E2E tests | `pytest tests/agent/ -v` |
| `components/` | Frontend component tests | `npm test tests/components/` |
| `contexts/` | Frontend context tests | `npm test tests/contexts/` |
| `benchmark/` | Performance benchmarks | _empty — awaiting benchmarks_ |

## Individual Test Files

### Bugfix Regression (`bugfix/`)

| File | Covers | Run Command |
|------|--------|-------------|
| `test_websocket_integration.py` | WebSocket chat path — MUST pass after any backend change | `pytest tests/bugfix/test_websocket_integration.py -v` |
| `test_error_recovery.py` | Error recovery scenarios | `pytest tests/bugfix/test_error_recovery.py -v` |
| Other `*.py` | Various bugfix regression tests | `pytest tests/bugfix/ -v` |

### E2E Tests (`agent/`)

| File | Covers |
|------|--------|
| `test_autoresearch_integration.py` | Auto-research pipeline |
| `test_load_autoresearch.py` | Load testing auto-research |

## Notes

- Bugfix tests (`tests/bugfix/`) are the highest-priority regression suite. Run them before any commit.
- Frontend tests (`components/`, `contexts/`) require Node.js. Run with `npm test`.
- Benchmark directory is empty — populated by `--benchmark` runs.
