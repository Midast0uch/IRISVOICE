"""
Unit tests for quota_key derivation (T2.5 / D-9 / REQ-7).

Covers:
  * quota_key = api_base_url | sha256(credential)[:12]
  * same inst → same key
  * different credential → different key
  * different api_base_url → different key
  * credential is hashed (never the raw secret in the key)
"""
import hashlib

from backend.agent.inference.provider import ProviderInstance, ProviderKind
from backend.agent.rate_meter import quota_key


class _Inst:
    """Minimal ProviderInstance stand-in for quota_key tests."""

    def __init__(self, id, api_base_url, api_key, kind=ProviderKind.API):
        self.id = id
        self.api_base_url = api_base_url
        self.api_key = api_key
        self.kind = kind


def _expected(base_url, cred):
    _h = hashlib.sha256(cred.encode("utf-8")).hexdigest()[:12]
    return f"{base_url}|{_h}"


def test_quota_key_format():
    _i = _Inst("p1", "https://api.example.com", "secret123")
    _k = quota_key(_i)
    assert _k == _expected("https://api.example.com", "secret123")
    assert _k.startswith("https://api.example.com|")
    assert len(_k.split("|")[1]) == 12


def test_same_inst_same_key():
    _a = _Inst("p1", "https://api.example.com", "secret123")
    _b = _Inst("p1", "https://api.example.com", "secret123")
    assert quota_key(_a) == quota_key(_b)


def test_different_credential_different_key():
    _a = _Inst("p1", "https://api.example.com", "secret123")
    _b = _Inst("p1", "https://api.example.com", "different")
    assert quota_key(_a) != quota_key(_b)


def test_different_base_url_different_key():
    _a = _Inst("p1", "https://api.example.com", "secret123")
    _b = _Inst("p1", "https://other.com", "secret123")
    assert quota_key(_a) != quota_key(_b)


def test_credential_hashed_not_plain():
    _i = _Inst("p1", "https://api.example.com", "supersecret")
    _k = quota_key(_i)
    assert "supersecret" not in _k
