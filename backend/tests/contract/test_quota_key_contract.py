"""
Contract test for quota_key (T2.5 / D-9 / REQ-7 AC1).

Pins the boundary contract: quota_key MUST NOT be derived from
ProviderInstance.id alone (over-partitions) and MUST NOT be derived from
api_base_url alone (under-partitions). It MUST combine both. A break here is
caught at the interface, before behavior.
"""
from backend.agent.inference.provider import ProviderInstance, ProviderKind
from backend.agent.rate_meter import quota_key


class _Inst:
    def __init__(self, id, api_base_url, api_key, kind=ProviderKind.API):
        self.id = id
        self.api_base_url = api_base_url
        self.api_key = api_key
        self.kind = kind


def test_not_keyed_by_id_alone():
    # Two instances, same id, different credentials → must differ
    _a = _Inst("shared", "https://api.example.com", "keyA")
    _b = _Inst("shared", "https://api.example.com", "keyB")
    assert quota_key(_a) != quota_key(_b)


def test_not_keyed_by_base_url_alone():
    # Two instances, same base url, different credentials → must differ
    _a = _Inst("p1", "https://api.example.com", "keyA")
    _b = _Inst("p2", "https://api.example.com", "keyB")
    assert quota_key(_a) != quota_key(_b)


def test_combines_base_url_and_credential():
    _a = _Inst("p1", "https://api.example.com", "keyA")
    _b = _Inst("p1", "https://api2.example.com", "keyA")
    assert quota_key(_a) != quota_key(_b)
