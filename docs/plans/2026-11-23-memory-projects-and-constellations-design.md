# Memory surface: projects, and the inside of the galaxies — design

Date: 2026-11-23 · Owner decisions: "Lens + record at source"; inside = A (constellations) as the base, with
B (moons) and C (flowing light) for movement. Belongs to W4 of
`docs/Design/Memory-Cortex/LIVE-CONTEXT-AND-GALAXY-PLAN.md` (galaxy cortex, behind `?cortex=galaxy`).

## 1. Why

The galaxies sort the memory by MEANING (one galaxy per domain). The owner's question: where does the work of
OTHER projects go — IRIS working on itself, an app being built, an MCP server being built or used? Measured
2026-11-23 on the live store:

- `conversations.project_id`: empty on all 1,137 conversations.
- `project_registry` (memory.db): 0 rows; no code writes it.
- `kernel.active_project_id`: read by `_multiagent_tags`, never set.
- A claim keeps no project; only eval claims carry one inside their text ("The project is in <folder>. <task>").

So today a project's work is mixed into the topic galaxies and cannot be separated afterwards. The fix is at the
source first, the view second.

## 2. Two axes

Domain = what the work is about. Project = where the work happened. A web-search claim made while building an MCP
server belongs to both. The galaxies stay the domain axis; projects are a LENS across them (option A of the
brainstorm): choosing a project lights its claims and constellations in every galaxy and dims the rest. Nothing
moves, so the map stays stable, and one project's spread across topics is visible.

Rejected: projects as their own regions (B: a second set of objects in a full space); projects as galaxies with
domains inside (C: inverts the map, splits a shared topic across projects).

## 3. Record at the source

One resolver, `backend/memory/projects.py`:

- `project_of(folder)` -> `{id, name, path, kind}` or None. Walks up from the folder (at most 8 levels, never to
  the home folder or a drive root) to the first root marker: `.git`, `package.json`, `pyproject.toml`,
  `Cargo.toml`, `go.mod`, `setup.py`. No marker -> None (a loose file is not a project).
  - `kind = "iris"` when the root is the IRIS repo (or its self-edit sandbox worktree).
  - `kind = "mcp"` when the root's name or its manifest names MCP (`mcp` in the folder name, or
    `@modelcontextprotocol` / `mcp` in package.json / pyproject.toml dependencies).
  - else `kind = "app"`.
  - `id = "proj_" + sha1(normcase(root))[:12]`: stable, one per folder. Bounded LRU cache (256 roots).
- `note(conversation_id, project)`: on the `projects` lane (one ordered writer, never inline):
  upsert `project_registry` (name, path, kind, last_active) through `db.app_write`, and stamp
  `conversations.project_id` when it is still empty (the first project a conversation works in names it).

The chokepoint is the tool bridge (every tool call passes there): a file tool or `run_command` resolves its folder
(an absolute path's folder; a relative path against the session workdir, else the backend's own folder = IRIS).
The bridge keeps the last project per session, so the lane is only touched when the project changes.
`set_session_workdir` (the folder the user or the DevOrchestrator binds) notes the folder too.

A claim keeps its project at birth: `claim_finding` adds `project` ({id, name, kind}) from the conversation's
project, else from its own tool targets. It survives the deletion of the chat (387 of 389 chats are gone).

MCP servers being USED: IRIS's MCP servers today are all its own (browser, file_manager, vision, github, ...), so
there is nothing external to register yet. When an external server is connected, it registers with
`kind = "mcp"` the same way (no new axis).

## 4. Serve and show

Snapshot: `projects: [{id, name, kind, path, claims}]` and `landmark.project` per claim. A claim's project, in
order: its finding's project; its conversation's `project_id`; for old claims, the folder named in its text
("The project is in <folder>.") resolved WITHOUT touching the disk (`project_of(path, probe=False)`: the folder
itself is the root), marked `inferred`.

Surface:
- A "projects" control in the inside nav bar: IRIS itself · apps · MCP servers · everything, with claim counts.
- Choosing one sets a lens: claims, constellations and moons of that project stay bright; all else dims to 15%.
  The timeline and corridors are out of scope for this step (NOT THIS below).
- The claim card names its project ("in IRIS itself", "in <app>", "an MCP server: <name>").
- IRIS's own work: the nucleus warms slightly while the IRIS lens is on (the one touch of B).

## 5. The inside of a galaxy (A + B + C)

- A · Constellations. Each star system's claims are joined by the minimum spanning tree of their positions (Prim,
  per system, O(n²) on small n): thin, clean lines, the shape of the group. They replace the always-on hyphae
  inside, which crossed and tangled. The real claim links (hyphae) show only for the hovered or selected claim
  and when a recall walks them (the pulse).
- Clickable vs not. A claim (clickable) sends a slow sonar ping: a thin ring that grows and fades every few
  seconds, its phase its own. Stars, dust and filaments never ping and never ring. Hover still rings white.
- B · Moons. Pins orbit their star system slowly (one turn in about two minutes, each its own radius and
  phase), on the CPU so hover and click stay exact (at most 80 pins).
- C · Flowing light. Light travels outward along each constellation from its sun (by hop depth), slow; a group
  used recently flows faster. Galaxies turn slowly (differential: inner faster).

## 6. Done / not this

DONE = a new conversation that works in a folder stamps its project; the registry has the row; a new claim's
finding carries the project; the snapshot serves projects and per-claim projects (old claims inferred); the
inside shows constellations, pings, orbiting moons and flowing light; the project lens dims all other claims;
fps stays >= 28 at DPR 1 (whole view) — measured live.

NOT THIS = a project editor or rename UI; per-project galaxies; a timeline or corridor project filter; a disk
scan to backfill old claims; a new event family; external MCP connection support.

## 7. Tests

Contract (`backend/tests/contract/test_project_record_contract.py`): the resolver (root markers, iris/mcp/app,
no marker -> None, never the home folder); `note` writes the registry and stamps an empty conversation only;
`claim_finding` carries the project; the snapshot serves `projects` and `landmark.project` (finding, conversation,
inferred). Each fails on the code before the change. Visual parts: live check in the built-in browser + fps.

## 8. Changes made while building (owner feedback, 2026-11-23)

- **Claims are seeds of the weave.** Rings read as buttons, and lit planets did not belong. A claim is the shell's own weave
  in little: finished weave = proven, one family woven from below = learning, loose = new, frayed = fading. Its shape is
  the kind of WORK (`claim_work`: code, web, you, run, built, files, words); the old kind (coordinate space) was one value
  for 283 of 389 claims. A two-row legend is always on screen inside a galaxy; a click keeps one kind.
- **No claim covers another.** A group is sized by its count and its claims are pushed apart in 3D (median spacing in the
  densest galaxy 0.028 -> 0.083 of its radius); a claim is never drawn wider than its nearest-neighbour room; near the
  pointer the claims spread (a radial monotone fisheye, so the nearest claim stays nearest and picking is unchanged).
- **Galaxy rotation dropped**: hover and click must stay exact. Movement = beads on the threads, light along the
  constellations, moons, the aurora.
- **The card answers a reader's questions** (`GET /claims/{id}/story`): can it be trusted, what it found, how, its track
  record, every connected conversation. Measured: the source chat is kept for 2 of 389 claims, 252 have events in memory
  for a conversation that taught or proved them; with the conversations that USED a claim almost every claim opens one.
- **Any conversation opens in the timeline** (`GET /thread-model/{id}`), not only the snapshot's 48 newest; one whose chat
  is gone is told from its events and runs. A pin opens the conversation it is from.
- **The aurora follows the lemon** (great circles of its own profile, colour drifting along the ribbon and in time).
  Domain names rest 2.6 s after the last pointer move. The key and projects toggles are two small icons.
- **Projects, live gate found two bugs the unit tests missed**: the direct answer path never told the tool bridge its
  conversation, and the bridge de-duplicated per session (the app has one session for every chat). Both fixed and pinned;
  live: conv-10866 -> its app's project. Evaluation workspaces are never projects; a worktree of IRIS is IRIS by its
  `.git` file, not its name.
- GPU cost outside, per layer (hide one, sync read, 16 rounds): aurora 0.1 ms, claims and constellations nothing measurable.
