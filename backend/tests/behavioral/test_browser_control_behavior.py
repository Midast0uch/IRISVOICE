"""Behavioral: the agent really clicks and types in the in-app browser
(specs/websearch-vision-browser B1-B3, REQ-4 / REQ-5).

Drives the REAL stack — ``browser_tools`` -> ``BrowserSession`` -> Playwright
Chromium — against a LOCAL static fixture page (no network). Nothing here stubs
the browser: a click is proven by the page's own DOM and by timestamps the page
records when the input arrives.

Only two seams are patched, both for reasons the fixture forces:
  * ``_egress_error``: the egress guard (correctly) refuses loopback, and the
    fixture server IS loopback. ``test_browser_open_honors_the_egress_guard``
    runs WITHOUT the patch and pins that the guard is on.
  * the capture store root: frames land in ``tmp_path``, not ``data/captures``.
"""
from __future__ import annotations

import functools
import http.server
import threading
import time

import pytest

from backend.agent.tools import browser_tools
from backend.crawler import capture_store

_INDEX = """<!doctype html><html><head><title>Fixture Home</title></head><body>
<h1>Fixture page</h1>
<button id="b">Press me</button>
<label for="q">Search</label><input id="q" type="text">
<select id="s" aria-label="Colour"><option value="r">Red</option><option value="g">Green</option></select>
<a href="/two.html">Go to two</a>
<button id="hidden" style="display:none">Invisible</button>
<div id="out"></div>
<script>
window.__clicks = []; window.__keys = [];
document.getElementById('b').addEventListener('click', function () {
  window.__clicks.push(Date.now());
  this.textContent = 'Clicked';
  document.getElementById('out').textContent = 'clicked-marker';
});
document.getElementById('q').addEventListener('keydown', function () { window.__keys.push(Date.now()); });
</script></body></html>"""
_TWO = "<!doctype html><html><head><title>Fixture Two</title></head><body><h1>Second page</h1><a href='/'>Home</a></body></html>"


_HEAVY = """<!doctype html><html><head><title>Heavy</title>
<style>@font-face{font-family:x;src:url(/f.woff2)} body{font-family:x}</style></head><body>
<h1>Heavy page</h1><p>Enough visible text for the crawl to call this page usable.</p>
<video src="/clip.mp4" preload="auto"></video></body></html>"""


class _Handler(http.server.BaseHTTPRequestHandler):
    hits: list = []  # every request path the fixture server saw

    def do_GET(self):  # noqa: N802 — http.server API
        _Handler.hits.append(self.path)
        page = _TWO if self.path.startswith("/two.html") else _HEAVY if self.path.startswith("/heavy.html") else _INDEX
        body = page.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_a):  # keep test output quiet
        pass


@pytest.fixture(scope="module")
def site():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


@pytest.fixture
def allow_loopback(monkeypatch):
    async def _ok(_url):
        return ""

    monkeypatch.setattr(browser_tools, "_egress_error", _ok)


@pytest.fixture(autouse=True)
def tmp_captures(monkeypatch, tmp_path):
    monkeypatch.setattr(capture_store, "_store", capture_store.CaptureStore(root=str(tmp_path)))
    return tmp_path


@pytest.fixture(autouse=True)
def brain_judges_fixture_actions_safe(monkeypatch):
    """The click-safety gate (W2) sends an ambiguous element (the fixture's "Press me")
    to the Brain judge, and there is no model in this test. The rules stay real; only
    the model call answers "safe" so these tests keep driving real input."""
    from backend.agent import click_safety_shadow
    from backend.agent.tools import click_safety

    monkeypatch.setattr(click_safety, "_call_llm", lambda _p: '{"verdict": "safe", "reason": "fixture"}')
    # No Oracle engine either: the shadow row's scoring would load the decision model
    # on a background lane while the browser is being driven.
    monkeypatch.setattr(click_safety_shadow, "ENGINE", None)


class _Events:
    """The emit seam the tool bridge hands the session; records wall time per event."""

    def __init__(self):
        self.items: list = []

    def __call__(self, event, payload):
        self.items.append((event, dict(payload), time.time() * 1000.0))

    def vision(self):
        return [(p, t) for ev, p, t in self.items if ev == "CRAWLER_VISION_ACTION"]

    def of(self, name):
        return [p for ev, p, _t in self.items if ev == name]


@pytest.fixture
async def conv():
    cid = f"conv-{time.monotonic_ns()}"
    yield cid
    await browser_tools.close_conversation_browser(cid)


async def _eval(cid, js):
    page = browser_tools._RT.sessions[cid].session._page
    return await browser_tools._RT.run(page.evaluate(js), 10)


def _mark(observed, role, name):
    hits = [m for m in observed["marks"] if m["role"] == role and m["name"] == name]
    assert hits, f"no {role} {name!r} in {[(m['role'], m['name']) for m in observed['marks']]}"
    return hits[0]


async def _open_observed(cid, site, events):
    opened = await browser_tools.browser_open(cid, site + "/", events)
    assert opened["success"], opened
    observed = await browser_tools.browser_observe(cid, events)
    assert observed["success"], observed
    return observed


# ── B1: observe ────────────────────────────────────────────────────────────


async def test_observe_lists_button_input_link_with_roles_names_and_boxes(site, allow_loopback, conv):
    """B1 DONE: the fixture's button, input and link come back with the right
    role, accessible name and a real box; the hidden button does not."""
    observed = await _open_observed(conv, site, _Events())

    button = _mark(observed, "button", "Press me")
    box_input = _mark(observed, "textbox", "Search")  # named by its <label>
    link = _mark(observed, "link", "Go to two")
    assert _mark(observed, "combobox", "Colour")["tag"] == "select"
    assert not any(m["name"] == "Invisible" for m in observed["marks"])
    for m in (button, box_input, link):
        assert m["w"] > 10 and m["h"] > 5 and m["x"] >= 0 and m["y"] >= 0 and m["in_view"]

    ids = [m["id"] for m in observed["marks"]]
    assert ids == list(range(1, len(ids) + 1)), "ids must be 1..N"
    # Each id is tagged on the live DOM node (the handle act() re-finds it by).
    assert await _eval(conv, f"document.querySelector('[data-iris-mark=\"{button['id']}\"]').id") == "b"
    assert observed["title"] == "Fixture Home" and observed["url"].endswith("/")
    assert "Fixture page" in observed["content"] and f"[{button['id']}] button \"Press me\"" in observed["content"]
    second = await browser_tools.browser_observe(conv, _Events())
    assert second["marks_seq"] == observed["marks_seq"] + 1


async def test_marked_screenshot_only_when_a_vision_model_is_live(site, allow_loopback, conv, monkeypatch):
    """B1 DONE / AC4.2: the numbered screenshot is attached only with a live vision model."""
    async def _no():
        return False

    async def _yes():
        return True

    await _open_observed(conv, site, None)
    monkeypatch.setattr(browser_tools, "_vision_live", _no)
    assert "marked_screenshot" not in await browser_tools.browser_observe(conv)
    monkeypatch.setattr(browser_tools, "_vision_live", _yes)
    shot = (await browser_tools.browser_observe(conv))["marked_screenshot"]
    assert shot["mime"] == "image/jpeg" and len(shot["b64"]) > 1000


# ── B2: act ────────────────────────────────────────────────────────────────


async def test_click_really_clicks_and_announces_approach_before_done(site, allow_loopback, conv):
    """B2 DONE: the click changes the DOM; events arrive approach -> done in
    order with the element's x/y; the input lands AFTER the approach event."""
    events = _Events()
    observed = await _open_observed(conv, site, events)
    button = _mark(observed, "button", "Press me")
    events.items.clear()

    result = await browser_tools.browser_act(conv, "click", button["id"], None, events)

    assert result["success"], result
    assert await _eval(conv, "document.getElementById('out').textContent") == "clicked-marker"
    assert await _eval(conv, "document.getElementById('b').textContent") == "Clicked"
    (approach, t_approach), (done, _t_done) = events.vision()
    assert approach["phase"] == "approach" and done["phase"] == "done"
    assert done["ok"] is True and "error" not in done
    assert approach["seq"] < done["seq"], "the overlay de-duplicates by (run_id, seq)"
    assert approach["run_id"] == done["run_id"] and approach["action_index"] == done["action_index"]
    # Existing contract fields are all present.
    for key in ("kind", "x", "y", "viewport_w", "viewport_h", "scroll_y", "scroll_height",
                "seq", "run_id", "action_index", "total", "job_id", "url"):
        assert key in approach, key
    assert approach["kind"] == "click"
    # x/y are 0..1 fractions of the viewport, at the element's centre.
    cx = (button["x"] + button["w"] / 2) / approach["viewport_w"]
    cy = (button["y"] + button["h"] / 2) / approach["viewport_h"]
    assert approach["x"] == pytest.approx(cx, abs=0.002) and approach["y"] == pytest.approx(cy, abs=0.002)
    assert 0.0 <= approach["x"] <= 1.0 and 0.0 <= approach["y"] <= 1.0
    # The input came AFTER the announcement, by at least the overlay travel time
    # (180 ms sleep, then the mouse glide). 170 leaves 10 ms for clock granularity
    # on Windows; with the wait removed the gap measures ~136 ms (the glide alone),
    # so this still fails if the wait is dropped.
    clicked_at = (await _eval(conv, "window.__clicks"))[0]
    assert clicked_at - t_approach >= 170, f"click {clicked_at - t_approach:.0f} ms after approach"


async def test_typing_fills_the_input_with_a_per_key_delay(site, allow_loopback, conv):
    """B2 DONE: typing fills the input with real key events paced 30-90 ms apart."""
    events = _Events()
    observed = await _open_observed(conv, site, events)
    box = _mark(observed, "textbox", "Search")
    text = "hello world"

    result = await browser_tools.browser_act(conv, "type", box["id"], text, events)

    assert result["success"], result
    assert await _eval(conv, "document.getElementById('q').value") == text
    keys = await _eval(conv, "window.__keys")
    assert len(keys) == len(text)
    # The mean gap is span/(n-1): the page's delivery jitter telescopes out of it, so the
    # 30 ms floor (the spec's minimum per-key delay) needs no jitter allowance. The
    # ceiling is NOT the 90 ms spec maximum: each key also pays one CDP round trip and
    # Windows' ~15 ms timer granularity on top of the injected 30-90 ms (measured mean
    # 127 ms). 250 ms only catches a runaway delay.
    mean_gap = (keys[-1] - keys[0]) / (len(keys) - 1) / 1000.0
    assert 0.030 <= mean_gap <= 0.250, f"mean per-key gap {mean_gap * 1000:.0f} ms"
    assert [p["phase"] for p, _t in events.vision()][-2:] == ["approach", "done"]


async def test_unknown_element_id_is_an_error_and_emits_no_approach(site, allow_loopback, conv):
    """B2 DONE / AC4.4: an unknown id returns ok=false naming the problem, and
    NO cursor event fires toward nothing; a stale id (page navigated) does the same."""
    events = _Events()
    observed = await _open_observed(conv, site, events)
    link = _mark(observed, "link", "Go to two")
    events.items.clear()

    missing = await browser_tools.browser_act(conv, "click", 999, None, events)
    assert missing["success"] is False
    assert "999" in missing["error"] and "browser_observe" in missing["error"]
    assert events.vision() == [], "an unresolvable element must not emit an approach"

    nav = await browser_tools.browser_act(conv, "click", link["id"], None, events)
    assert nav["success"] and nav["changed"] and nav["url"].endswith("/two.html")
    events.items.clear()
    stale = await browser_tools.browser_act(conv, "click", link["id"], None, events)
    assert stale["success"] is False and "call browser_observe" in stale["error"]
    assert events.vision() == []


async def test_failed_action_reports_ok_false_and_the_error(site, allow_loopback, conv):
    """B2 DONE / AC5.2: an action that resolves but fails is announced, then
    reported `ok=false` with its error — never as a success."""
    events = _Events()
    observed = await _open_observed(conv, site, events)
    button = _mark(observed, "button", "Press me")
    events.items.clear()

    # A <button> is not a <select>: the element resolves, the input then fails.
    result = await browser_tools.browser_act(conv, "select", button["id"], "Red", events)

    assert result["success"] is False and "select failed" in result["error"]
    (approach, _), (done, _) = events.vision()
    assert approach["phase"] == "approach" and done["phase"] == "done"
    assert done["ok"] is False and done["error"]
    assert browser_tools._RT.sessions[conv].session.last_error, "the swallowed last_error must surface"

    events.items.clear()
    back = await browser_tools.browser_act(conv, "back", None, None, events)  # no history
    assert back["success"] is False and "no previous page" in back["error"]
    assert events.vision()[-1][0]["ok"] is False


# ── B3: the iframe follows ─────────────────────────────────────────────────


async def test_page_changing_actions_publish_a_fresh_capture(site, allow_loopback, conv, tmp_captures):
    """B3 DONE: after a click that changes the DOM — and after one that navigates —
    a NEW capture page is published and announced, so the iframe follows."""
    events = _Events()
    observed = await _open_observed(conv, site, events)
    opened_pages = events.of("CRAWLER_PAGE_FETCHED")
    assert len(opened_pages) == 1 and opened_pages[0]["capture_available"] is True
    first = opened_pages[0]["capture_page"]
    job = opened_pages[0]["job_id"]
    store = capture_store.get_capture_store()
    assert store.has(job, first)

    await browser_tools.browser_act(conv, "click", _mark(observed, "button", "Press me")["id"], None, events)
    after_dom = events.of("CRAWLER_PAGE_FETCHED")[-1]
    assert after_dom["capture_page"] > first and store.has(job, after_dom["capture_page"])
    assert "clicked-marker" in store.load(job, after_dom["capture_page"])["html"]

    # A no-op action publishes nothing new (the frame is de-duplicated).
    n_before = len(events.of("CRAWLER_PAGE_FETCHED"))
    await browser_tools.browser_act(conv, "scroll", None, "up", events)
    assert len(events.of("CRAWLER_PAGE_FETCHED")) == n_before

    observed = await browser_tools.browser_observe(conv, events)
    await browser_tools.browser_act(conv, "click", _mark(observed, "link", "Go to two")["id"], None, events)
    after_nav = events.of("CRAWLER_PAGE_FETCHED")[-1]
    assert after_nav["capture_page"] > after_dom["capture_page"] and after_nav["url"].endswith("/two.html")
    assert "Second page" in store.load(job, after_nav["capture_page"])["html"]


# ── the holder: bounded, LRU, guarded ──────────────────────────────────────


async def test_sessions_are_bounded_and_the_least_recently_used_is_closed(site, allow_loopback):
    """B1: at most N sessions; opening one more closes the LRU one and tells its panel."""
    limit = browser_tools._MAX_SESSIONS
    cids = [f"lru-{time.monotonic_ns()}-{i}" for i in range(limit + 1)]
    events = _Events()
    try:
        for cid in cids[:limit]:
            assert (await browser_tools.browser_open(cid, site + "/", events))["success"]
        # Touch the first, so the SECOND is now least recently used.
        await browser_tools.browser_observe(cids[0], events)
        assert (await browser_tools.browser_open(cids[limit], site + "/", events))["success"]
        evicted = cids[1] if limit > 1 else cids[0]
        assert set(browser_tools._RT.sessions) == set(cids) - {evicted}
        assert any("evicted" in p["summary"] for p in events.of("CRAWLER_COMPLETE"))
    finally:
        for cid in cids:
            await browser_tools.close_conversation_browser(cid)
    assert not browser_tools._RT.sessions


async def test_browser_open_honors_the_egress_guard(site, conv):
    """No patch: the loopback fixture is refused, like every other tool's fetch."""
    result = await browser_tools.browser_open(conv, site + "/", None)
    assert result["success"] is False and "not allowed" in result["error"]
    assert conv not in browser_tools._RT.sessions


async def test_observe_and_act_without_an_open_browser_say_so(conv):
    for res in (await browser_tools.browser_observe(conv),
                await browser_tools.browser_act(conv, "click", 1)):
        assert res["success"] is False and "browser_open" in res["error"]


# ── one Chromium on one host loop (W1 / REQ-5) ─────────────────────────────


def _chromium_tree():
    """(processes, browser_main_processes, working_set_bytes, main_cmdlines) of this
    process's Chromium descendants. Working set = summed RSS (Windows working set)."""
    psutil = pytest.importorskip("psutil")
    procs, mains, ws = 0, 0, 0
    cmdlines: list = []
    for p in psutil.Process().children(recursive=True):
        try:
            if not any(k in p.name().lower() for k in ("chrom", "headless_shell")):
                continue
            cmd = p.cmdline()
            procs += 1
            ws += p.memory_info().rss
            if not any(a.startswith("--type=") for a in cmd):
                mains += 1
                cmdlines.append(cmd)
        except psutil.Error:
            continue
    return procs, mains, ws, cmdlines


async def test_a_session_and_a_crawl_fetch_on_another_loop_share_one_chromium(
    site, allow_loopback, conv, monkeypatch, record_property,
):
    """W1 DONE: a pool crawl fetch (on a fresh event loop, as every crawl tool call
    runs) and an agent browser session run at the same time and both succeed; the
    backend launches exactly ONE Chromium, with the D5 memory flags; the crawl
    context never requests media or fonts."""
    import asyncio

    from backend.crawler import capabilities
    from backend.vision import browser_pool

    await browser_pool.shutdown_browser_pool()  # a clean pool: count this test's launches
    launches: list = []
    real_start = browser_pool._start_browser

    async def counting_start():
        launches.append(1)
        await real_start()

    monkeypatch.setattr(browser_pool, "_start_browser", counting_start)
    _Handler.hits.clear()
    # Warm the pool first (the plan-time prewarm does this in production): the crawl's
    # per-page budget is 8 s of navigation and does not include a cold Chromium start
    # that competes with the session's own open for the CPU.
    _warm_browser, warm_lease = await browser_pool.acquire_browser()
    warm_lease.release()

    outcome: list = []

    def crawl_on_its_own_loop():
        outcome.append(asyncio.run(asyncio.wait_for(
            capabilities._browser_pool_fetch_one(site + "/heavy.html", "heavy page", "job-w1", 0, None), 90,
        )))

    worker = threading.Thread(target=crawl_on_its_own_loop)
    worker.start()
    opened = await browser_tools.browser_open(conv, site + "/", None)
    await asyncio.to_thread(worker.join, 120)

    assert opened["success"], opened
    (fetched,) = outcome
    assert fetched.page is not None and "Heavy page" in fetched.page.markdown, fetched.verdict
    assert len(launches) == 1, f"{len(launches)} Chromium launches for one crawl + one session"
    assert (await browser_tools.browser_observe(conv))["success"], "the session survived the crawl fetch"

    procs, mains, ws, cmdlines = _chromium_tree()
    record_property("chromium_working_set_mb_one_crawl_one_session", round(ws / 1e6))
    print(f"\n[W1] one crawl + one session: chromium procs={procs} browsers={mains} working_set={ws / 1e6:.0f} MB")
    assert mains == 1, f"{mains} Chromium browser processes are alive"
    flags = " ".join(cmdlines[0])
    for flag in ("--renderer-process-limit=4", "--js-flags=--max-old-space-size=256", "--disable-gpu"):
        assert flag in flags, f"{flag} missing from the launch"
    assert "/heavy.html" in _Handler.hits
    assert not {"/clip.mp4", "/f.woff2"} & set(_Handler.hits), "the crawl context fetched media or a font"

    await browser_tools.close_conversation_browser(conv)
    await browser_pool.shutdown_browser_pool()
    _, mains_after, _, _ = _chromium_tree()
    assert mains_after == 0, "the Chromium did not stop on shutdown"
