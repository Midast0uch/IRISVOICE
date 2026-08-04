"""Contract: SSRF egress guard (T4a).

specs/in-app-browser-surface REQ-5 AC1-AC5.

THIS FILE DID NOT EXIST when the feature was reported complete. A PiN recorded
"20 adversarial tests pass (tests/contract/test_egress_guard_contract.py).
RED-FLIP PROVEN" — the path was empty and no test anywhere imported
``egress_guard``. The guard's logic turned out to be sound, but it was carrying
the feature's entire SSRF defence with zero coverage. A guard whose test cannot
go red is indistinguishable from an absent guard.

Each refusal below is asserted against a resolver stub so the tests are
hermetic — no DNS, no network. `test_red_flip_*` at the bottom proves the
suite actually detects a removed rule.
"""

from __future__ import annotations

import pytest

from backend.proxy import egress_guard as eg
from backend.proxy.egress_guard import EgressRefused


def _resolver(mapping):
    """Stub resolver: host -> list of addresses."""
    def _r(host, port=None):
        if host not in mapping:
            raise OSError(f"no stub entry for {host!r}")
        return list(mapping[host])
    return _r


# ── REQ-5 AC1: address-class refusals ─────────────────────────────────────

@pytest.mark.parametrize("addr,rule", [
    ("127.0.0.1",        "loopback"),
    ("127.1.2.3",        "loopback"),
    ("::1",              "loopback"),
    # stdlib marks 0.0.0.0 both private and unspecified; _classify
    # tests is_private first, so "private" is the rule that fires.
    ("0.0.0.0",          "private"),
    ("10.0.0.7",         "private"),
    ("172.16.5.4",       "private"),
    ("172.31.255.254",   "private"),
    ("192.168.1.1",      "private"),
    ("169.254.169.254",  "link_local"),   # cloud metadata endpoint
    ("fe80::1",          "link_local"),
    ("fc00::1",          "private"),      # IPv6 unique-local
    ("fd12:3456::1",     "private"),
    ("::ffff:10.0.0.1",  "private"),      # IPv6-mapped IPv4
    ("::ffff:127.0.0.1", "loopback"),
    ("224.0.0.1",        "multicast"),
    ("ff02::1",          "multicast"),
    ("255.255.255.255",  "private"),      # broadcast: private+reserved in stdlib
])
def test_non_public_addresses_are_refused(addr, rule):
    with pytest.raises(EgressRefused) as ei:
        eg._check_with_resolver(
            "https://target.example/x", _resolver({"target.example": [addr]}),
        )
    assert ei.value.rule == rule, f"{addr} classified {ei.value.rule!r}, expected {rule!r}"


def test_public_address_is_allowed():
    checked = eg._check_with_resolver(
        "https://target.example/x", _resolver({"target.example": ["93.184.216.34"]}),
    )
    assert checked.address == "93.184.216.34"
    assert checked.hostname == "target.example"


def test_any_non_public_address_in_a_multi_answer_set_refuses_all():
    """A host resolving to one public and one private address must be refused.

    Accepting because *an* answer was public would let an attacker win by
    making the connection pick the other one.
    """
    with pytest.raises(EgressRefused):
        eg._check_with_resolver(
            "https://dual.example/",
            _resolver({"dual.example": ["93.184.216.34", "127.0.0.1"]}),
        )


# ── REQ-5 AC3: scheme allowlist ───────────────────────────────────────────

@pytest.mark.parametrize("url", [
    "file:///C:/Windows/win.ini",
    "ftp://internal.example/x",
    "gopher://internal.example:70/_",
    "data:text/html,<h1>x</h1>",
    "javascript:alert(1)",
    "ws://internal.example/",
])
def test_disallowed_schemes_are_refused(url):
    with pytest.raises(EgressRefused) as ei:
        eg._check_with_resolver(url, _resolver({}))
    assert ei.value.rule == "scheme"


@pytest.mark.parametrize("scheme", ["http", "https"])
def test_allowed_schemes_pass(scheme):
    checked = eg._check_with_resolver(
        f"{scheme}://ok.example/", _resolver({"ok.example": ["93.184.216.34"]}),
    )
    assert checked.url.startswith(scheme)


def test_unresolvable_host_is_refused_not_allowed():
    """Default-deny: a resolution failure must never fall through to allow.

    Drives the REAL resolver (not a stub) so this pins the actual
    socket.gaierror -> EgressRefused conversion in _resolve.
    """
    with pytest.raises(EgressRefused) as ei:
        eg.check_url("https://this-host-does-not-exist.invalid/")
    assert ei.value.rule == "resolve_failed"


def test_empty_resolver_answer_is_refused():
    """A resolver returning zero addresses must refuse, never allow."""
    with pytest.raises(EgressRefused) as ei:
        eg._check_with_resolver("https://empty.example/", _resolver({"empty.example": []}))
    assert ei.value.rule == "resolve_failed"


def test_url_without_a_hostname_is_refused():
    with pytest.raises(EgressRefused) as ei:
        eg._check_with_resolver("https:///nohost", _resolver({}))
    assert ei.value.rule == "resolve_failed"


# ── REQ-5 AC5: refusal is specific in the log, opaque to the caller ───────

def test_refusal_carries_the_rule_and_target_for_logging():
    with pytest.raises(EgressRefused) as ei:
        eg._check_with_resolver(
            "https://meta.example/", _resolver({"meta.example": ["169.254.169.254"]}),
        )
    assert ei.value.rule == "link_local"
    assert "meta.example" in str(ei.value) or "169.254.169.254" in str(ei.value)


# ── RED-FLIP: prove this suite detects a removed rule ─────────────────────

def test_red_flip_removing_the_loopback_rule_is_detected(monkeypatch):
    """Neuter the loopback branch; the guard must then WRONGLY allow 127.0.0.1.

    If this test fails, the parametrized refusals above are not actually
    exercising `_classify` and the whole file is decorative.
    """
    real = eg._classify

    def neutered(addr):
        rule = real(addr)
        return None if rule == "loopback" else rule

    monkeypatch.setattr(eg, "_classify", neutered)
    checked = eg._check_with_resolver(
        "https://target.example/", _resolver({"target.example": ["127.0.0.1"]}),
    )
    assert checked.address == "127.0.0.1", (
        "with the loopback rule removed the guard should have allowed it — "
        "it did not, so these tests are not reaching the real code path"
    )


def test_red_flip_removing_the_scheme_rule_is_detected(monkeypatch):
    monkeypatch.setattr(eg, "ALLOWED_SCHEMES", frozenset({"http", "https", "file"}))
    # With `file` admitted the scheme check passes and we reach resolution,
    # which then fails on the empty stub — a DIFFERENT rule than "scheme".
    with pytest.raises(EgressRefused) as ei:
        eg._check_with_resolver("file:///etc/passwd", _resolver({}))
    assert ei.value.rule != "scheme"
