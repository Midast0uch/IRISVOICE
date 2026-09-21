import asyncio
import backend.tools.lfm_vl_provider as vl
import httpx

class _FakeResponse:
    def __init__(self, status_code=200, json_data=None):
        self.status_code = status_code
        self._json = json_data if json_data is not None else {}
    def json(self):
        return self._json
    def raise_for_status(self):
        pass

class _FakeHttpx:
    def __init__(self, scenario):
        self.scenario = scenario
        self.calls = []
    def get(self, url, timeout=1.0, headers=None):
        self.calls.append(('GET', url))
        if url.endswith("/models"):
            if self.scenario == "multimodal":
                return _FakeResponse(200, {"data": [{"id": "vision-model"}]})
        return _FakeResponse(200, {})
    def post(self, url, json=None, timeout=1.0, headers=None):
        self.calls.append(('POST', url))
        return _FakeResponse(200, {"choices": [{"message": {"content": "ok"}}]})

vl._load_candidate_endpoints_from_config = lambda: []
vl.clear_vision_capability_cache()
vl._EXTRA_VISION_ENDPOINTS = []

fake = _FakeHttpx("multimodal")
httpx.get = fake.get
httpx.post = fake.post

vl.set_vision_candidate_endpoints(["http://localhost:1234/v1"])

# trace _candidate_vision_specs
cands = vl._candidate_vision_specs("")
print("candidates:", cands)

# trace discovery
res = vl._discover_reusable_vision_server("")
print("discovery result:", res)
print("reused:", vl._reused_vision_base_url)
print("calls:", fake.calls)
