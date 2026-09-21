# Live Test Criteria â€” vision-browser-e2e-reliability

Date: 2026-09-18. Session 341.
Spec: `specs/vision-browser-e2e-reliability` (landmark `vision-browser-e2e-reliability-complete`).
Status this closes: Verification Plan steps 6 (panel reflection) and 10 (latency
baseline) â€” both UNVERIFIED in T14 because the frontend was down.

**THE AGENT ANSWERING IS NOT A PASS.** A canned or training-data reply is a FAIL.
The pass grade is: the task completes, measurably fast, with proof the agent
browsed.

---

## LT-0 â€” Preconditions

- Backend up on :8090 (`/health` â†’ 200), frontend on :3000 (`GET /` â†’ 200,
  single title `Control Center | TTS Chatbot`).
- Exactly ONE tab on localhost:3000 (duplicate tabs cancel the in-flight turn â€”
  `client_replace`).
- Web mode ON (toggle offâ†’on if the desync is suspected).
- Vision provider resolvable (tier 1/2 via `resolve_vision_client`, else tier 3
  local VL). Record which tier served â€” it changes the latency picture.

## Time budget (owner rule, 2026-09-18)

**No single live-run may exceed 5 minutes.** Target for the vision-e2e loop:
under 3 minutes once warm. The tier-3 vision source is the SHARED multimodal
server (specs/vision-single-server) â€” borrowed in ~ms, no cold spawn.

## LT-1 â€” The drive prompt

Type ONE prompt that forces the agent to find its own URLs and extract from
them. The user gives NO URL. Example:

> "Search the web for the current price of the RTX 5090 Founders Edition and
> tell me what two different retailers list it at."

IMPORTANT â€” HOW the prompt is written:
- **No meta-instructions.** Never tell the agent "use your browsing tools",
  "use vision", or which tool to call. Tool selection is the agent's own
  decision; spelling it out in the prompt voids the "agent self-directs"
  criterion. The prompt reads like something a normal user would say.
- **A vision-capable model must be available.** The vision path
  (`fetch_vision` / `CRAWLER_VISION_ACTION`) only engages when
  `resolve_vision_client()` can serve: a cloud brain WITH image support, or a
  tier-3 local VL model loaded on GPU. A text-only brain (e.g. gpt-oss-120b)
  makes the whole vision path unreachable by definition â€” that is a config,
  not a spec failure, and the run must be labelled "text-crawl, vision
  unavailable" instead of graded.

Properties the prompt must have:
- Requires real-time data (training data cannot answer it).
- Requires at least TWO distinct sources (forces multi-URL extraction).
- No URL supplied, no tool names mentioned.

## LT-1b â€” Response surface discipline (2026-09-18, owner)
- A short factual answer (a couple of prices + sources) belongs in PLAIN TEXT
  in the chat, not in a prism/markdown document card. A heavy card for a
  one-liner of findings is a format-classification miss â€” record it as a
  finding, not a pass.

## LT-2 â€” Completion criteria (all must hold)

1. **Final answer delivered**: a `chat_message` arrives on the WS with the
   final reply, and the UI shows it in the chat wing.
2. **Grounded, not recalled**: the answer cites facts that match what the
   visited pages contained at run time (spot-check against the URLs below).
   An answer reachable from training data with no browsing is a FAIL.
3. **Agent self-directed URLs**: the backend log or WS events show URLs the
   AGENT chose (search/crawl planner output), not the user prompt. Proof: a
   NEW `data/har/*.har` file (or crawler event log entries) with a timestamp
   inside the test window.
4. **Extraction happened**: at least one extract/read step per visited URL
   (vision `fetch_one`/`read_text` or crawler extraction events).
5. **Clean termination**: the vision loop ends on `model_stop` or a wall ask â€”
   NOT `max_steps`, NOT `guardrail`, NOT `repeat_kind`. The `[vision-timing]
   stage=session` line names the termination cause.
6. **Panel reflection (Verification Plan step 6)**: `CRAWLER_VISION_ACTION`
   events reach the frontend carrying `run_id` + monotonic `seq`; the vision
   actions render in the crawl panel/ambient tier while the run is live.
   Backend events in `.iris-logs/backend-events.jsonl` â‰  panel rendering â€”
   both must be true.
7. **No silent cancellation**: no `client_replace cancelled in-flight thread`
   in the backend log; no WS watchdog reconnect
   (`No frame for Ns ... treating the backend as wedged`) in the browser
   console during the run.

## LT-3 â€” Speed and performance measurables (Verification Plan step 10)

This run ESTABLISHES the baseline (Decision 13: no number is a target until a
baseline exists). Collect all of these; report p50/p95/max.

Instrument: `python scripts/measure_vision_latency.py --log <backend log>`
applied to the test window. Plus WS timestamps and wall clock.

| Metric | How measured | Baseline (fill in) |
|---|---|---|
| Time to first browse action | prompt send â†’ first browser `act`/navigate event | |
| Time to first extracted content | prompt send â†’ first successful extraction | |
| Time to final answer | prompt send â†’ final `chat_message` | |
| Browser acquire: cold | `[vision-timing] stage=browser_acquire cold=True` | |
| Browser acquire: warm | `[vision-timing] stage=browser_acquire warm=True` | |
| Per-stage p50/p95 | acquire, open, screenshot, act, inference, publish | |
| Action cadence | per-step `cadence` signal events | |
| Frame discipline | screenshots taken â‰ˆ page-state changes (REQ-9; one observation per settled state, not one per decision) | |
| Cold/warm split | REQ-18: second run reuses the pool (warm acquire), does not re-launch | |
| Vision autoload cold load (P3, session-342) | empty slot â†’ `load_model` wall time via `[LocalModelManager]` progress events; measured 2026-09-19: 8.5 s after `--no-warmup` + poll-tightening (was 40.2 s) | 8.5 s (cold) |
| Vision autoload residency (P3) | `tasklist/llama-server` count DURING and AFTER an autoloaded run â€” exactly one process, zero orphans | |

Run the SAME prompt twice (fresh conversation each time) to get a cold-then-warm
comparison and guard against a one-off network spike.

## Session-342 live battery results (2026-09-19, brain=ollama gpt-oss:120b-cloud, vision=LFM2.5-VL-3B shared server)

| Run | Prompt class | Outcome |
|---|---|---|
| RTX 5090 two retailers (REST) | planned URLs partially walled | COMPLETE â€” DGXTech $3,998.95 captured; only one retailer found |
| RTX 5090 two retailers (UI) | n/a | 2026-09-19 20:46: answer synthesized with real content; chat bubble carried raw scratchpad (CoT + tool-call JSON) above the actual finding â€” narrated-leak, recorded as pin_8ce139e05652 |
| nvidia.com hero banner | single-site read | PASS â€” "Artificial Intelligence Computing Leadership from NVIDIA" |
| BestBuy price-box screenshot | focused element capture (P5) | HONEST REFUSAL â€” "couldn't fully complete... required work still open". Confirms P5 gap fills pinned in pin_7f840d7702d9 |
| weather.com Toronto high | spinner/settle page | HONEST â€” page showed only placeholder values; agent said so |
| Vercel/Netlify compare | multi-source extraction | ANSWER CORRECT (Pro $20 vs $19, table rendered) but chat bubble carries raw tool-call scratch above the answer â€” same leak class |

New fixed live-behaviors verified this session:
1. `load_model` cold load for the pinned VL model: 40.2 s â†’ **8.5 s** (`--no-warmup` + readiness poll cap 0.5â†’2 s), zero leaked `llama-server` processes after exit.
2. P1 exhaustion discovery trigger (AC9) green on 5/5 coverage tests.
3. P3 empty-slot autoload contract green (6/6); never fires when a model is resident.
4. P6 TTS no-consumer latch green (4/4) â€” the 25 s flood is now one WARN per turn.
5. In-app browser capture pages render styled again â€” `_rewrite_html(html, capture['url'])` before the injector chain (`backend/api/browser_surface.py`), previously relative CSS/images resolved against `/api/browser/capture/â€¦` origin and 404'd (bare-HTML panel).
6. Brain synthesis empty-completion retry (one shot) in `agent_kernel.py` â€” earlier "I've completed the task" receipts on a successful run turned into real answers.

OPEN (not in this session's code pass):
- Chat-vs-content discipline: synthesized answers sometimes carry the raw scratchpad into `content` (see pin_8ce139e05652). This is the chat-communication-lanes work, previously deferred.
- P4 multi-tier combination battery and P5 focused-element capture tool (vision-side, never a crawl path) still pending.

## LT-4 â€” Hard-fail conditions (any one = FAIL, investigation required)

- Vision loop terminates on `max_steps`/`guardrail`/`repeat_kind`.
- A screenshot is taken on EVERY decision step (frame-cache contract broken).
- Same URL fetched twice in one run with no visual-delta justification.
- TTS worker ramps and never unloads; RAM ratchet instead of sawtooth
  (`scripts/mem_watch.py` evidence).
- The final answer precedes the extraction evidence (answer without browsing).
- Phantom success: WS shows success but no `data/har/` entry and no panel
  activity.
- P3 autoload: a resident NON-vision model was evicted mid-turn (log shows a
  load not preceded by an empty-slot decision), OR an autoloaded load leaves
  more than one `llama-server` process alive, OR the autoload exceeds
  `IRIS_VISION_AUTOLOAD_TIMEOUT_S` (default 150 s) without the loud
  unavailable fallback.

## LT-5 â€” Evidence bundle

Save under `screenshots/` (images) and reference from the run pin:
- Baseline orb screenshot; mid-run panel screenshot; final answer screenshot.
- Backend log window for the run (timestamp-bracketed).
- `measure_vision_latency.py --json` output pasted into the run record.
- List of `data/har/*.har` files created inside the window, with timestamps.

## LT-7 â€” VLM capability battery (added 2026-09-18)

The single price-lookup prompt only proves one narrow shape. Once the shared
vision server is live (specs/vision-single-server), run ALL of these as
separate natural prompts (NO tool hints, NO URLs given unless the task is the
navigation itself):

| # | Prompt (natural, as a user would phrase it) | Proves |
|---|---|---|
| B1 | "Search the web for the current price of the RTX 5090 Founders Edition and tell me what two different retailers list it at." | Text-first crawl + 2-source extraction |
| B2 | "Go to nvidia.com and tell me what the hero banner says." | Pure visual read when DOM text is sparse |
| B3 | "Find the Steam store page for Hades 2 and tell me if it's on sale and at what discount." | Page navigation + sale badge (visual) |
| B4 | "Open weather.com and tell me today's high for Toronto." | Form/spinner-heavy page; settle detection |
| B5 | "Compare the pricing sections of vercel.com and netlify.com â€” what does the cheapest paid tier cost on each?" | Multi-page vision + comparison synthesis |
| B6 | (only when a login wall is hit organically) sign-in page handling | takeover ask path (REQ-13..16 surfaces) |

Rules:
- Each run is budgeted â‰¤ 5 min wall clock. Over-budget = finding, investigate.
- Each run must answer from fetched pages, never from the model's priors.
- The VLM must choose WHEN it needs the browser. If it answers from training
  data without any crawl, that run FAILS regardless of answer quality.
- Communication contract applies (specs/chat-communication-lanes): full
  content on the card, chat line supportive and non-duplicative, spoken line
  its own sentence.

## LT-8 â€” Expanded failure battery (session-342, extended 2026-09-19/20)

The original battery asked variations of the same shape. This table splits
failures out so no failure class is hidden behind another run's silence. Run
EACH prompt as a fresh conversation (the chat accumulates turns; a fresh
thread is what proves honesty).

Mark a run OK only if BOTH are true: the final chat answer answers the prompt,
and it does NOT carry raw scratchpad (see F-class column).

| # | Prompt | Targets failure class | Session-342 result |
|---|---|---|---|
| E1 | "Search the web for the current price of the RTX 5090 Founders Edition and name two retailers that list it." | F1/F2/F8 | partial â€” content was real, CoT leaked into the card (pin f8ce139e05652) |
| E2 | "Go to nvidia.com and tell me what the hero banner says." | pure visual read | PASS |
| E3 | "Open weather.com and tell me today's high for Toronto." | F4 spinner/placeholder, F8 | HONEST (page showed placeholders) |
| E4 | "Compare the pricing sections of vercel.com and netlify.com â€” what does the cheapest paid tier cost on each?" | F8 multi-source extraction | ANSWER CORRECT (table right) but scratchpad in chat |
| E5 | "Open earth.nullschool.net and tell me today's jet-stream wind speed at 250 hPa over the North Atlantic." | vision-required visualization | DONE 2026-09-20 â€” honest refusal (no numeric carry-through), tool_decision hit an empty-completion (retry path NOT exercised there â€” the retry covers brain synthesis; the tool-decision path needs the same treatment) |
| E6 | "Search the web for the defcon 2026 badge door prize winner and tell me who won." | F9 â€” answer not on the web | DONE 2026-09-20 â€” honest refusal; run showed AC1 empty-plan discovery DID fire (`disc:` step logged), and `goal-contract` capped the turn with "1 required fact open" instead of fabricating a winner |
| E7 | "Open https://techbloat.com and read the headline under the hero banner." | F2 â€” Cloudflare wall + AC9 discovery | **(fill)** |
| E8 | "Summarize today's top story on theverge.com" | DOM-heavy SPA | **(fill)** |
| E9 | "What is the price of the Framework 13 laptop with no OS?" | single-source extraction | **(fill)** |
| E10 | "Search the web for whether you can still buy Tesla Model S in the UK." | time-sensitive answer + date logic | **(fill)** |

### F-class map (why each run can fail)

| Class | What breaks | Honest response looks like |
|---|---|---|
| F1 | No planner output at all | "No sources produced" + discovery attempt |
| F2 | Every crawled URL returns challenge/empty | Exhaustion discovery (AC9) tries the search engine once more |
| F4 | Page text-only placeholder / spinner | Vision reads the rendered page OR honest "the data was a placeholder" |
| F8 | Sources reachable but do not carry the answer | "The retrieved pages did not list it" â€” no invented figure |
| F9 | The data does not exist on the public web | "I could not find this published; <what was tried>" |
| F10 | Provider empty-completion / timeout | One retry (session-342), then clean degrade, never the frozen template |
| F11 | Leaked reasoning into content | CoT / tool-call JSON visible to the user = fail |

Rules beyond LT-7:
- After ANY HONEST refusal, the run must STILL log the sources attempted (visible in the card or the log window).
- A 429/captcha on the SEARCH ENGINE (Bing default) must park the engine and still answer if any sources were read.
- No turn may end with "I've completed the task" / "1/1 steps finished" as the only answer â€” that is a FAIL.

(run "specs/tool-decision-engine" at end) — summary

## LT-9 — Decision engine production test (session 344)

The engine is baked into the live build, running in SHADOW by default
(`IRIS_DECISION_ENFORCE=""`). This section defines how we measure it in
production and what proves it ready to become the actuating layer.

### Run procedure

1. Backend running with `IRIS_DECISION_ENFORCE` set as:
   - empty = shadow (records all decisions, never acts);
   - `"tool_choice"` = the DE-2 tables start acting;
   - `"tool_choice,presentation,narration"` = all three act.
2. Drive a battery of real prompts (browser / computer-use / coding, fresh thread
   per prompt). Budget: ≤5 min per turn (same rule).
3. Query the ledger after the lap (`data/memory.db → system_events` rows whose
   `interaction_payload` carries `decision`).

### Expected

| Lane | What to see |
|---|---|
| Coverage | Fraction of decisions with `route="engine"` (the rest: escalated / memory / shadow) |
| Accuracy | Among `engine` rows: `final_choice == chosen` (when the join fires) |
| Latency | `engine_latency_ms` should sit in a tight band around ~250-450 ms on a quiet box (CPU). |
| Failoks | Zero rows where the chosen name was NOT in the candidates. |

### Pass standard for flipping the enforce switch

- Lap accuracy ≥ 90% for rows with conf ≥ 0.85 (our offline calibration gave
  92% / 42% coverage; the live run cross-checks it does not exist only in vitro).
- ≥50 distinct lap rows inside one measurement window.
- No phantom-selection failures (chosen ∉ candidates) — ever.

(The instrument `python scripts/calibrate_decision_threshold.py` prints this
report from the ledger directly.)
