# Requirements: CLM Memory (context the model can manage)

Status: NEW spec, 2026-10-28. Predecessor: `specs/memory-recall-reach` (finalized).
Source design: `docs/Design/CLM_MYCELIUM_DESIGN_BRIEF.md` (Phases 1-5).
Owner: Midas. Audience: the implementing agent.

## Why this spec exists

A normal model only appends to its context. A CLM treats the context as something the
model owns and may rewrite, so the live window stretches and shrinks while the record
stays complete. The recall spec prepared the memory for this in one specific way: three
addressable levels (thread → episode → chunk), one codec, incidence to the phase plane,
and an immutable record layer. That ground exists and is measured.

This spec builds the other half: the editable view on top of that record.

## Decisions Locked

- **Mycelium is the source of truth; CLM is fitted to it** (brief §0). Do not migrate,
  flatten or replace any existing store or path.
- **No file-based context.** Where the paper writes a context file and greps it, IRIS
  writes to the record and recalls by coordinate. The live view is a DERIVED view, never
  a file on disk.
- **Two halves of the rubber band**: shrink/stretch is the CLM's job; "where everything
  was" is already Mycelium's. This spec builds only the first.
- **No new dependency without the owner.** CPU only. One writer (`db.app_write`).
  Everything that is not needed by the current reply runs on a lane.
- **Policy does not live in an instruction document** (brief §0 rule 7). Behavior comes
  from memory mechanics, landmarks and recorded outcomes.
- **The benchmark is part of done.** Each wave lands with its measurement; a wave that
  cannot show its number is not finished.
- **Prepared ground is not re-litigated**: two planes (REQ-10), the codec (REQ-4 of the
  recall spec), the Kyudo decay law (REQ-5), the three levels (REQ-11).

## Requirements

### CLM-1: The live view is a derived, editable representation
**User Story:** As IRIS I want to own the window I am thinking in, so I can keep what
matters for this task and drop what does not.

- CLM-1.1 WHEN a turn begins THE SYSTEM SHALL assemble the live view from the record
  (recall + recent turns), not from a mutable file.
- CLM-1.2 THE SYSTEM SHALL represent every block in the view by a stable identifier that
  resolves back to the record (chunk id, chain entry, or level row).
- CLM-1.3 WHEN the model edits the view THE SYSTEM SHALL record the edit as an event in
  the immutable chain, so history never depends on the view's current shape.
- CLM-1.4 THE SYSTEM SHALL never let an edit delete from the record.

### CLM-2: Offload is a placeholder, not a loss
- CLM-2.1 WHEN a block leaves the view THE SYSTEM SHALL leave a one-line placeholder
  carrying its coordinate, its time frame, its domain and a reason it mattered.
- CLM-2.2 THE SYSTEM SHALL enforce offload BEFORE the drop in the harness. Measurement
  in the brief (§5.2) shows backups do not happen unless something enforces them.
- CLM-2.3 WHEN a placeholder is re-expanded THE SYSTEM SHALL return the original block by
  coordinate, not a summary of it.
- CLM-2.4 IF a placeholder cannot resolve (row pruned) THEN THE SYSTEM SHALL say so in
  the view rather than silently return nothing. (File chunks are re-ingestable from disk
  while the hash matches; say which case it is.)

### CLM-3: Model-written summaries are pins with provenance
- CLM-3.1 WHEN the model summarises THE SYSTEM SHALL store a pin: author (model),
  timestamp, the coordinates of the raw material, and the claim text.
- CLM-3.2 A pin SHALL never be treated as more authoritative than its sources, and SHALL
  be distinguishable from raw record in the view.
- CLM-3.3 WHEN a pin re-enters the view THE SYSTEM SHALL frame it as reference data,
  never as instructions.
- CLM-3.4 THE SYSTEM SHALL keep pins out of the authority path for landmarks: a
  model-written pin is a candidate, never a landmark (brief §7.9).

### CLM-4: The gauge is real
- CLM-4.1 THE SYSTEM SHALL report current tokens against the budget to the model in tool
  results, using the ACTIVE backend's tokenizer (Anthropic / OpenAI-compatible /
  llama.cpp are all supported).
- CLM-4.2 THE SYSTEM SHALL remind shortly before the limit (the paper uses 2,048 tokens).
- CLM-4.3 THE SYSTEM SHALL NOT assume one tokenizer; a wrong gauge is worse than none.

### CLM-5: Recent-to-past, with open items carried forward
- CLM-5.1 THE SYSTEM SHALL keep recent material verbatim, middle material as a pin or
  ledger line, and past material as placeholders only.
- CLM-5.2 NOTHING SHALL leave the view until it is in the record, a placeholder exists,
  and every open item in it is carried forward.
- CLM-5.3 THE SYSTEM SHALL keep a dead-end ledger; a negative result is knowledge.
- CLM-5.4 THE SYSTEM SHALL re-stretch on three triggers: the task touches a landmark, an
  error matches a past event, or the agent is about to repeat a known dead end.

### CLM-6: Safety
- CLM-6.1 The record SHALL be append-only and never model-editable.
- CLM-6.2 The model SHALL NOT edit its own system prompt or instructions in the same loop
  that uses them.
- CLM-6.3 THE SYSTEM SHALL be able to audit a pin against its sources on demand.

### CLM-7: Measurement (the spec's completion test)
- CLM-7.1 A ContextBench-style suite: exact recall of a value offloaded N turns ago;
  counting/lookup over offloaded logs; keep-specific-delete-filler; in-place update of a
  state block.
- CLM-7.2 The rubber-band test the paper does NOT cover: recall by TIME FRAME and by
  DOMAIN ("what did we decide about auth last week?"), graded on what reaches the view.
- CLM-7.3 Report: premature eviction (dropped then needed), re-recall cost, repeated
  dead-end actions, stale-landmark use, wrong-landmark rate.
- CLM-7.4 Edit cost on the serving backend: tokens re-processed after a mid-view edit
  versus an append. Do not assume SCR.

## Out of Scope
- Reinforcement learning and prompt evolution (brief §12: reference only).
- The SGLang Suffix-Cache patch (not portable to this stack).
- Multi-agent live views and the coordinator tracker (brief Phase 5; after single-agent
  works and is measured).
- Any change to the two planes, the codec, or the decay law.

## Inherited Ground (must not be rebuilt)
`thread_context` (8,098 threads, 17.7x smaller scan), `episodes` with int8 + fingerprint
(362 rows), chunk codec (int8 + 128 B fingerprint), incidence by `thread_id`, the chain as
the ordered path, `memory_chain`/landmarks/pins as the record, lanes + `app_write` as the
one writer, and the recall path at recall@10_live 0.86/0.9458/0.87 (1.0 on the turn path
against shipped truth).
