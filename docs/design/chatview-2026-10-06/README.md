# Chat view design — 2026-10-06 (owner-approved concept)

| File | What | Status |
|---|---|---|
| `iris-strands.html` | **Concept 2 "IRIS Living Spine", revision 3 — APPROVED by the owner 2026-10-06.** The target look and behaviour for the chat view in both modes. | approved (https://claude.ai/artifact/CDss9BFHkf4QdqMS7ZsSwD) |
| `iris-dashboard.html` | **Concept 2 rev 4 "Dashboard Spine"** — the dashboard built from the chat's parts: one `◉` menu, a spine rail, settings rows with value summaries, the Apply bar, the Workspace hub with a Views lane, and the `#` / `@` reference rules. | proposed 2026-10-06, waiting for the owner (https://claude.ai/artifact/1vMLK38PPrNDJGiJaNJ8jR) |
| `iris-braid.html` | Concept 1 "IRIS Braid and Spine". Kept as a reference at the owner's request. | reference |
| `chatview-split.html` | The first glimpse: one turn stream drawn in both modes, the file split map, the part types. | reference |

Open the HTML files in a browser (self-contained; fonts from Google Fonts).

## What the owner approved (concept 2, rev 3)

- **Threads and strands.** A thread is the whole; each chat under it is a *strand*. Strands are named by the user; preset tags (plan, build, research, people, swarm) plus the user's own tags. One strand may hold planning, building, a swarm and `@person`. All strands of a thread share one memory. Swarms / sub-agents get their own strand and report back to the strand that started them.
- **Header.** Xur (opens the thread orbit) · thread name (rename in place) · current strand under it (no dropdown arrow) · `⌖` opens the strand map (strand switcher; dot when another strand works) · `◉` menu (dashboard, detach, alerts, launcher, close).
- **Thread orbit.** Click the Xur: threads sit on the Xur's loops; pinned threads keep the lower loops; scroll to turn; type to find. No dropdown container.
- **Edge light.** Each wing's top edge is one hairline with the spotlight aperture set into it at the top middle (same position as today; no box). A slow light leaves the aperture (every ~7 s idle; ~2.6 s in the working strand's colour); in spotlight the line stays lit near the aperture. Same edge on the dashboard.
- **Spotlight** keeps today's behaviour: the spotlit wing 680 px; the other 360 px, opacity 0.3, saturate(0.6) blur(2px), no pointer events.
- **The spine.** The Xur's own particle trail runs down the left of every strand; the agent Xur rides it to the step that runs (both modes; in personal mode the spine bends into the task card and becomes its step line). Knots only where something enters from outside the strand (another strand's id, another agent, another person, helpers reporting back). No landmarks shown. Conversation chips live on the spine: hover for the list, click to jump, drag to scrub.
- **Brand colour.** The Xur takes three neighbouring hues from the brand hue (never one flat colour).
- **Task card.** Personal mode keeps the vertical card with every event (progress rail, goal, steps with summaries and ✓, live actions, failure reason + "tried again", memory footer, card id). Plain words: "looked closer" (sub-loop), "done" (converged), "reported back" (fold-back); no landmarks.
- **Developer matrix.** Rows are born, run (scanning shimmer), fold; parallel rows get light from the Xur; `↳ looked closer` chambers fold to one line.
- **Diffs.** A `±` icon where an edit happens; review per hunk (Keep / Undo); Undo restores the file AND tells IRIS the change was not wanted; drag a diff to the dashboard workspace like an artifact.
- **Composer.** `to:` chip (who hears this; with people only `@iris` sends a prompt) · `#` references (task card, artifact, strand turn — addresses, never content) · project bar above the message box in both modes (folder, open files, `+` folder/repo, branch) · steer while IRIS works · stop button. No mic button (voice stays wake-word).
- **Lens.** Artifacts open inside the wing; pop out or drag to the dashboard workspace.
- **Dashboard** restyled in the same ink with the same edge and trail.
