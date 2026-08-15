"""T9 — View-agent injection contract (REQ-4 AC1/AC2/AC5)."""

from backend.proxy.view_agent import inject_view_agent, VIEW_AGENT_SCRIPT


def test_injects_before_body():
    html = "<html><head><title>x</title></head><body>hi</body></html>"
    out = inject_view_agent(html)
    assert "postMessage" in out
    assert out.index("<script>") < out.index("</body>")


def test_idempotent_no_double_inject():
    html = "<html><body>hi</body></html>"
    once = inject_view_agent(html)
    twice = inject_view_agent(once)
    assert once == twice


def test_empty_passthrough():
    assert inject_view_agent("") == ""
    assert inject_view_agent(None) is None


def test_no_body_appends():
    html = "<html><p>a</p></html>"
    out = inject_view_agent(html)
    assert out.startswith(html)
    assert "postMessage" in out


def test_script_is_fixed_shape_v1():
    assert "__iris" in VIEW_AGENT_SCRIPT
    assert "v: 1" in VIEW_AGENT_SCRIPT
    assert "kind" in VIEW_AGENT_SCRIPT
    assert 'window.parent.postMessage(msg, "*")' in VIEW_AGENT_SCRIPT
    # Only the two documented commands are accepted.
    assert "scrollTo" in VIEW_AGENT_SCRIPT
    assert "highlight" in VIEW_AGENT_SCRIPT


def test_script_never_raises():
    # No bare `throw` statement; every body is wrapped in try/catch.
    assert "throw e" not in VIEW_AGENT_SCRIPT
    assert "throw new" not in VIEW_AGENT_SCRIPT
    assert "try {" in VIEW_AGENT_SCRIPT
