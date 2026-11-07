"""The pre-load engine identity must equal the identity the bar record carries.

MEASURED 2026-11-06: ``_current_backend_identity`` fell back to the BARE
``backend_id`` (``d1-2b-q4_k_m``) while the bar record and the LOADED engine use
the readout-tagged ``model_id`` (``d1-2b-q4_k_m+systemone``). The enforcement
check runs before the engine loads, so every consumer read "measured on a
different engine" and the Oracle enforced NOTHING (``deciding=none``) even
though narration/presentation/route_v2 held ``status=enforced``.
"""
from backend.agent import decision_engine as de
from backend.agent.decision_backend_d1 import D1Backend


def test_unloaded_identity_uses_the_tagged_model_id(monkeypatch):
    class _Unloaded:
        model_id = None

    monkeypatch.setattr(de, "get_decision_engine", lambda: _Unloaded())
    ident = de._current_backend_identity("narration")
    assert ident.split("|")[0] == D1Backend().model_id


def test_the_tagged_id_is_not_duplicated(monkeypatch):
    # the identity is model|readout|hash; the model part must not already carry
    # a second readout suffix
    class _Unloaded:
        model_id = None

    monkeypatch.setattr(de, "get_decision_engine", lambda: _Unloaded())
    parts = de._current_backend_identity("narration").split("|")
    assert len(parts) == 3
    assert parts[0].count("+") <= 1
