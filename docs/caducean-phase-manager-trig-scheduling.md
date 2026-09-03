# Caducean Phase Manager — Using Trig Functions to Stop Loop Collisions

**Purpose:** Design concept for a separate scheduling layer, owned by the Caducean Engine, that
keeps the sub-loop, outer loop, pacman loop (and any future loop) from firing at the same moment
and tripping rate limits — without any loop needing to know the others exist. This is a concept
document. No code has been written or tested against this idea yet.

---

## 1. The problem, in plain terms

Right now, each loop (sub-loop, outer loop, pacman loop) decides for itself when it's ready to
act. Most of the time that's fine. But because none of them know about each other, there's
nothing stopping all three from deciding "now" at the same moment — and when that happens, you
get a burst of calls all at once. That burst is what's tripping the rate limit. It's not that
you're doing too much work overall — it's that the work is arriving in spikes instead of being
spread out.

This matches how you described it: **a firework, not a stream.** A firework is a lot of energy
released in one instant. A stream is the same energy, moving continuously, never all at once.

There are actually two separate problems bundled together here, and it matters to keep them
apart:

- **Problem A — Collisions.** Loops firing at the same moment as each other. This is a *timing*
  problem — fixable by changing *when* each loop acts, without changing *how much* each loop
  does overall.
- **Problem B — Total volume.** Even perfectly spread out, if the three loops combined want to
  make more calls per minute than the API allows, you'll still get rate-limited eventually. This
  looked at first like a separate *budget* problem needing a different tool — but Section 6 walks
  through why it's actually the other half of the same coupled-oscillator idea, not a bolt-on.

The rest of this document covers both, because both turn out to be expressions of the same
underlying mechanism (Section 9 makes this explicit) — not two unrelated fixes stacked together.

---

## 2. Why trig functions are the right tool here (not just a metaphor)

You already have the core intuition sitting inside your own physics: a Duffing oscillator (your
`u` value) doesn't sit still and doesn't jump discontinuously — it rises and falls smoothly,
circling toward an attractor. What you're describing wanting for your loops — "movement like a
stream of thought" — is the same shape of idea, applied to *when things happen* instead of *what
state something is in*.

Here's the picture: instead of thinking of each loop as "waiting in a queue, then doing a thing,
then waiting again" (a straight line, a row of dominoes), think of each loop as **walking around
the face of a clock** at its own natural pace. Its "phase" is just where it currently is on that
clock face. When its hand crosses a certain mark, it acts. Two loops collide only if their hands
happen to cross the mark at the same moment.

The question becomes: how do you keep several clock hands, each moving at their own natural
speed, from ever landing on the same spot at the same time — **without** hardcoding "loop B, wait
two seconds after loop A"? That hardcoded version is exactly what you're trying to avoid, because
it means every time you add or change a loop, you have to go back and re-tune everyone else's
wait times by hand.

The trig-function answer: let each loop's hand gently *push away* from wherever the other hands
currently are, every tick, by an amount proportional to **the sine of the angular distance
between them.** Sine is the natural tool here for one specific reason — it's exactly the function
that measures "how close are these two positions on a circle," and it naturally goes to zero once
two hands are evenly spread apart, so the pushing gently stops once collisions are no longer
likely. Nobody has to calculate the "correct" spacing in advance — it falls out of the math on
its own.

This general idea (oscillators nudging each other's phase using the sine of their difference) is
a well-studied piece of physics called **phase coupling** (the standard reference model is called
the *Kuramoto model*, if you ever want to search for more on it). Normally, phase coupling is
used to make independent rhythms **lock together** — think fireflies flashing in sync, or two
people unconsciously falling into step while walking side by side. You want the opposite:
**anti-phase coupling**, which uses the same sine-based nudge but with the sign flipped, so
instead of pulling hands together it spreads them apart — evenly around the clock face, like
runners naturally spacing themselves out on a track instead of bunching up. This spread-out
result is sometimes called a "splay state" in the literature — it's a known, stable outcome of
this exact math, not a hopeful guess.

---

## 3. Why this belongs as a separate Caducean layer, not inside each loop

This is the part that directly answers your modularity concern, and it's worth being explicit
about, because it's the whole point of doing it this way.

If you hardcode timing logic into each loop — "check what the sub-loop is doing, then decide" —
every loop ends up needing to know about every other loop. Add a fourth loop later, and you're
back in every existing loop's code, changing things. That's the opposite of modular.

The trig-based fix avoids this because **the sine-coupling math doesn't care what a loop *is*.**
It only needs two things from each loop:
- A natural rhythm (how often it *wants* to act, left entirely up to the loop itself)
- A phase (its current position on the clock face, which the manager tracks *for* it)

That means a loop never needs to know any other loop exists. It just does two things:
1. **Registers once** with the manager: "here's roughly how often I want to act."
2. **Asks the manager** at decision time: "is it my turn?"

Everything about *avoiding collisions* — the sine nudges, the spreading-out, the rebalancing when
a loop is added or removed — lives entirely inside the manager. This is precisely why it should
be a separate layer owned by the Caducean Engine, sitting above all the loops rather than woven
into any one of them: it's the one place that's allowed to know all the loops exist, so nowhere
else has to.

This also fits naturally with how Caducean already treats itself as the governance layer for
agent behavior rather than part of any one behavior — you'd just be extending that same
governance role from "when should reasoning stop" to "when should each loop be allowed to act."

---

## 4. What the manager actually needs to do (conceptually)

Four responsibilities, each simple on its own:

1. **Onboarding.** When a loop first appears, give it a phase position (can be random, or spaced
   evenly among however many loops already exist) and remember its natural rhythm.
2. **Nudging.** On a regular tick, adjust every registered loop's phase very slightly, pushing it
   away from whichever other loops are currently nearby in phase — using the sine-of-the-
   difference idea from Section 2. Loops far apart in phase barely get nudged at all; loops that
   are dangerously close get nudged more.
3. **Gating.** When a loop asks "is it my turn," the manager checks whether that loop's phase has
   reached its firing point. If yes, allow it and reset that loop's countdown toward the next
   cycle. If not, tell it to wait a little.
4. **Rebalancing on change.** When a loop is added or removed, the manager doesn't need any
   special-case logic — the same nudging rule in step 2 naturally re-spreads everyone over the
   next few ticks, because the sine term automatically responds to however many phases currently
   exist.

Nothing in this list requires the manager to understand what a "sub-loop" or "pacman loop"
*does* — only where it currently sits in phase and how often it wants to turn. That's what keeps
it generic enough to manage loops you haven't built yet.

---

## 5. How this could layer on top of what already exists

This doesn't need to replace anything already discussed — it slots in one level above it:

- The **growth-width rule** (deciding whether a step is atomic or needs to split) still runs
  entirely inside a loop, using that loop's own `u`/`ξ` state. The phase manager doesn't touch
  that decision at all.
- The phase manager only decides **when a loop is allowed to check in and act**, not **what it
  does once it's allowed to.** Think of it as traffic-light timing versus driving — the lights
  decide when you can go, not where you're driving to.
- A loop's own confidence or urgency (its `u` value, or however "ready to act" is measured
  internally) could optionally *widen or narrow* its firing window at the manager level — a loop
  that's very confident could be allowed a slightly earlier gate-check, without needing to know
  anything about the other loops it might be competing with for a slot. That's an optional
  refinement, not a requirement for the basic version to work.

---

## 6. Volume — the other half of the same oscillator, not a separate mechanism

Earlier drafts of this idea treated timing and volume as two different problems needing two
different tools: sine-based phase spacing for collisions, plus a plain shared counter (a token
bucket) bolted on next to it for total volume. That was an unnecessary split. A correction is
worth making explicit here: **anti-phase coupling doesn't mean the loops stop being coupled** —
the sine-of-the-difference nudge *is* the coupling, just tuned to push apart instead of pull
together. The loops are still one connected, mutually-responsive system throughout this whole
document, not independent agents that happen to avoid each other.

That matters here because a full oscillator was never just an angle. It's a rotating arrow, with
two properties: a **direction** (phase, θ — used for timing in Sections 2–5) and a **length**
(amplitude, r — unused so far). Amplitude is the natural home for volume, and it can be coupled
to the other loops' amplitudes the exact same way phase is coupled to their positions — no second
mechanism required.

**The picture:** think of a choir. Anti-phase coupling on phase is what keeps singers from all
taking a breath at the same instant — still one performance, still listening to each other, just
staggered so there's always sound instead of gaps or floods. Amplitude is each singer's own
volume. A choir doesn't need a hard rule capping how many people may sing loudly at once —
singers naturally ease off when the room is already loud, and swell back up when there's room.
That's not a separate rule from the listening-to-each-other relationship; it's the same
relationship, expressed as loudness instead of timing.

**Concretely:** each loop's amplitude represents how large a request it's currently allowed to
make (or how eagerly it fires within its phase window). Amplitude couples to a single shared
quantity — total volume currently being drawn across every registered loop — the same generic way
phases couple to each other's positions. When the shared total rises, every loop's amplitude
eases down smoothly. When there's headroom, amplitudes drift back up. No loop checks a counter or
asks permission; the manager tracks one shared "how full is the room" number, and every loop's
amplitude quietly responds to it.

This isn't a stretch from the physics already underpinning this whole engine — it's already
sitting in the Duffing law you started from. `u` doesn't only have a direction of change; it has
a natural amplitude that self-limits at the attractors (`u* = ±1`). This engine already runs on a
self-limiting-amplitude system. Extending that same idea — an amplitude that settles toward a
shared, dynamically-adjusting ceiling instead of a fixed cap — makes volume management part of
the *same* coupled-oscillator model as the phase-spacing, rather than a second, separate mechanism
sitting next to it. Phase handles collisions; amplitude handles volume; both are the same kind of
coupling, just measured on different properties of the same rotating arrow.

A flat hard ceiling (a literal, non-negotiable maximum request count) can still sit underneath
this as a last-resort safety rail — the same way your Duffing system still has `DER_EMERGENCY_STOP`
as a hard backstop even though the physics is meant to self-regulate long before that point is
reached. The amplitude coupling is what should do the actual day-to-day regulating; the hard cap
is what catches it if the coupling itself is ever mistuned.

---

## 7. Batching sub-loop children — compression is already the decoupling point

This connects to something already built, and it's worth being explicit about why it works,
because it's the reason "batch the sub-loop" isn't just possible but a natural fit rather than a
bolt-on.

**Batching and parallel firing are opposites, worth separating clearly:** parallel means several
separate calls happening at the same moment (more collisions — the exact problem Section 1
describes). Batching means grouping several pieces of independent work into *one* call instead of
several (fewer calls total). It's the difference between five cars leaving at once versus five
people carpooling in one car. Only batching helps with total call volume; only the phase manager
(Sections 2–4) helps with timing collisions. They solve different halves of the same problem and
don't conflict.

**Why sub-loop children are the right candidate for batching, specifically:** when growth-width
splits a step into children, those children don't report their individual progress back to the
parent in real time. The parent never had that dependency to begin with — the whole point of the
Sub-Loop collapsing back into a single `COMPRESS` observation, and of MCM folding a bloated run
into one compact NBL string, is that **the parent's only contract is "give me the finished,
compressed result whenever it's ready."** It was never watching the children work step by step.

That matters a great deal for batching, because it means the parent genuinely cannot tell the
difference between two scenarios:
- Three children run one at a time, each finishing and folding into the compressed result
  separately, or
- Three children run together as one batched dispatch, and their combined result folds into the
  compressed result once, together.

Either way, the parent experiences exactly one thing: the compression step resolving and handing
back a signal. **The compression boundary is already the seam where batching can happen for free**
— it was already the single point of re-entry into the parent's flow, so grouping what happens
before that point doesn't introduce a new place where anything has to stop and wait. This is what
makes "nothing needs to stop, motion stays continuous" true in a concrete sense, not just a nice
image: the parent was always going to wait on compression, never on individual children, so
batching the children doesn't add a wait — it just changes what's happening during the wait that
was already there.

**The one condition that still applies, unchanged from before:** children can only be batched
together if they're genuinely independent of each other (don't need each other's results first).
Compression being the re-entry point doesn't change that — it's about *how results rejoin the
parent*, not permission to batch children that actually depend on one another.

**How this slots into the phase manager, without breaking its modularity:** the manager doesn't
need to specifically understand "sub-loops" as a category to support this. It only needs one more
small fact at registration time: which compression join-point a given loop reports to, and
whether it's marked independent of its siblings under that same join-point. With that, the
manager can notice when several independent children are converging on the same phase window and
route them as one batched dispatch instead of several individually-gated turns — the same generic
mechanism would work for any future loop that also happens to report into a shared compression
point, not just the sub-loop specifically.

**An honest tension worth watching, not resolved here:** compression is currently designed to
fire as soon as a child is ready — a fast child shouldn't have to sit and wait for a slow sibling
just to be grouped into a batch. If batching is applied too eagerly, it could reintroduce exactly
the kind of stall this whole approach is trying to avoid — a fast result held hostage to a slower
one for the sake of grouping. The safer version is almost certainly *bounded* batching: only group
children whose phase windows (from Section 4's gating) were already going to land close together
anyway, rather than forcing artificial synchronization on children that would otherwise finish
independently. That's a tuning decision for implementation, not something this document resolves.

---

## 8. Honest caveats

- This is a design concept, not a validated one. The core math (sine-based anti-phase coupling
  producing a stable, evenly-spread "splay state") is well established in the general oscillator
  literature, but it hasn't been tested against your actual loops' real timing behavior.
- The "coupling strength" (how hard the manager nudges phases apart per tick) needs to be tuned —
  too strong, and phases can overshoot and oscillate around each other instead of settling; too
  weak, and it won't meaningfully reduce collisions within a reasonable number of ticks. This
  would need empirical tuning against your actual call patterns, not a value assumed in advance.
- This document does not specify where in the codebase this manager would live, how "phase
  ticks" would be driven (a background timer? piggybacked on an existing loop's cycle?), or how
  it would interact with the Sub-Loop's existing nested-session lifecycle. Those are open
  implementation questions, not answered here on purpose — this is meant to establish the concept
  before committing to placement.
- The bounded-batching idea in Section 7 (only group children whose phase windows already land
  close together) is a proposed safeguard, not a tested one. Getting the "how close is close
  enough to batch" boundary wrong in either direction either loses most of the batching benefit
  (too strict) or reintroduces the fast-child-waiting-on-slow-sibling stall (too loose).

---

## 9. The underlying principle, stated plainly

Sections 2 through 7 aren't really separate tricks. They're the same one idea, applied to
several properties: **compress everything that happened before into one honest current position,
and let moment-to-moment behavior be a pure, memory-free reaction to that one position.**

- The **phase** (Sections 2–4) is the stateful part — it's a running total, built up tick by tick
  from everything that came before. It only exists because of history.
- The **amplitude** (Section 6) is the same kind of stateful running total, just measured on
  volume instead of timing — it only exists because of how much has recently been drawn across
  every loop.
- **What a loop does once it knows its phase and amplitude** — check the sine of the distance to
  its neighbors, ease its own volume up or down — is completely stateless. It doesn't need
  yesterday's phase or last week's total. It only needs the two numbers it's standing on right
  now.

State gets *concentrated* into a position and a magnitude. Behavior at that position and
magnitude doesn't need to look backward at all.

One more thing worth being precise about, since it's the correction that led here: none of this
means the loops stop relating to each other once collisions and volume are under control. The
coupling **is** the mechanism, in both directions — anti-phase coupling on timing, shared-total
coupling on volume. It's a feature the whole system runs on, not scaffolding that gets removed
once things are stable. The loops staying genuinely coupled to each other is *how* motion stays
continuous — it's not something to be minimized once collisions stop.

This isn't a new idea being introduced into IRISVOICE — it's a pattern already trusted elsewhere
in the system, just not yet pointed at scheduling:

- **NBL already does this.** An entire messy session — every step, every tool call — gets
  compressed into one compact coordinate string. Once the NBL exists, nothing downstream needs
  the play-by-play; it reacts to that one compact position, statelessly.
- **The Duffing law already does this, for both properties.** `F(u) = 2u − 2u³` doesn't know or
  care about the trajectory that got `u` to its current value — it only reacts to where `u` is
  right now. And `u` already self-limits toward its attractors (`u* = ±1`) the same way Section 6
  proposes amplitude should self-limit toward a shared, moving ceiling instead of a fixed one.

The phase manager is the same split, applied to *when* and *how much* a loop is allowed to act,
rather than *what* it does or *how resolved* it is: two stateful positions, tracked centrally and
kept genuinely coupled to each other, paired with a stateless reaction rule that only ever needs
to look at those positions — never the history behind them. That's the actual reason this
approach feels like the right shape for "in motion, not a firework": it's not handling
statefulness and statelessness as two things happening at once, it's routing each one to the
layer that's supposed to carry it, while keeping the coupling between loops intact throughout.
