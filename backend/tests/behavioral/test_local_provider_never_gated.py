"""
Behavioral test: local/open-weight providers are never gated (T2.1 / D-9 / REQ-9).

Only ProviderKind.API is metered. LOCAL_OPENAI, OLLAMA, INPROCESS must return
an infinite ceiling (never gated) and must ignore 429 observations / request
recording. This is a behavioral property — the bug would be gating a local
model (which never emits 429 anyway) or attributing load to the wrong quota.
"""
from backend.agent.inference.provider import ProviderInstance, ProviderKind
from backend.agent.rate_meter import (
    get_rate_meter,
    metered,
    quota_key,
    reset_rate_meter_for_testing,
)


def _inst(kind, base="http://localhost:1234", key=""):
    return ProviderInstance(
        id="local1",
        label="Local1",
        kind=kind,
        api_base_url=base,
        api_key=key,
        model="m",
    )


def test_local_openai_unmetered():
    assert metered(_inst(ProviderKind.LOCAL_OPENAI)) is False


def test_ollama_unmetered():
    assert metered(_inst(ProviderKind.OLLAMA)) is False


def test_inprocess_unmetered():
    assert metered(_inst(ProviderKind.INPROCESS)) is False


def test_api_metered():
    assert metered(_inst(ProviderKind.API, base="https://api.x.com", key="k")) is True


def test_unmetered_never_gated():
    reset_rate_meter_for_testing()
    _m = get_rate_meter()
    _i = _inst(ProviderKind.LOCAL_OPENAI)
    _q = quota_key(_i)
    _m.ensure_window(_q, metered_flag=metered(_i))
    # Even after many 429s, an unmetered quota is never gated
    for _ in range(10):
        _m.observe_429(_q, retry_after=1.0)
    assert _m.get_ceiling(_q) == float("inf")
    # Recording requests on an unmetered quota is a no-op
    _m.record_request(_q, tokens=100, priority=0, estimated=True)
    assert _m.draw(_q)["requests"] == 0
