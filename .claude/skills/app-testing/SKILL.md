---
name: app-testing
description: Live-test and validate IRIS Voice changes. Mode A (primary for any agent, DER, physics or latency change) is the measured eval loop — run real tasks through the real backend with evals/run_evals.py, read pass + reply_s, find stalls with in-process stack dumps and query plans, fix the cause, prove it, guard it as a standard. Mode B is UI-driven testing of the widget. Use when validating any change, live-testing the app, or orienting for the first time.
---

# App Testing — IRIS Voice (pointer)

The skill has ONE source file, shared with OpenCode agents:

**Read `.opencode/skills/app-testing/SKILL.md` (repo root) now and follow it.**

Edit only that file. This pointer exists so Claude Code discovers the skill by name;
duplicating the content here would let the two copies drift.
