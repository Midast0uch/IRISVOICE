"""CLM-11 / T7.3 contract: the digest is bounded, `wb` refs round-trip, the stdout ring
and expand answer from a REAL worker, and a gone value is a named case."""
import pytest

from backend.tests.contract._wb_common import drop, make_workdir, mod

digest = mod("digest")
manager_mod = mod("manager")


@pytest.fixture
def env():
    wd = make_workdir()
    m = manager_mod.WorkbenchManager()
    client = m.workbench_for("conv-d", wd)
    try:
        yield m, client
    finally:
        m.shutdown()
        drop(wd)


def test_digest_is_bounded(env):
    _, c = env
    code = ("print('s' * 5000)\n" + "\n".join(f"v{i} = list(range({100 + i}))" for i in range(20))
            + "\n'V' * 1000")
    rep = c.exec(code)
    text = digest.digest(rep)
    stdout_part = text.split("stdout:\n", 1)[1].split("\nfull output:", 1)[0]
    assert len(stdout_part) <= 1200 + len("\n... [3800 chars cut] ...\n") + 2     # head + tail + the cut marker
    assert text.count("[wb:") == 12 and "... and 8 more" in text
    value_line = [l for l in text.splitlines() if l.startswith("value: ")][0]
    assert len(value_line) <= len("value: ") + 400
    assert len(text) < 3600
    lines = [l for l in text.splitlines() if l.startswith("v") and ": list" in l]
    assert len(lines) == 12 and "size 100 - " in lines[0] and f"[wb:{rep['incarnation']}/v0]" in lines[0]


def test_digest_error_and_truncated(env):
    _, c = env
    rep = c.exec("answer = 42\nraise ValueError('boom')")
    text = digest.digest(rep)
    assert "run_python error" in text and "error: ValueError: boom" in text
    assert "ValueError: boom" in text.split("error: ValueError: boom", 1)[1]        # the trace tail follows
    assert "kept:" not in text and rep["kept"] == []
    assert "output was cut" in digest.digest({**rep, "truncated": True})


def test_wb_refs_parse_and_survive_the_placeholder(env):
    _, c = env
    rep = c.exec("table = [1, 2, 3]\nprint('x' * 3000)")
    refs = digest.refs(rep)
    assert refs and any(r.endswith("/table") for r in refs) and any("/out" in r for r in refs)
    from backend.agent.context_view import Block, Ref, parse_placeholder, render_placeholder

    for r in refs:
        inc, name = digest.parse_ref(r)
        assert inc == rep["incarnation"] and digest.make_ref(inc, name) == r
        ref = Ref(kind="wb", id=f"{inc}/{name}")
        block = Block(block_id="b1", ref=ref, kind="tool", messages=[], tokens=0, ts=0.0)
        line = render_placeholder(block, "set aside")
        assert parse_placeholder(line) == ref
    for bad in ("wb:", "wb:abc", "tool_result:abc/x", "wb:abc/", "wb: abc/x", ""):
        assert digest.parse_ref(bad) is None


def test_stdout_ring_keeps_the_last_fifty(env):
    _, c = env
    first = c.exec("print('first-output')")
    inspect_first = c.inspect(f"out{first['out_n']}")
    assert inspect_first["ok"] and inspect_first["text"].strip() == "first-output"
    for i in range(50):
        c.exec(f"print('o{i}')")
    gone = c.inspect(f"out{first['out_n']}")
    assert gone["ok"] is False and gone["error"]["type"] == "KeyError"
    last = c.exec("print('last')")
    assert c.inspect(f"out{last['out_n']}")["text"].strip() == "last"


def test_full_stdout_returned_by_expand_in_pages(env):
    m, c = env
    rep = c.exec("print('0123456789' * 1500)")                     # 15,001 chars with the newline
    ref = digest.refs(rep)[-1]
    assert ref.endswith(f"/out{rep['out_n']}")
    p1 = manager_mod.expand(ref, 0, manager=m)
    assert p1["success"] and p1["chars"] == 15001 and len(p1["content"]) == 6000 and p1["next_offset"] == 6000
    p3 = manager_mod.expand(ref, 12000, manager=m)
    assert p3["success"] and "next_offset" not in p3 and p3["content"].endswith("\n")


def test_expand_variable_then_gone_cases(env):
    m, c = env
    rep = c.exec("rows = list(range(10))")
    digest.remember_origin(rep, "load the rows")
    ref = digest.make_ref(rep["incarnation"], "rows")
    ok = manager_mod.expand(ref, 0, manager=m)
    assert ok["success"] and ok["content"] == "[0, 1, 2, 3, 4, 5, 6, 7, 8, 9]"
    c.exec("del rows")                                              # name missing
    g1 = manager_mod.expand(ref, 0, manager=m)
    assert g1["success"] is False and g1["case"] == "workbench_gone" and g1["purpose"] == "load the rows"
    m.close("conv-d")                                               # incarnation gone
    g2 = manager_mod.expand(ref, 0, manager=m)
    assert g2["case"] == "workbench_gone" and g2["purpose"] == "load the rows" and g2["error"]
    assert manager_mod.expand("wb:nothing", 0, manager=m)["case"] == "malformed_ref"
    assert manager_mod.expand("wb:abc/__import__('os')", 0, manager=m)["case"] == "malformed_ref"


def test_digest_warns_when_the_worker_tree_passes_256_mb(env):
    _, c = env
    rep = c.exec("blob = b'x' * (300 * 1024 * 1024)\nlen(blob)")
    mb = c.rss_mb()
    assert mb > 256
    assert f"[workbench holds {int(mb)} MB - del what you no longer need]" in digest.digest(rep, mb)
    assert "[workbench holds" not in digest.digest(rep, 100.0)
    assert "[workbench holds" not in digest.digest(rep)
