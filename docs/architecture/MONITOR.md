# Monitor page

One page, `components/dashboard/MonitorPage.tsx`, replaces the old Monitor tab
(Analytics | Logs | Diagnostics, plus the developer-only DCP block) and the
Inference console sub-app. Owner rule (2026-10-06): the two held the same
content, so nothing is shown twice. Look: `docs/design/chatview-2026-10-06/
iris-dashboard.html` (`monitor` rows: orb, name, one-line live summary; open =
fields under a lit hairline).

Rows, in order: **Now**, **Inference stream**, **Usage**, **Logs**,
**Diagnostics**, and **Context** (developer mode only).

Data lives in `components/dashboard/monitor/useMonitorData.ts`, one hook per
source. Every value on the page is read from exactly one hook.

## Inventory of the old surfaces

Source: WS = message re-dispatched by `useIRISWebSocket` as `iris:ws_message`.

| Item | Old place | Source | Duplicate of | Now |
|---|---|---|---|---|
| Active model (last loaded) | Console summary bar | WS `model_load_event` | Debug Info "Reasoning model / Tool model" | Now, one row per profile, from `model_load_event` only. Debug lines removed. |
| Average tok/s | Console summary bar | WS `inference_event` (session mean) | | Now ("Average speed") |
| Last call tok/s + latency | Console stream line | WS `inference_event` | | Now ("Speed"), and in the stream line |
| Session tokens | Console summary bar | `inference_event` sum | Analytics "Total Tokens" (same quantity) | Dropped; Usage "Tokens" (store-backed) is the one |
| Stream: calls and loads | Console log area | `inference_event`, `model_load_event` | Analytics "Recent Activity" (same calls, from the usage store); Logs call lines | Inference stream only |
| Filter all / inference / load | Console | local | | Stream "Show": all / calls / loads |
| Pause, auto-scroll, export, clear | Console | local | | Stream controls (pause freezes the list; Now keeps following) |
| Total tokens, prompt/completion split | Analytics | WS `monitor_analytics_data` (poll 10 s) | Console "Tokens" | Usage "Tokens" |
| Total calls, audio tokens | Analytics | same | Latency "Count" (same number) | Usage "Calls"; Latency "Count" dropped |
| Estimated cost, session minutes | Analytics | same | | Usage |
| Avg latency card | Analytics | same | Latency Distribution "Avg" | Dropped; Usage "Latency, average" |
| Latency min / p50 / p95 / max | Analytics | same | | Usage (4 rows) |
| Model breakdown (tokens, %, cost) | Analytics | same | | Usage, one row per model with a bar |
| Recent Activity list | Analytics | same | Stream calls | Dropped; the stream is the one list of calls |
| System Output lines | Logs | WS `update_field system_logs` | | Logs (one list) |
| Error Stream lines | Logs | WS `update_field error_logs` | (disjoint from System Output; backend splits by level) | Logs, same list; the ERROR / WARNING chips replace the second panel |
| Model-call and model-load log lines | Logs | same | Stream events for the same calls | Hidden in Logs (see below) |
| Level chips, search, auto-scroll, refresh | Logs | local | | Logs controls |
| System Health checks | Diagnostics | WS `update_field system_health` | | Diagnostics |
| Issues & Warnings | Diagnostics | `update_field troubleshoot` | `ERROR/WARN [component]: ...` lines repeat a health check row | Only lines not tied to a listed check stay |
| Debug Info | Diagnostics | `update_field debug_info` | "Reasoning model", "Tool model" repeat Now | Those two lines removed; the rest stays |
| Refresh / run checks | Diagnostics | `confirm_card diagnostics` | | "Run checks" |
| DCP counters, last pass | DCPStatsPanel | window `iris:dcp_pruned` | | Context row (developer mode) |

## How model-call lines are detected in Logs

`isModelCallLine` (in `useMonitorData.ts`) matches the message start. These
backend lines describe the same call or load the stream already shows:

- `[InferenceRouter] call done ...` (one per model call, `router.py`)
- `[Timing] process_text_message ...` (one per streamed turn, `iris_gateway.py`)
- `[LocalModelManager] Model unloaded` / `In-process model unloaded|released`

Logs shows "N model-call lines hidden; they are in the Inference stream" when
any are hidden, so the filter is never silent. A new backend line that mirrors a
stream event needs one more alternative in that regex; the test
`a streamed call shows in the stream and NOT in Logs` pins the three above.

## Behaviour notes

- Logs and Diagnostics read the backend the first time their row opens (the
  diagnostics handler runs process and GPU probes). Usage polls every 10 s while
  the page is mounted, as the Analytics tab did.
- The stream and Now are fed by live events, as the console was. Events that
  arrive while the Monitor tab is not mounted are not kept. "Now" says
  "no load seen" (not "none loaded") until a load event arrives.
- `open_inference_console` (card action) and `initialSubApp: 'inference_console'`
  (from `app/page.tsx`) open the Monitor tab with the Inference stream row open.
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
