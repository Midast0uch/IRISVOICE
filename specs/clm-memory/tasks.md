# Tasks: CLM Memory

Waves are ordered so each one is measurable on its own and none blocks the recall work.
The predecessor spec (`memory-recall-reach`) is closed; this spec owns the view.

## Wave 1 — Gauge + edit trail (no view editing yet)
- [ ] T1 (CLM-1.3, CLM-4): record the live view's shape each turn as a chain event
  (`VIEW_EDITED` / `VIEW_ASSEMBLED`) and report tokens vs budget with the ACTIVE
  backend's tokenizer. Metric: gauge error vs the real tokenizer on 20 turns; event
  count per turn. Why first: every later wave needs to know what the view was.
- [ ] T2 (CLM-1.1/1.2): make every injected block carry its stable id (chunk id, chain
  entry, level row). Metric: 100% of injected blocks resolve back to a row.

## Wave 2 — Offload + placeholder + re-expand
- [ ] T3 (CLM-2.1): placeholder format (coordinate, time frame, domain, reason).
- [ ] T4 (CLM-2.2): harness-enforced offload before drop. Metric: offloaded blocks that
  were NOT in the record = 0 (this is the brief's §5.2 finding turned into a gate).
- [ ] T5 (CLM-2.3/2.4): re-expand by coordinate; explicit "cannot resolve" path.
  Metric: re-expansion returns the ORIGINAL text byte-for-byte, and the pruned case is
  counted, not silent.
- [ ] T6 (CLM-7.1): ContextBench analogues (KV store, log triage, needle retention,
  sketchpad). Metric: per-task pass, graded from what reaches the view.

## Wave 3 — Pins with provenance
- [ ] T7 (CLM-3.1): pin write path with author + source coordinates. Note: `mycelium_pins`
  exists with 0 rows; `pin_store.py` is the app surface - pick one, do not add a third.
- [ ] T8 (CLM-3.2/3.3): distinguishability + reference-data framing on re-entry.
  Metric: a pin is never rendered in the instruction block; assertion test.
- [ ] T9 (CLM-3.4, CLM-6.3): pins never promote a landmark; audit a pin against sources.
  Metric: promotions from pins = 0; audit returns the source set.

## Wave 4 — Recent-to-past + dead-end ledger
- [ ] T10 (CLM-5.1/5.2): zones, open-item carry-forward, the "nothing leaves until"
  gate. Metric: open items lost = 0 over a 10-turn replay.
- [ ] T11 (CLM-5.3): dead-end ledger. Metric: repeated dead-end actions before/after.
- [ ] T12 (CLM-5.4): three re-stretch triggers. Metric: re-stretch fired when it should
  (recall of the right coordinate), and not fired when it should not.

## Wave 5 — The rubber-band measurement (the completion test)
- [ ] T13 (CLM-7.2): time-frame and domain recall. Metric: precision of the coordinate
  returned for "last week / auth" style questions.
- [ ] T14 (CLM-7.3): the counter set (premature eviction, re-recall cost, stale landmark,
  wrong landmark).
- [ ] T15 (CLM-7.4): edit cost on the serving backend, mid-view vs append. Metric: tokens
  re-processed, measured - do not assume SCR.

## Wave 6 — Multi-agent (only after Waves 1-5 are measured)
- [ ] T16 (brief §7.8): per-agent views + coordinator tracker, mapped onto the existing
  DER loop rather than a parallel orchestration.

## Dependency notes
- Wave 2 needs Wave 1's ids; Wave 4 needs Wave 2's placeholders; Wave 5 needs 1-4.
- Wave 3 is independent of 2 and can run in parallel.
- Do NOT touch: the chunk codec, the two planes, the decay law, `recall_reach`/`episodic`
  scoring (all owned and closed by the recall spec).
- A flag is not done: every wave's metric runs live before the wave closes.

## Open questions for the implementing agent (answer from the code first)
1. Where does the live view actually get assembled per backend today (DCP + the kernel's
   `_build_context`), and can an editable layer sit there without touching the planner?
2. Does `dcp.py` already drop blocks, and does it leave anything behind? (If it silently
   drops, wave 2 starts there.)
3. Which tokenizer per backend is authoritative, and is it already loaded?
4. `pin_store.py` vs `mycelium_pins` (0 rows): which is the app's pin surface?
5. What is the chain's existing label vocabulary for a view edit - can we add labels
   without adding values (event alphabet rule)?
