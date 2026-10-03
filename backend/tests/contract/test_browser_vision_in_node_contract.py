"""V8 guard (audit addendum 2026-10-02): the marked page screenshot that
browser_observe builds reaches a model.

Before: browser_observe drew Set-of-Marks on a screenshot and NOTHING read it
(the agent browsed on the DOM text list only; vision took no part in two live
browser runs). Now, inside a node:
  - the node's own model can see -> it gets the screenshot as an image message
    (only the newest image stays in the history);
  - it cannot see -> the resolved vision model reads the screenshot as text, on
    a page the element list cannot carry (<= 3 marks) or when the model asks.
"""

import json

from backend.agent.inference.router import InferenceRouter
from backend.agent.inference.transport import _to_ollama_messages
from backend.agent.node_executor import NodeContext, run_node

TOOLS = [{"type": "function", "function": {"name": n, "parameters": {}}}
         for n in ("browser_observe", "browser_act")]
SHOT = "AAAA"


def _call(name, args, i=0):
    return {"id": f"c{i}", "type": "function",
            "function": {"name": name, "arguments": json.dumps(args)}}


def _observe(n_marks, title="p"):
    return {"success": True, "content": f"Page: {title}", "title": title,
            "marks": [{"id": i} for i in range(n_marks)],
            "marked_screenshot": {"mime": "image/jpeg", "b64": SHOT}}


def _run(script, results, **kw):
    seen, replies = [], list(script)

    def gen(role, messages, **k):
        seen.append([dict(m) for m in messages])
        text, calls = replies.pop(0)
        return text, "", calls

    seq = {name: list(v) for name, v in results.items()}

    def execute(name, params):
        return seq[name].pop(0)

    ctx = NodeContext(generate=gen, execute=execute, format_result=lambda n, r: r.get("content", ""),
                      tools=TOOLS, **kw)
    return run_node("Find the height of Kilimanjaro", ctx), seen


def _images(messages):
    return [m for m in messages if isinstance(m.get("content"), list)
            and any(p.get("type") == "image_url" for p in m["content"])]


def test_a_seeing_model_gets_the_screenshot_and_only_the_newest_stays():
    script = [("", [_call("browser_observe", {}, 0)]),
              ("", [_call("browser_act", {"action": "click", "element_id": 1}, 1)]),
              ("", [_call("browser_observe", {}, 2)]),
              ("Found it.\nSTATUS: done", [])]
    looked = []
    r, seen = _run(script, {
        "browser_observe": [_observe(20, "a"), _observe(20, "b")],
        "browser_act": [{"success": True, "content": "clicked"}],
    }, sees=lambda role: True, look=lambda b64, q: looked.append(q) or "x")
    assert r.success
    shots = _images(seen[1])
    assert len(shots) == 1 and SHOT in shots[0]["content"][1]["image_url"]["url"]
    assert len(_images(seen[3])) == 1  # the first screenshot was dropped
    assert looked == []  # a model that sees needs no reader


def test_a_blind_model_gets_a_vision_reading_on_a_poor_page():
    script = [("", [_call("browser_observe", {}, 0)]), ("Done.\nSTATUS: done", [])]
    looked = []
    r, seen = _run(script, {"browser_observe": [_observe(2)]},
                   sees=lambda role: False,
                   look=lambda b64, q: looked.append((b64, q)) or "A chart: peak 5895 m.")
    tool_msg = [m for m in seen[1] if m.get("role") == "tool"][0]
    assert "A chart: peak 5895 m." in tool_msg["content"]
    assert looked == [(SHOT, "Find the height of Kilimanjaro")]
    assert _images(seen[1]) == []  # a blind model is never sent the image


def test_a_blind_model_on_a_rich_page_reads_only_when_it_asks():
    looked = []
    look = lambda b64, q: looked.append(q) or "seen"  # noqa: E731
    _run([("", [_call("browser_observe", {}, 0)]), ("Done.\nSTATUS: done", [])],
         {"browser_observe": [_observe(30)]}, sees=lambda role: False, look=look)
    assert looked == []
    _run([("", [_call("browser_observe", {"question": "which tab is red?"}, 0)]),
          ("Done.\nSTATUS: done", [])],
         {"browser_observe": [_observe(30)]}, sees=lambda role: False, look=look)
    assert looked == ["which tab is red?"]


def test_ollama_gets_images_in_its_own_field():
    out = _to_ollama_messages([{"role": "user", "content": [
        {"type": "text", "text": "note"},
        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,QUJD"}},
    ]}])
    assert out == [{"role": "user", "content": "note", "images": ["QUJD"]}]


def test_the_window_estimate_counts_an_image():
    with_img = [{"role": "user", "content": [
        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,QUJD"}}]}]
    assert InferenceRouter._estimate_prompt_tokens(with_img, None) >= 1000


def test_a_failed_call_may_be_retried_once():
    """Live 2026-10-02: browser_open timed out on a cold Chromium (90 s); the
    model's retry was blocked as a 'repeated call' and the node closed done
    with no page open. A failed call runs again; a succeeding retry counts."""
    script = [("", [_call("browser_open", {"url": "https://en.wikipedia.org"}, 0)]),
              ("", [_call("browser_open", {"url": "https://en.wikipedia.org"}, 1)]),
              ("Opened.\nSTATUS: done", [])]
    seen, replies = [], list(script)
    runs = []

    def gen(role, messages, **k):
        seen.append(messages)
        text, calls = replies.pop(0)
        return text, "", calls

    def execute(name, params):
        runs.append(name)
        return ({"success": False, "error": "browser unavailable: timed out"} if len(runs) == 1
                else {"success": True, "content": "Opened"})

    tools = [{"type": "function", "function": {"name": "browser_open", "parameters": {}}}]
    r = run_node("Open Wikipedia", NodeContext(generate=gen, execute=execute,
                                               format_result=lambda n, raw: str(raw), tools=tools))
    assert runs == ["browser_open", "browser_open"]
    assert r.success and [c["ok"] for c in r.calls] == [False, True]
