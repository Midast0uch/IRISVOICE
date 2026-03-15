# CLAUDE.md — Project Instructions for IRISVOICE

## Spec Execute Mode

When the user says **"spec execute"**, **"execute spec"**, **"implement spec"**, or **"start implementation"** followed by a spec name (e.g., `iris-mycelium-layer`), enter Spec Execute Mode:

### Workflow

1. **Load the spec.** Read ALL files in `.kilo/specs/{spec-name}/`:
   - `requirements.md` — the SHALL statements (source of truth)
   - `design*.md` — all design documents (architecture reference)
   - `tasks.md` — the implementation plan (your execution guide)

2. **Find your position.** Scan `tasks.md` for the first `<!-- status: pending -->` marker — that is your next task. Tasks already marked `<!-- status: done: ... -->` are complete. Resume from the first `pending` task.

3. **Execute one task at a time.** For each task:
   - Change its marker to `<!-- status: in_progress -->` before starting
   - Read the task's **Details** section completely before writing any code
   - Read the referenced **Requirements** (`_Requirements: X.Y_`) from `requirements.md`
   - Read the referenced design section if the task touches architecture
   - Read EVERY existing file listed in **Files to modify** before editing
   - Implement exactly what the task specifies — no more, no less
   - Run the relevant test after implementation if tests exist for that phase
   - Mark the task complete: change the marker to `<!-- status: done: {one-line summary} -->`

4. **Phase gates.** At the end of each Phase:
   - Report: which tasks completed, any deviations from spec
   - Continue immediately to the next phase — do NOT stop for confirmation
   - ONLY stop and ask the user when a critical ambiguity or blocking issue is encountered that the spec does not resolve

5. **Verification at each task:**
   - Every constant MUST match the value in `requirements.md` and `design*.md` — never invent values
   - Every file path MUST match what `tasks.md` specifies
   - Every class/method signature MUST match the design doc
   - If a task says "read the file carefully first" — you MUST read it before editing

### Rules

- **Never skip a task.** Tasks are ordered by dependency. Skipping breaks later phases.
- **Never implement ahead.** Do not write code for Phase N+1 while executing Phase N.
- **Never guess.** If a task is ambiguous, check `requirements.md` and `design*.md`. If still ambiguous, ask the user.
- **Never simplify.** Implement the full specification. No "we can add this later" shortcuts.
- **One task per message cycle.** Complete the task, mark it done, report, then move to the next.
- **Respect the single-agent context.** If `tasks.md` says a component is "built but not wired," build it without callers.
- **Use existing patterns.** Read adjacent files in the codebase to match coding style, import patterns, and error handling conventions.

### Progress Tracking Format

Each task heading in `tasks.md` has a status comment on the next line:
```markdown
### Task 1.1: Create `mycelium/` package scaffold
<!-- status: pending -->
```

When starting a task, change to:
```markdown
<!-- status: in_progress -->
```

When completing a task, change to:
```markdown
<!-- status: done: Created package with __init__.py exporting MyceliumInterface -->
```

**Finding your position:** Search for the first `<!-- status: pending -->` — that's your next task. All `done:` tasks above it are complete.

### Reporting Format

After each task, report:
```
✅ Task {N.M}: {task title}
   Files: {created/modified}
   Requirements verified: {X.Y, X.Z}
   Tests: {pass/fail/not-yet}
   Notes: {any deviations or observations}
```

After each phase:
```
📦 Phase {N} Complete: {phase title}
   Tasks: {completed}/{total}
   Files created: {list}
   Files modified: {list}
   All tests passing: {yes/no}
   Ready for Phase {N+1}?
```

---

## Project Context

- **Database:** SQLCipher-encrypted `data/memory.db`. One shared connection per process — modules never open their own connections.
- **Test location:** `IRISVOICE/backend/memory/tests/`
- **Package root:** `IRISVOICE/backend/memory/`
- **Spec location:** `.kilo/specs/{spec-name}/`
- **Existing specs (completed):** `iris-memory-foundation`, `iris-mcp-integration`, `iris-id-structure-cleanup`
- **Current spec (ready):** `iris-mycelium-layer` — 33 tasks across 12 phases

## Code Standards

- Python 3.10+ (match existing codebase)
- Type hints on all public methods
- Docstrings on all classes and public methods
- Constants defined once in the canonical location, imported elsewhere
- `try/except` wrapping on all Mycelium operations that could block existing memory operations
- Comments in English
- No `print()` — use `logging` module
