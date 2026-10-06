# Monitor page

One page, `components/dashboard/MonitorPage.tsx`, replaces the old Monitor tab
(Analytics | Logs | Diagnostics, plus the developer-only DCP block) and the
Inference console sub-app. Owner rule (2026-10-06): the two held the same
content, so nothing is shown twice. Look: `docs/design/chatview-2026-10-06/
iris-dashboard.html` (`Monitor = an instrument panel`). The first build used
settings-style rows (orb, name, summary); the owner said that look does not fit
live data, so the page is an instrument panel: a tile strip and panes.

## Layout

A 12-column grid. The page root is the CSS size container, so under 600 px of
width every pane spans the full width and the tiles go 2 x 2.

| Area (`data-area`) | Span | Holds |
|---|---|---|
| `now` (tile strip) | 12 | Reasoning model, Tool model (name, loaded dot; any other profile shows in the Tool tile note), Speed (last call tok/s, sparkline of the last 24 calls, last latency, session average), Reply time (median call latency, p95 beneath) |
| `stream` | 7 | Live dot (grey when paused), filter all / calls / loads, Pause / Resume, Auto-scroll, Export, Clear. Fixed-layout table: time, model, tokens in -> out, latency bar and seconds. Loads are muted rows. Per-call tok/s is the row tooltip |
| `usage` | 5 | Refresh. Tokens with prompt / completion split, calls, estimated cost, session minutes, latency average and range, one bar per model |
| `logs` | 7 | Level chips (ALL, ERROR, WARNING, INFO, DEBUG), search, Auto-scroll, Refresh. Terminal-like lines (time, level, text) and the note "N model-call lines are in the stream, not here" |
| `diagnostics` | 5 | Run checks. Status list: ● ok, ◐ warning, ✕ error, ○ idle, with the check message and latency on the right; issues and warnings not tied to a listed check; debug lines |
| `context` (developer mode only) | 12 | DCP counters and the last pass |

Shown as "—" or a plain note when the data is not there: Reply time before the
first usage reply (`latency.count` is 0), the model tiles before a load event,
Speed before a call. Not built, because no data source exists: the concept's
hourly token chart (the usage payload has totals and per-model rows, no time
series) and its turns done / failed bar (no such counter in any payload). The
concept shows p90; the usage payload carries p95, so the tile shows p95.

Panes are always on screen, so nothing opens or closes. `openRow`
(`open_inference_console`, `initialSubApp: 'inference_console'`) scrolls the
named pane into view and focuses it; the scroll is not animated under reduced
motion. The row-in highlight on new stream rows is also off under reduced
motion.

Data lives in `components/dashboard/monitor/useMonitorData.ts`, one hook per
source. Every value on the page is read from exactly one hook.

## Inventory of the old surfaces

Source: WS = message re-dispatched by `useIRISWebSocket` as `iris:ws_message`.

| Item | Old place | Source | Duplicate of | Now |
|---|---|---|---|---|
| Active model (last loaded) | Console summary bar | WS `model_load_event` | Debug Info "Reasoning model / Tool model" | Now, one tile per profile, from `model_load_event` only. Debug lines removed. |
| Average tok/s | Console summary bar | WS `inference_event` (session mean) | | Speed tile (small line: "avg") |
| Last call tok/s + latency | Console stream line | WS `inference_event` | | Speed tile (big number, sparkline), and in the stream row tooltip |
| Session tokens | Console summary bar | `inference_event` sum | Analytics "Total Tokens" (same quantity) | Dropped; Usage "Tokens" (store-backed) is the one |
| Stream: calls and loads | Console log area | `inference_event`, `model_load_event` | Analytics "Recent Activity" (same calls, from the usage store); Logs call lines | Inference stream only |
| Filter all / inference / load | Console | local | | Stream "Show": all / calls / loads |
| Pause, auto-scroll, export, clear | Console | local | | Stream controls (pause freezes the list; the tiles keep following) |
| Total tokens, prompt/completion split | Analytics | WS `monitor_analytics_data` (poll 10 s) | Console "Tokens" | Usage "Tokens" |
| Total calls, audio tokens | Analytics | same | Latency "Count" (same number) | Usage "Calls"; Latency "Count" dropped |
| Estimated cost, session minutes | Analytics | same | | Usage |
| Avg latency card | Analytics | same | Latency Distribution "Avg" | Dropped; Usage "Latency, average" |
| Latency min / p50 / p95 / max | Analytics | same | | Reply time tile (p50, p95); Usage keeps average and min to max |
| Model breakdown (tokens, %, cost) | Analytics | same | | Usage, one line per model with a bar |
| Recent Activity list | Analytics | same | Stream calls | Dropped; the stream is the one list of calls |
| System Output lines | Logs | WS `update_field system_logs` | | Logs (one list) |
| Error Stream lines | Logs | WS `update_field error_logs` | (disjoint from System Output; backend splits by level) | Logs, same list; the ERROR / WARNING chips replace the second panel |
| Model-call and model-load log lines | Logs | same | Stream events for the same calls | Hidden in Logs (see below) |
| Level chips, search, auto-scroll, refresh | Logs | local | | Logs controls |
| System Health checks | Diagnostics | WS `update_field system_health` | | Diagnostics |
| Issues & Warnings | Diagnostics | `update_field troubleshoot` | `ERROR/WARN [component]: ...` lines repeat a health check row | Only lines not tied to a listed check stay |
| Debug Info | Diagnostics | `update_field debug_info` | "Reasoning model", "Tool model" repeat Now | Those two lines removed; the rest stays |
| Refresh / run checks | Diagnostics | `confirm_card diagnostics` | | "Run checks" |
| DCP counters, last pass | DCPStatsPanel | window `iris:dcp_pruned` | | Context pane (developer mode) |

## How model-call lines are detected in Logs

`isModelCallLine` (in `useMonitorData.ts`) matches the message start. These
backend lines describe the same call or load the stream already shows:

- `[InferenceRouter] call done ...` (one per model call, `router.py`)
- `[Timing] process_text_message ...` (one per streamed turn, `iris_gateway.py`)
- `[LocalModelManager] Model unloaded` / `In-process model unloaded|released`

Logs shows "N model-call lines are in the stream, not here" when
any are hidden, so the filter is never silent. A new backend line that mirrors a
stream event needs one more alternative in that regex; the test
`a streamed call shows in the stream and NOT in Logs` pins the three above.

## Behaviour notes

- Logs and Diagnostics read the backend the first time their pane is on screen
  (IntersectionObserver; the diagnostics handler runs process and GPU probes).
  Where the observer does not exist they read at once. Usage polls every 10 s
  while the page is mounted, as the Analytics tab did.
- The stream and the tiles are fed by live events, as the console was. Events
  that arrive while the Monitor tab is not mounted are not kept. A model tile
  says "no load seen" (not "none loaded") until a load event arrives.
- `open_inference_console` (card action) and `initialSubApp: 'inference_console'`
  (from `app/page.tsx`) open the Monitor tab and focus the Inference stream pane.
  `handleSubAppChange('inference_console')` keeps working for any other caller.
  The backend only mentions the name in comments and in the unused
  `core_models.py` enum value.

## Files

- New: `components/dashboard/MonitorPage.tsx`, `components/dashboard/monitor/useMonitorData.ts`,
  `.iris-mon-*` CSS (`css-src/globals.css` and `public/globals.css`),
  `__tests__/monitor/`.
- No longer imported by the app, removable once the owner agrees:
  `components/dashboard/MonitorTabContainer.tsx`, `MonitorAnalyticsPanel.tsx`,
  `MonitorLogsPanel.tsx`, `MonitorDiagnosticsPanel.tsx`,
  `InferenceConsolePanel.tsx`, `components/dev/DCPStatsPanel.tsx`. Two existing
  tests still `jest.mock` three of them by path
  (`__tests__/components/dark-glass-dashboard.apply.test.tsx`,
  `model-status-badge.test.tsx`), so delete the files together with those lines.
