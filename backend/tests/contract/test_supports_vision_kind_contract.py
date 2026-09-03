"""CT-1 (specs/unified-vision-routing/design.md Testing Strategy):
`supports_vision` returns a bool for EVERY `ProviderKind` member, and a
future/unrecognised kind must return False rather than raise.

`ProviderKind` is enumerated DYNAMICALLY (``list(ProviderKind)`` /
``set(ProviderKind)``) instead of hardcoding the four current member names
into the parametrization, so this file fails the moment someone adds a
member to the enum — forcing a conscious update of both
``supports_vision`` and this test, rather than a silent pass because the
new member happens to also fall into the safe ``else: return False`` path
today.
"""

from __future__ import annotations

import pytest

from backend.agent.inference.provider import ProviderInstance, ProviderKind
from backend.agent.inference.router import supports_vision

# The set of ProviderKind members `supports_vision` explicitly branches on
# today (router.py's if/elif chain: API / LOCAL_OPENAI / INPROCESS / OLLAMA).
# If ProviderKind gains or loses a member, the canary test below fails FIRST
# — before any behavioral drift is possible — and a reviewer must decide
# whether `supports_vision` needs a new branch.
_HANDLED_KINDS = {
    ProviderKind.API,
    ProviderKind.LOCAL_OPENAI,
    ProviderKind.INPROCESS,
    ProviderKind.OLLAMA,
}


def test_provider_kind_enum_has_not_grown_unnoticed():
    """The actual CT-1 guard: dynamic enumeration of the real Enum, not a
    hardcoded parametrize list. A future ``ProviderKind.SOMETHING_NEW``
    breaks this assertion immediately."""
    assert set(ProviderKind) == _HANDLED_KINDS, (
        "ProviderKind gained or lost a member since this contract was "
        "written — update supports_vision()'s branches AND _HANDLED_KINDS "
        "in this file in the same change (CT-1)"
    )


@pytest.mark.parametrize("kind", list(ProviderKind))
def test_supports_vision_returns_bool_for_every_known_kind(kind, monkeypatch):
    """Every CURRENT member: supports_vision must return an actual `bool`
    and never raise, regardless of how minimal the instance is. The
    network-touching OLLAMA branch is stubbed to fail closed without a real
    socket — everything else runs the real code path."""
    if kind == ProviderKind.OLLAMA:
        class _RaisingClient:
            def __init__(self, *a, **kw):
                raise ConnectionError("no ollama daemon (test double)")

        monkeypatch.setattr("httpx.Client", _RaisingClient)

    inst = ProviderInstance(id="probe", label="Probe", kind=kind, model="some-model")
    result = supports_vision(inst)
    assert isinstance(result, bool)


class TestUnrecognisedKindNeverRaises:
    """The CT-1 edge case itself: a kind `supports_vision` does not
    recognise at all (simulating a FUTURE `ProviderKind` member added
    without updating this function) must resolve to False, never raise.
    `ProviderKind` is a real Enum and cannot gain a member at runtime, so a
    duck-typed stand-in exercises the exact same `else: return False`
    branch a real new member would hit."""

    def test_unrecognised_kind_is_false_not_raise(self):
        class _FutureInstance:
            id = "future-provider"
            kind = "some-brand-new-transport-kind"
            model = "gpt-vision-next"
            vision_loaded = True

        assert supports_vision(_FutureInstance()) is False

    def test_instance_missing_kind_attribute_entirely_is_false_not_raise(self):
        class _MalformedInstance:
            id = "malformed"
            model = "whatever"
            # deliberately no `kind` attribute at all

        assert supports_vision(_MalformedInstance()) is False

    def test_none_instance_is_false_not_raise(self):
        assert supports_vision(None) is False
