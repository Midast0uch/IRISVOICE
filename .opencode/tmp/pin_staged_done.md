# PENDING PIN — record via pin_add when the MCM server returns

(Staged 2026-09-09: the mcm-cad server disconnected mid-session-312, so this
pin could not be written to the graph. Record verbatim via pin_add on server
return, then delete this file.)

pin_add(
  title="Session 312 finding: awareness mechanisms exist but are unwired at gather decisions — successful redundant fetches, broken cache promise, DCP off hot path",
  type="decision",
  tags=["session-312", "conv-99", "gather-gate", "FAULTLINE", "DCP", "websearch"],
  content="""
LIVE FINDING (conv-99, 6:40 turn): planner emitted 3 overlapping gather steps;
SourceRegistry served the SAME 4 URLs to all 3 (topic-coverage bleed — Parakeet
query matched whisper.cpp URLs); orchestrator re-fetched every page fresh 3x
(52-59s each, fresh HAR each run); turn ended in deterministic fallback with
raw crawl text dumped into the response card. Explorer escalation died on
NameError: `_der_finalize_step` references QueueItem without importing it
(import lives in the DER-loop function only).

ROOT PATTERN — mechanism-without-consumer, three instances:
(1) SUCCESSFUL redundant fetch: FAULTLINE wall ledger covers FAILURES only;
    GitHub answered 200 so no wall lesson formed; nothing compares registry
    known_urls (gather gate agent_kernel.py:12151) against already-crawled
    URLs. The gather gate tracks QUERY digests (_der_crawl_attempts), not
    URLs — paraphrased queries never match (qkey_in_attempted=False all run).
(2) BROKEN D6 promise: gather gate comment says same-query repeats are
    cache-served reads ("no provider call is paid") — JobRegistry stores
    completed results with TTL but nothing serves them on repeat dispatch;
    CrawlPlanner cache HIT caches URL LIST only; pages re-fetch at full price.
(3) DCP UNWIRED: backend/agent/dcp.py is real (3 passes, window-derived
    budget) but only called from MCM dcp_prune action + swarm context_control.
    Neither runs on the DER context-assembly path; conversation memory hit
    71.5k/64k with no pruner watching. (Correction: the final synthesis prompt
    is already bounded at 6000 chars/step via session-247 get_results_summary
    cap — the synthesis Empty is the provider-empty disease, now seen at 4
    call sites across conv-96/97/98/99, NOT proven window-blowout.)

DESIGN RULE (user-principle, recorded): at no point may the agent repeat a
step or tool call without knowing it, absent genuine failure or misaligned
results. A cache promise without a consumer is decoration — the gather
decision must consult what the agent already knows (URLs fetched this turn,
queries asked, window fullness) BEFORE dispatching. Successful fetches need
memory too, not just failures.

FIX LIST (aligned+verified): (1) QueueItem import one-liner; (2) URL-level
turn memory at the gather gate — filter registry known_urls against completed
JobRegistry jobs for the conversation; all-filtered -> steer to read/synthesis
instead of re-dispatch; (3) honor the D6 promise: serve same-query repeats
from JobRegistry completed results (tool_bridge.py:2405 site); (4) ONE
transport-level Empty-retry in transport.py:840 (covers all 4 empty call
sites at once) + wire DCP into DER context assembly; (5) fallback report
renders envelope summaries with line breaks, never raw crawl text (cramped
card, conv-99).
"""
)
