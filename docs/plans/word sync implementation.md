# Word Highlight Sync via Chunk-Duration Distribution

## Problem Statement

Word highlighting in the TTS playback UI is currently advancing on an independent
timing mechanism (e.g. a fixed-rate scheduler or average-speaking-rate estimate)
rather than being derived from the actual audio being played. This causes
highlight progress to desynchronize from audio progress, typically finishing far
ahead of the audio because the estimated pace doesn't match true playback pace,
and any error compounds over the length of the response since nothing
re-anchors the two clocks together.

## Root Cause

There are two clocks in play that must be one and the same:

1. The **audio clock** — the actual elapsed playback time of the TTS audio.
2. The **highlight clock** — whatever mechanism currently advances which word is
   highlighted.

If these are implemented as two separate timers, they will never stay in sync,
because there is no periodic correction. The fix is architectural, not
cosmetic: the highlight state must be a *read* of the audio clock, never an
independent *write*.

## Solution Overview

Replace the independent highlight timer with a two-part system:

1. **Word Timing Table** — built once per audio chunk, mapping each word to a
   `(start_time, end_time)` range in seconds, relative to the full stream.
2. **Playback Position Lookup** — on every UI update tick, read the actual
   current playback position from the audio pipeline, then look up which
   word's range contains that position, and highlight only that word.

No forced alignment model, no ASR pass, no additional model load on GPU or
CPU. The word timing table is derived entirely from data already available at
the point each chunk finishes synthesizing: the chunk's text and its audio
sample data.

## Part 1: Building the Word Timing Table

This happens once per chunk, immediately after that chunk's audio finishes
generating (in the producer side of the existing producer-consumer queue), not
during playback.

### 1.1 Determine chunk duration (ground truth, not estimated)

Every chunk of synthesized audio has a known sample count and a known sample
rate. Duration in seconds is derived directly from these two values. This
number must come from the actual generated audio object for that chunk, not
from any prior estimate.

### 1.2 Determine chunk start offset in the overall stream

Maintain a running total of seconds accounted for by all previously processed
chunks. The current chunk's start offset in the full response is equal to that
running total. After processing the current chunk, add its duration to the
running total before moving to the next chunk. This total must be tracked
per-response and reset at the start of each new TTS response.

### 1.3 Tokenize the chunk's text into words, preserving character spans

Split the chunk's source text (the exact text that was sent to the TTS engine
for that chunk — not the LLM's raw streaming text, which may not correspond
1:1 if there is any preprocessing) into words. For each word, record its start
and end character index within the chunk's text string. Punctuation attached
to a word (e.g. trailing commas or periods) should be included in that word's
span so no characters fall outside every word's range.

### 1.4 Assign a time-weight to each character (or syllable group)

For each unit (character, or better, syllable group — see 1.5), assign a
proportional weight representing how much of the chunk's total duration that
unit should consume. If using flat character-count weighting, every character
gets equal weight. If using syllable weighting, each syllable group gets equal
weight and characters within silent/consonant clusters inherit their parent
syllable's weight.

Sum the weights of all units in the chunk to get a total weight. Each unit's
allocated duration = (unit's weight / total weight) × chunk duration.

### 1.5 Prefer syllable-based weighting over character-count weighting

Character count alone systematically misrepresents speaking duration —
short/common words speak faster per character than their length implies, and
long words with consonant clusters speak faster per character than vowel-heavy
words. A lightweight heuristic (grouping consecutive vowel characters into
syllable units, with sensible handling of silent trailing "e" and common
diphthongs) produces meaningfully better timing without requiring any real
phonetic model. This heuristic should be implemented as an isolated, testable
utility function so its accuracy can be iterated on independently of the rest
of the pipeline.

### 1.6 Compute per-word start/end times

Walk through each word's character span, sum the allocated durations of the
units within that span, and accumulate a running clock starting from the
chunk's start offset (from 1.2). This produces, for every word in the chunk:

- `word_text`
- `start_time` (absolute seconds from the beginning of the full response)
- `end_time` (absolute seconds from the beginning of the full response)

### 1.7 Append to a per-response word timing table

Each chunk's word entries get appended, in order, to a single growing list
covering the entire response (not just the current chunk). This list is what
the playback side will query against. Because chunks are processed in the
producer as they're generated, this table should be available slightly ahead
of when that chunk actually begins playing — verify this holds given the
existing queue's buffering depth, and if the first chunk's table isn't ready
before playback of chunk 1 begins, that specific chunk may need to fall back
to a naive even-split estimate rather than blocking playback start.

## Part 2: Driving Highlighting from Playback Position

This replaces whatever currently advances the highlighted word.

### 2.1 Read actual playback position, not elapsed wall-clock time

On each animation/update tick, query the actual current playback position from
the audio playback layer (the real position within the currently playing
audio, in seconds, relative to the same absolute response-start reference used
when building the timing table in 1.2). This must be the authoritative
position from the playback engine itself, not a value computed by adding up
"time since chunk started playing" in application code, since that is exactly
the kind of independent clock that caused the original desync.

### 2.2 Look up the current word from the timing table

Given the current playback position, find the word entry in the per-response
timing table whose `start_time <= position < end_time`. That word is the one
that should be highlighted. If position falls in a gap between two words'
ranges (can happen due to rounding), highlight whichever word's range ends
closest to the current position, or the next upcoming word — pick one
consistent rule and apply it uniformly.

### 2.3 No independent advancement logic anywhere

Audit the current highlight implementation for any code path that advances the
highlighted word index based on elapsed time, timers, or per-word delay
constants. All such logic should be removed and replaced entirely by the
lookup in 2.2. If any fallback timer-based logic remains for edge cases (e.g.
before the first chunk's table is ready), it must be clearly scoped and
temporary, never running concurrently with the table-based lookup for the same
segment of audio.

### 2.4 Handle chunk boundaries transparently

Because the timing table is built per-response (not per-chunk) with absolute
start/end times, the lookup logic in 2.2 does not need any special-case
handling when playback crosses from one chunk's audio into the next — the
table already accounts for chunk start offsets. Confirm the audio playback
layer's reported position is also continuous across chunk boundaries (i.e. it
doesn't reset to 0 at the start of each new chunk); if it does reset per chunk,
that reset must be corrected for by adding the chunk's start offset before
using the position in the lookup.

## Validation Checklist

- [ ] Word timing table entries are built from actual chunk audio duration
  (samples / sample rate), not from any estimated speaking rate.
- [ ] Running duration total correctly resets at the start of each new
  response and accumulates correctly across chunks within one response.
- [ ] Every character in each chunk's text falls within exactly one word's
  span (no gaps, no overlaps).
- [ ] Syllable-weighting utility is isolated and independently testable.
- [ ] Highlighting is driven exclusively by querying real playback position
  every tick — verify by deliberately testing with variable playback rates
  (e.g. temporarily testing at a different rate) and confirming highlighting
  stays in sync (this would fail immediately if any old timer-based logic
  remained).
- [ ] No code path advances the highlighted word based on elapsed wall-clock
  time or fixed per-word delays.
- [ ] Playback position used in lookup is continuous across chunk boundaries,
  correcting for any per-chunk reset if the audio layer resets position at
  chunk start.
- [ ] First-chunk edge case (timing table not yet ready before playback
  starts) has an explicit, documented fallback behavior.
