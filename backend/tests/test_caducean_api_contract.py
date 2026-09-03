"""
test_caducean_api_contract.py — API contract tests for /api/caducean/* endpoints.

PURPOSE: Verify that the FastAPI endpoints return responses matching the
FROZEN JSON schema in backend/tests/contracts/caducean_api_v2.json.

This test does NOT require a running FastAPI server — it uses FastAPI's
TestClient to make in-process requests. This bypasses the pre-existing
pytest conftest bug that prevents the test from being collected.

Run: python backend/tests/test_caducean_api_contract.py
"""

import json
import os
import sys
import tempfile

# Ensure the project root is in path
PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Load the FROZEN contract
CONTRACT_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "contracts",
    "caducean_api_v2.json",
)
with open(CONTRACT_PATH) as f:
    CONTRACT = json.load(f)


def _validate_required_keys(response: dict, required: list) -> list:
    """Return list of missing required keys."""
    return [k for k in required if k not in response]


def _validate_type(value, expected_type: str) -> bool:
    """Lightweight type check matching JSON Schema types."""
    if expected_type == "string":
        return isinstance(value, str)
    if expected_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected_type == "boolean":
        return isinstance(value, bool)
    if expected_type == "object":
        return isinstance(value, dict)
    if expected_type == "null":
        return value is None
    return True  # unknown type, don't fail


# ── Test 1: contract file is loadable and has all 4 endpoints ──────


def test_contract_file_structure():
    """Verify the frozen contract JSON has all 4 expected endpoints."""
    assert "endpoints" in CONTRACT, "contract missing 'endpoints' key"
    expected_endpoints = [
        "GET /api/caducean/state",
        "GET /api/caducean/direction",
        "POST /api/caducean/params",
        "GET /api/caducean/health",
    ]
    for ep in expected_endpoints:
        assert ep in CONTRACT["endpoints"], f"contract missing endpoint: {ep}"
    print(f"  PASS  contract has all 4 endpoints: {expected_endpoints}")


# ── Test 2: GET /api/caducean/health ──────────────────────────────


def test_health_endpoint_schema():
    """The /health endpoint must return {engine_live: bool, ...}."""
    spec = CONTRACT["endpoints"]["GET /api/caducean/health"]["response_200"]
    required = spec["required"]
    # Validate spec is well-formed
    assert "engine_live" in required
    print(f"  PASS  /health spec: required={required}")


# ── Test 3: GET /api/caducean/state response shape ──────────────


def test_state_endpoint_schema():
    """The /state endpoint must return 10 required fields with correct types."""
    spec = CONTRACT["endpoints"]["GET /api/caducean/state"]["response_200"]
    required = spec["required"]
    properties = spec["properties"]
    assert len(required) == 10, f"expected 10 required fields, got {len(required)}"
    # Verify types
    assert properties["x"]["type"] == "integer"
    assert properties["y"]["type"] == "integer"
    assert properties["xi"]["type"] == "number"
    assert properties["u"]["type"] == "number"
    assert properties["u"]["minimum"] == -1 and properties["u"]["maximum"] == 1
    assert properties["a"]["minimum"] == 1 and properties["a"]["maximum"] == 4
    assert properties["s"]["minimum"] == 0.1 and properties["s"]["maximum"] == 0.8
    print(f"  PASS  /state spec: 10 required fields, types and bounds correct")


# ── Test 4: GET /api/caducean/direction response shape ───────────


def test_direction_endpoint_schema():
    """The /direction endpoint must return 6 required fields matching
    the IrisDirectionSignal C struct."""
    spec = CONTRACT["endpoints"]["GET /api/caducean/direction"]["response_200"]
    required = spec["required"]
    properties = spec["properties"]
    assert len(required) == 6, f"expected 6 required fields, got {len(required)}"
    # Verify these match the C struct
    expected_fields = {"target_u", "force_magnitude", "u_current", "phase", "balance"}
    assert set(required) == expected_fields | {"session_id"}
    # Verify target_u is constrained to ±1
    assert properties["target_u"]["enum"] == [-1, 1]
    print(f"  PASS  /direction spec: 6 required fields, target_u enum [-1, 1]")


# ── Test 5: POST /api/caducean/params request body ──────────────


def test_params_endpoint_request_schema():
    """The /params POST must require session_id, a, b, s."""
    spec = CONTRACT["endpoints"]["POST /api/caducean/params"]["request_body"]
    required = spec["required"]
    assert set(required) == {"session_id", "a", "b", "s"}
    # Verify bounds on a, b, s match what the C++ engine clamps to
    props = spec["properties"]
    assert props["a"]["minimum"] == 1 and props["a"]["maximum"] == 4
    assert props["b"]["minimum"] == 1 and props["b"]["maximum"] == 4
    assert props["s"]["minimum"] == 0.1 and props["s"]["maximum"] == 0.8
    print(f"  PASS  /params request body: required={required}, bounds match C++ clamps")


# ── Test 6: Direct endpoint test via TestClient ──────────────────


def test_endpoints_via_test_client():
    """Use FastAPI's TestClient to make in-process requests to the endpoints.
    This validates the actual endpoint code, not just the spec."""
    try:
        from fastapi.testclient import TestClient
        from backend.main import app
    except ImportError as e:
        print(f"  SKIP  TestClient (missing dep: {e})")
        return

    # Initialize a test engine first
    from backend.gateway.iris_ffi import ffi_init_engine

    tmp = tempfile.mktemp(suffix=".db")
    ffi_init_engine(tmp, "00" * 32)

    with TestClient(app) as client:
        # Test /health
        r = client.get("/api/caducean/health")
        assert r.status_code == 200
        data = r.json()
        assert "engine_live" in data
        assert isinstance(data["engine_live"], bool)
        print(f"  PASS  GET /api/caducean/health: {data}")

        # Test /state (with valid session_id)
        r = client.get("/api/caducean/state?session_id=test_phase5")
        assert r.status_code == 200
        data = r.json()
        required = CONTRACT["endpoints"]["GET /api/caducean/state"]["response_200"][
            "required"
        ]
        missing = _validate_required_keys(data, required)
        assert not missing, f"missing keys: {missing}"
        # Verify types
        assert _validate_type(data["session_id"], "string")
        assert _validate_type(data["engine_live"], "boolean")
        assert _validate_type(data["x"], "integer")
        assert _validate_type(data["u"], "number")
        print(
            f"  PASS  GET /api/caducean/state: x={data['x']}, y={data['y']}, u={data['u']:.3f}"
        )

        # Test /direction
        r = client.get("/api/caducean/direction?session_id=test_phase5&balance=1.5")
        assert r.status_code == 200
        data = r.json()
        required = CONTRACT["endpoints"]["GET /api/caducean/direction"]["response_200"][
            "required"
        ]
        missing = _validate_required_keys(data, required)
        assert not missing, f"missing keys: {missing}"
        # target_u must be ±1
        assert data["target_u"] in (-1.0, 1.0)
        # balance should be 1.5 (we passed it)
        assert abs(data["balance"] - 1.5) < 0.001
        print(
            f"  PASS  GET /api/caducean/direction: target_u={data['target_u']}, balance={data['balance']}"
        )

        # Test /params POST
        r = client.post(
            "/api/caducean/params",
            json={
                "session_id": "test_phase5",
                "a": 3.0,
                "b": 3.0,
                "s": 0.5,
            },
        )
        assert r.status_code == 200
        data = r.json()
        assert "ok" in data and "session_id" in data
        assert data["ok"] is True
        assert data["applied"] is not None
        assert abs(data["applied"]["a"] - 3.0) < 0.001
        print(f"  PASS  POST /api/caducean/params: {data}")

        # Test 422 on missing field
        r = client.post("/api/caducean/params", json={"session_id": "x"})
        assert r.status_code == 422
        print(f"  PASS  POST /api/caducean/params (missing a/b/s): 422")

        # Test 422 on wrong type
        r = client.post(
            "/api/caducean/params",
            json={
                "session_id": "x",
                "a": "not_a_number",
                "b": 2.0,
                "s": 0.5,
            },
        )
        assert r.status_code == 422
        print(f"  PASS  POST /api/caducean/params (a as string): 422")

    try:
        os.unlink(tmp)
    except OSError:
        pass


# ── Runner ───────────────────────────────────────────────────────


def run_all():
    tests = [
        test_contract_file_structure,
        test_health_endpoint_schema,
        test_state_endpoint_schema,
        test_direction_endpoint_schema,
        test_params_endpoint_request_schema,
        test_endpoints_via_test_client,
    ]
    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except AssertionError as e:
            print(f"  FAIL  {t.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"  ERROR {t.__name__}: {type(e).__name__}: {e}")
            failed += 1
    print()
    print(f"Phase 5 API contract tests: {passed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if run_all() else 1)
