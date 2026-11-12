"""Standard S-THINK (2026-11-11): the API transport asks the provider to skip
hidden reasoning where that was MEASURED to pay (opencodego deepseek: median
model call 6-7 s -> 2.1 s, coding median reply 88.7 s -> 39.9 s, cohort 21/21
before and after), and nowhere else (an unknown field can be a 400).

Fails on the old state: the rule and the request field did not exist.
"""
import inspect

from backend.agent.inference import transport as T


def test_the_measured_pair_gets_thinking_disabled(monkeypatch):
    monkeypatch.delenv("IRIS_KEEP_MODEL_THINKING", raising=False)
    assert T._thinking_off("opencodego", "deepseek-v4.1-flash")


def test_other_providers_and_models_never_get_the_field(monkeypatch):
    monkeypatch.delenv("IRIS_KEEP_MODEL_THINKING", raising=False)
    assert not T._thinking_off("opencodego", "minimax-m3.1-flash")
    assert not T._thinking_off("openrouter", "deepseek/deepseek-chat")
    assert not T._thinking_off("inceptionlabs", "mercury-3")
    assert not T._thinking_off("", "")


def test_the_off_switch_keeps_thinking(monkeypatch):
    monkeypatch.setenv("IRIS_KEEP_MODEL_THINKING", "1")
    assert not T._thinking_off("opencodego", "deepseek-v4.1-flash")


def test_the_request_body_carries_the_field():
    # The rule must reach the body that both the plain and the streamed call send.
    src = inspect.getsource(T.ApiHttpxTransport.generate)
    assert '_thinking_off(' in src
    assert 'body["thinking"] = {"type": "disabled"}' in src
