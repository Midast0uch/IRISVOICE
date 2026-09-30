# Design: Fast Research + Real In-App Browser Control (rev 2, 2026-09-30)

Read `requirements.md` first (baseline, root causes RC1-RC8, the event contract). Line numbers
below are from the 2026-09-30 audit; RE-VERIFY each one before editing (the files move fast).

## Shape of the change

```
web goal
  -> _mem_lookup / tool choice          (REQ-1: factual -> search first; interaction -> browser_*)
  -> search (quick tier, Exa)           (REQ-1: parse text/highlights; loop-safe client)
       |-- enough?  -> synthesis        (one Brain pass; REQ-3)
       |-- not enough -> crawler_query
             -> Tier-1 httpx (policy UA; 403 = blocked, parked + recorded)      (REQ-2)
             -> pooled browser (bounded new_context/new_page/goto)             (REQ-2)
             -> returns at min_pages + grace, cancels the rest                (REQ-2)
             -> content -> synthesis (answer path)
             -> DataExtractor on lane("web_extract") -> OPEN_TAB payload       (REQ-3, side lane)
  -> browser_open / browser_observe / browser_act  (REQ-4/5: one live page per conversation)
       act: resolve element -> emit CRAWLER_VISION_ACTION phase=approach (x,y)
            -> wait travel -> real mouse/keyboard -> emit phase=done ok/err
            -> publish capture -> iframe follows
```

## Decisions

### D1: Fix the quick tier instead of adding providers
Exa already returns page text. The quick tier failed for two code bugs (RC3), not for lack of a
provider. Fix the parse (`text` / `highlights` at the result top level; keep `content.text` as a
fallback) and the client lifetime (create the `httpx.AsyncClient` per call, or cache one per
running loop keyed by `id(asyncio.get_running_loop())` and discard it when that loop closes).
Per-call creation is the simplest correct option; the connection cost is small against a 1-14 s
Exa call. Rejected: SearXNG/Brave/DDG providers (rev 1 T1) - not the measured problem.

Note measured 2026-09-30: an Exa `type: "auto"` call took 13.6 s cold and 0.14 s for the same
query again. Measure `type` alternatives (Exa docs: `auto`, `neural`, `keyword`, `fast` - check
the current API) before changing it; do not change it blind.

### D2: Route factual goals to `search`, escalate on insufficiency
`_mem_lookup` (`agent_kernel.py:~15853-15939`) hard-returns `crawler_query` with the goal
verbatim. Change: web-intent goals route to `search`; the query is shaped by the existing
query-shaping helper if one exists (search `_der_refine_query`, `_shape_query`,
`search_query_from_goal` first - reuse, do not add a second one), else the goal with filler
("search the web", "look up", "check a source online", "confirm") stripped. `crawler_query`
remains the escalation when the quick result sets `requires_deep_crawl` or the sufficiency check
fails. Keep the existing `_MAX_CRAWLS_PER_TASK` budget.

### D3: 403 is "blocked", not "challenge"; the browser does not fight it
Tier-1 UA from env `IRIS_CRAWL_USER_AGENT`, default
`IRISVoice/1.0 (+https://github.com/Midast0uch/IRISVOICE; research assistant)`. Use it for
robots.txt too (`robots_checker.py:~58`). `is_challenge_page()` markers stay the only
`challenge` signal; a bare 401/403 becomes `blocked`, which parks the URL and calls
`record_wall()` so the next run skips it, with no Tier-2 escalation. The existing policy "walls
park immediately" (`capabilities.py:~735-757`, `orchestrator.py:~107-118`) then holds inside
`fetch_one` as well (`capabilities.py:~232-241`).

### D4: Quorum return in `dispatch_urls`
Replace the all-or-nothing `gather` (`orchestrator.py:~1576`) with `asyncio.wait(...,
FIRST_COMPLETED)` in a loop: when usable results >= `min_pages` (default 3, already a parameter
- wire it), wait at most `grace_s` (default 2 s, env `IRIS_CRAWL_QUORUM_GRACE_S`) for stragglers,
then cancel the rest. Start each URL's budget clock after it acquires its semaphore (fixes
AC2.5). Cancelled URLs are not walls: no park, no `record_wall`.

### D5: DataExtractor leaves the answer path
Its JSON only feeds the dashboard `OPEN_TAB` payload (`orchestrator.py:~964`) and `summary`; the
agent consumes raw `content`. Run it on `durability_queue.lane("web_extract")` after `research()`
has returned its content; the lane job emits the `OPEN_TAB` event with the dashboard payload when
it lands (same event, same fields, later). Its model call moves to the light path with tools off
(the `SourceRegistry` fix at `source_registry.py:~208` is the pattern). The user-initiated
gateway path (`iris_gateway.py:~11499`) that DOES consume the extractor output stays synchronous
- only the agent path changes.

### D6: Browser tools on the existing `BrowserSession`
Reuse `backend/vision/browser_session.py` (pooled Chromium, keyring cookie injection, capture
publishing, bounding-box capture at `:~1066-1100`, `act()` at `:~901-929`). Do NOT create a new
browser manager. Add:
- a per-conversation session holder (dict conv_id -> BrowserSession, closed at conversation end /
  idle timeout; bounded - at most N sessions, default 2, LRU-closed);
- `observe()`: one `page.evaluate` of a JS function that collects visible interactive elements
  (see AC4.2 selector list), skips zero-size / hidden / off-document nodes, and returns
  `[{id, role, name, tag, x, y, w, h}]` in document order, capped (default 60, most-visible
  first); store the list on the session as `last_marks` with a `marks_seq`;
- `act(action, element_id, text)`: look up `last_marks[element_id]`; re-resolve the element by a
  stable handle stored at observe time (a `data-iris-mark` attribute set by the observe script),
  `scroll_into_view_if_needed`, recompute its box, emit approach, sleep travel, then
  `page.mouse.move` (steps>1) + `page.mouse.click` / `page.keyboard.type(text, delay=...)` /
  `select_option` / `mouse.wheel`; return `{ok, error?, url, title, changed}`. `act()` must read
  and return errors (the current `last_error` swallow is RC8).
- Marked screenshot: only when `resolve_vision_client()` reports a live vision model; draw the
  numbers with PIL on the PNG. Text marks alone are enough for the Brain and the tool model.

Tools registered in `tool_registry.py` + dispatched in `tool_bridge.py` like other tools, tier
`read_only` for observe, and the existing permission tier for input actions (typing into a form
is not read-only). Do not register the `fetch.vision` capability as an LLM-facing tool (audit: it
leaked into the tool-model grammar once with no executor) - mark it `hidden=True`.

### D7: Events: same names, one added field
`CRAWLER_VISION_ACTION` gains `phase` (`approach` | `done`), `ok`, `error`. `x`/`y` stay 0..1
viewport fractions (the hook's contract). The frontend already treats a burst of events as
saccadic and holds position when x/y are missing - no frontend change is required for the
animation. Optional frontend follow-up (separate task, owner review): show a failed-action
state when `ok=false`.

### D8: The Oracle in shadow only
Add `web_depth` and `browser_next` consumers the same way existing shadow consumers are wired
(`tool_decision.py` `_engine_try` / the consumer registry the contract test
`contract/test_consumer_registry.py` pins). Each logs its decision with the reference label
that is later known (what the Brain / outcome did). No enforcement.

## What stays untouched

`BrowserNavigationOverlay.tsx`, `useBrowserNavOverlay.ts`, `useCrawl`, `dark-glass-dashboard.tsx`,
`api/browser_surface.py` (capture proxy), the event names in the requirements table, the DER loop
shape, `InferenceRouter.generate` as the one model chokepoint.

## Error handling

| Failure | Response |
|---|---|
| Exa timeout / 429 / 5xx | quick tier returns `requires_deep_crawl: true` -> crawler_query |
| All Tier-1 URLs blocked | parked + recorded; `search_discovery` fallback stays as today |
| Browser launch fails | tool result `ok=false, error="browser unavailable: ..."`; no retry loop |
| Stale / unknown element id | `ok=false, error="element N not on page; call browser_observe"` |
| Navigation during act | act returns `changed=true`; the next observe renumbers (`marks_seq`+1) |
| Frontend disconnected | events dropped by the emitter; actions proceed |

## Testing (THE TEST RULE applies: existing tests are the requirement; do not weaken them)

- Contract: `CRAWLER_VISION_ACTION` payload keeps every existing field and adds `phase`/`ok`
  (extend the existing crawl-ui / overlay contract test if one exists, else a new contract test);
  Exa parse of a recorded real response (fixture from a live call); `blocked` vs `challenge`
  classification; `dispatch_urls` quorum return with a stub fetcher where 2 URLs never finish.
- Behavioral: `browser_observe` + `browser_act` against a LOCAL static HTML fixture page served
  by a temp http.server (a button that changes text, a text input, a link) - assert real clicks
  changed the DOM, events came in order approach -> done, a failed act reports `ok=false`.
- Measurement (the Director runs this, not the implementer): `evals/run_evals.py --task r01...
  r08` one at a time, backend detached, reply_s before/after; a guard per standard proven to fail
  on the old code.
