# Backend Tests — Reference Index

> Each file listed with the production code it covers and how to run it.

## Run All Backend Tests

```bash
python -m pytest backend/tests/ -v
```

## Individual Test Files

### Core System

| File | Covers | Run Command |
|------|--------|-------------|
| `test_iris_core_smoke.py` | `backend/gateway/iris_core` (C++ hybrid core) | `pytest backend/tests/test_iris_core_smoke.py -v` |
| `test_agent_loop_upgrade.py` | Backend agent loop | `pytest backend/tests/test_agent_loop_upgrade.py -v` |
| `test_ask_user_tool.py` | Ask-user tool | `pytest backend/tests/test_ask_user_tool.py -v` |

### Chat REST API — NEW (this session)

| File | Covers | Run Command |
|------|--------|-------------|
| `test_chat_models.py` | `backend/api/chat.py` — Pydantic models, thread ID generation, input validation | `pytest backend/tests/test_chat_models.py -v` |
| `test_chat_handler.py` | `backend/api/chat.py` — FastAPI endpoints (TestClient), thread CRUD, fork, error handling | `pytest backend/tests/test_chat_handler.py -v` |
| `test_chat_persistence.py` | `backend/conversation_store.py` — SQLite persistence, restart survival, CRUD | `pytest backend/tests/test_chat_persistence.py -v` |
| `test_chat_immortus.py` | `backend/gateway/iris_ffi.py` — Immortus FFI graceful degradation, chain_append | `pytest backend/tests/test_chat_immortus.py -v` |
| `test_chat_e2e.py` | Full lifecycle: thread create → list → fork → delete | `pytest backend/tests/test_chat_e2e.py -v` |

**All chat tests together:**
```bash
pytest backend/tests/test_chat_models.py backend/tests/test_chat_handler.py backend/tests/test_chat_persistence.py backend/tests/test_chat_immortus.py backend/tests/test_chat_e2e.py -v
```
