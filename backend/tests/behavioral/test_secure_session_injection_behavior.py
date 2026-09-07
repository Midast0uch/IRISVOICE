"""BT (vision-goal-directed-search T32 / REQ-12 AC12.1-12.3): secure
session injection + HAR sanitization.

Cookies come from the OS keyring (`iris_voice_sessions` / domain) into
`context.add_cookies` — never from prompts or logs — and every exported
HAR entry redacts `Cookie` / `Set-Cookie` / `Authorization` (and
siblings) to `[REDACTED]`. Drives the REAL `_inject_keyring_cookies`
(with a fake context + fake keyring module) and the REAL
`sanitize_har_entries`.
"""
from __future__ import annotations

import asyncio
import json
import sys

import pytest

from backend.crawler.crawler_engine import sanitize_har_entries
from backend.vision import browser_session as bs_mod


class _FakeContext:
    def __init__(self):
        self.cookies: list = []

    async def add_cookies(self, cookies):
        self.cookies.extend(cookies)


class _FakeKeyring:
    def __init__(self, payload: dict):
        self._payload = payload
        self.lookups: list = []

    def get_password(self, service, key):
        self.lookups.append((service, key))
        raw = self._payload.get(key)
        return json.dumps(raw) if raw is not None else None


@pytest.fixture()
def _keyring(monkeypatch):
    fake = _FakeKeyring(
        {"github.com": [{"name": "session", "value": "s3cr3t", "domain": ".github.com"}]}
    )
    monkeypatch.setitem(sys.modules, "keyring", fake)
    return fake


def test_keyring_cookies_injected_for_known_domain(_keyring):
    ctx = _FakeContext()
    n = asyncio.run(
        bs_mod._inject_keyring_cookies(ctx, "https://github.com/octo/repo", "job-key")
    )
    assert n == 1
    assert ctx.cookies and ctx.cookies[0]["name"] == "session"
    assert ("iris_voice_sessions", "github.com") in _keyring.lookups


def test_unknown_domain_falls_back_to_anonymous(_keyring):
    ctx = _FakeContext()
    n = asyncio.run(
        bs_mod._inject_keyring_cookies(ctx, "https://unknown.example/x", "job-anon")
    )
    assert n == 0
    assert ctx.cookies == []


def test_har_redacts_sensitive_headers_and_keeps_the_rest():
    entries = [
        {
            "url": "https://github.com/",
            "request_headers": {
                "Cookie": "session=s3cr3t",
                "Authorization": "Bearer abc",
                "User-Agent": "iris",
            },
            "response_headers": {"Set-Cookie": "id=1", "Content-Type": "text/html"},
        }
    ]
    clean = sanitize_har_entries(entries)
    req, res = clean[0]["request_headers"], clean[0]["response_headers"]
    assert req["Cookie"] == "[REDACTED]"
    assert req["Authorization"] == "[REDACTED]"
    assert req["User-Agent"] == "iris"
    assert res["Set-Cookie"] == "[REDACTED]"
    assert res["Content-Type"] == "text/html"
    # The caller's in-memory entries are never mutated (penalty scoring
    # reads the same dicts).
    assert entries[0]["request_headers"]["Cookie"] == "session=s3cr3t"
