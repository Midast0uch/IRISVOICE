"""Contract: access control on the in-app browser surface.

Closes the unauthenticated-endpoint finding (pin_160522ab3740). Both gates —
address AND token — must be independently load-bearing, so each test below
removes exactly one and asserts the request is still refused.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import browser_auth as ba
from backend.api.browser_surface import router


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("IRIS_BROWSER_SURFACE_TOKEN", "test-token-abc")
    ba.reset_token_cache_for_tests()
    app = FastAPI()
    app.include_router(router)
    # Starlette's default peer is the literal string "testclient", which the
    # address gate correctly refuses (an unparseable peer is not loopback).
    # Present a real loopback address so these tests isolate the TOKEN gate.
    yield TestClient(app, client=("127.0.0.1", 50000))
    ba.reset_token_cache_for_tests()


# FIXTURE INPUT CHANGED — CALLED OUT EXPLICITLY; no assertion is touched and the
# load is unchanged. This was "/api/browser/capture/job-1/1". The two token-gate
# tests below require a capture that DOES NOT EXIST (their own docstring says so)
# so that reaching the handler is provable by the 'unavailable' marker. But
# "job-1" is a plausible id that other suites and manual runs also use, and the
# capture store is a SHARED PERSISTENT directory (data/captures/<job>/<n>.html).
# Once anything wrote data/captures/job-1/1.html — one existed from 2026-08-11
# 17:28 — the handler answered 'available' and both tests failed while the
# property they exist to prove (a correct token passes the gate and reaches the
# handler) was in fact still holding. A sentinel id no crawl or fixture will ever
# mint makes the precondition true by construction instead of by luck.
CAPTURE = "/api/browser/capture/job-nonexistent-auth-fixture/1"
PROXY = "/api/browser/proxy?url=https://example.com"


# ── The token gate ────────────────────────────────────────────────────────

@pytest.mark.parametrize("path", [CAPTURE, PROXY])
def test_no_token_is_refused(client, path):
    """TestClient presents 127.0.0.1, so the address gate passes — this
    isolates the TOKEN gate."""
    assert client.get(path).status_code == 404


@pytest.mark.parametrize("path", [CAPTURE, PROXY])
def test_wrong_token_is_refused(client, path):
    r = client.get(path, headers={ba.HEADER_NAME: "not-the-token"})
    assert r.status_code == 404


def test_correct_token_passes_the_gate(client):
    """A capture that does not exist should reach the handler and 404 as
    'unavailable' — distinguishable from the auth refusal by its marker."""
    r = client.get(CAPTURE, headers={ba.HEADER_NAME: "test-token-abc"})
    assert r.headers.get("X-Capture-Status") == "unavailable"


def test_cookie_is_accepted_because_an_iframe_cannot_set_headers(client):
    client.cookies.set(ba.COOKIE_NAME, "test-token-abc")
    r = client.get(CAPTURE)
    assert r.headers.get("X-Capture-Status") == "unavailable"


# ── The address gate ──────────────────────────────────────────────────────

@pytest.mark.parametrize("host,allowed", [
    ("127.0.0.1", True),
    ("::1", True),
    ("100.117.236.6", True),    # tailnet CGNAT
    ("100.64.0.1", True),
    ("fd7a:115c:a1e0::1", True),
    ("192.168.1.50", False),    # ordinary LAN peer
    ("10.0.0.5", False),
    ("172.16.0.9", False),
    ("8.8.8.8", False),
    ("100.63.255.255", False),  # just below the CGNAT range
    ("100.128.0.1", False),     # just above it
])
def test_address_gate(host, allowed):
    class _Req:
        client = type("C", (), {"host": host})()
    assert ba.client_address_allowed(_Req()) is allowed


def test_forwarded_headers_cannot_forge_a_tailnet_address(client):
    """X-Forwarded-For is attacker-controlled; trusting it would let any LAN
    peer claim to be on the tailnet."""
    class _Req:
        client = type("C", (), {"host": "192.168.1.50"})()
        headers = {"X-Forwarded-For": "100.64.0.1", "X-Real-IP": "100.64.0.1"}
        cookies: dict = {}
    assert ba.client_address_allowed(_Req()) is False


def test_missing_client_is_refused_not_allowed():
    class _Req:
        client = None
    assert ba.client_address_allowed(_Req()) is False


# ── Session bootstrap ─────────────────────────────────────────────────────

def test_session_sets_an_httponly_cookie_and_never_leaks_the_token_in_the_body(client):
    r = client.post("/api/browser/session")
    assert r.status_code == 200
    assert "test-token-abc" not in r.text, "token must never appear in a response body"
    raw = r.headers.get("set-cookie", "")
    assert ba.COOKIE_NAME in raw
    assert "HttpOnly" in raw, "page script in the frame must not be able to read it"
    assert "strict" in raw.lower()


# ── Key separation ────────────────────────────────────────────────────────

def test_surface_token_is_not_the_memory_key(monkeypatch):
    """Deriving both from the identity key with the SAME info string would mean
    a leaked surface token equals a memory-DB key."""
    monkeypatch.delenv("IRIS_BROWSER_SURFACE_TOKEN", raising=False)
    ba.reset_token_cache_for_tests()
    priv = b"\x11" * 64
    monkeypatch.setattr(
        "backend.core.biometric.load_dilithium_private_key", lambda: priv,
    )
    surface = ba._derive_token()

    from backend.core.biometric import derive_memory_key_from_dilithium

    memory_key = derive_memory_key_from_dilithium(priv).hex()
    assert surface != memory_key
    ba.reset_token_cache_for_tests()


def test_dev_fallback_token_is_random_not_a_constant(monkeypatch):
    """A shipped default would look like auth while authenticating nothing."""
    monkeypatch.delenv("IRIS_BROWSER_SURFACE_TOKEN", raising=False)
    monkeypatch.setattr(
        "backend.core.biometric.load_dilithium_private_key", lambda: None,
    )
    ba.reset_token_cache_for_tests()
    first = ba._derive_token()
    ba.reset_token_cache_for_tests()
    second = ba._derive_token()
    assert first != second, "fallback token must not be a fixed constant"
    assert len(first) >= 32
    ba.reset_token_cache_for_tests()


def test_token_comparison_is_constant_time():
    import inspect

    src = inspect.getsource(ba.token_valid)
    assert "compare_digest" in src, "a plain == leaks the shared prefix by timing"
