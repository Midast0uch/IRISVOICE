"""
IRIS Bootstrap — Session Start
File: IRISVOICE/bootstrap/session_start.py

Run this as the FIRST command of every session and after every context condense.
Reads the coordinate database and prints the current state into the context window.
The agent reads this output to know where it is, what it built, what to avoid.

Usage:
    python bootstrap/session_start.py
    python bootstrap/session_start.py --compact    # shorter output for post-condense
    python bootstrap/session_start.py --gate       # just show current gate status

Roo Code custom instruction:
    Add this to Roo Code's "Custom Instructions" or as the first message:
    "Run python bootstrap/session_start.py before starting any work this session."
"""

import sys
import os
import json
import subprocess

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bootstrap.coordinates import CoordinateStore, LANDMARK_THRESHOLD


def auto_sync_commits(store: CoordinateStore, root_dir: str):
    """
    Scan the last 10 git commits and record any not yet tracked in code_events.
    Uses the commit SHA in the detail JSON field for idempotency —
    re-running session_start never double-records the same commit.

    Fires silently on every UserPromptSubmit so the DB stays current
    without Claude needing to remember to call record_event.py manually.
    """
    try:
        # Get last 10 commits: SHA + subject
        log = subprocess.run(
            ["git", "log", "-10", "--pretty=format:%H|%s"],
            capture_output=True, text=True, cwd=root_dir, timeout=8
        )
        if log.returncode != 0 or not log.stdout.strip():
            return

        commits = []
        for line in log.stdout.strip().splitlines():
            parts = line.split("|", 1)
            if len(parts) == 2:
                commits.append({"sha": parts[0].strip(), "msg": parts[1].strip()})

        if not commits:
            return

        # Fetch already-recorded commit SHAs from detail field
        with store._conn() as conn:
            rows = conn.execute(
                "SELECT detail FROM code_events "
                "WHERE event_type = 'git_commit' AND detail IS NOT NULL"
            ).fetchall()

        recorded_shas = set()
        for row in rows:
            try:
                d = json.loads(row["detail"])
                sha = d.get("commit_sha")
                if sha:
                    recorded_shas.add(sha)
            except Exception:
                pass

        # Record any commits not yet tracked
        for commit in commits:
            sha = commit["sha"]
            msg = commit["msg"]

            if sha in recorded_shas:
                continue  # already tracked — skip

            # Get files changed in this commit
            files_result = subprocess.run(
                ["git", "show", "--name-only", "--pretty=format:", sha],
                capture_output=True, text=True, cwd=root_dir, timeout=8
            )
            changed_files = [
                f.strip() for f in files_result.stdout.strip().splitlines()
                if f.strip()
            ]

            # Record git_commit event with SHA embedded in detail
            store.record_code_event(
                agent_id="auto_sync",
                event_type="git_commit",
                description=msg,
                detail={"commit_sha": sha},
            )

            # Record file_edit for every file in this commit
            for fp in changed_files:
                store.record_code_event(
                    agent_id="auto_sync",
                    event_type="file_edit",
                    description=msg,
                    file_path=fp,
                )

    except Exception:
        pass  # never block session load


def get_current_gate(store: CoordinateStore) -> tuple[int, str]:
    """
    Determine which gate the agent is currently on.
    Returns (gate_number, gate_status_description)
    """
    landmarks = store.get_landmarks(permanent_only=True)
    permanent_names = {lm["name"] for lm in landmarks}

    # Gate 1 — Developer Mode (GOALS.md current gate)
    # Verified manually: start both servers, load GGUF, chat, confirm GPU active
    gate1_ordered = [
        "g1_backend_health",        # /health returns 200
        "g1_frontend_orb",          # frontend loads, orb connects green
        "g1_models_screen",         # ModelsScreen lists GGUFs from ~/.lmstudio/models
        "g1_cuda_verified",         # llama_supports_gpu_offload()=True [DONE 2026-03-31]
        "g1_model_loaded",          # 9B model loads, 25+ tok/s [DONE 2026-03-31]
        "g1_chat_response",         # chat message → reply from local GGUF
        "g1_no_memory_spike",       # backend starts clean, CUDA lazy [DONE 2026-04-05]
        "g1_tool_calling",          # tool calls work with iris_local in session
    ]
    gate1_required = set(gate1_ordered)

    # Gate 2 — Chat/Terminal Hybrid (xterm.js embedded in chat-view)
    gate2_ordered = [
        "g2_xterm_embedded",        # xterm.js renders in chat-view.tsx
        "g2_ws_input_output",       # keystrokes → WS → agent, stream → terminal
        "g2_security_wired",        # security_filter + mcp_security in request path
        "g2_context_management",    # iris_gateway session/persona flows through TUI
        "g2_tool_output_parsed",    # tool_bridge output formatted for terminal stream
    ]
    gate2_required = set(gate2_ordered)

    # Gate 3 — Agent Kernel Upgrade
    gate3_ordered = [
        "g3_der_token_budgets",     # DER loop enforces token budgets per mode
        "g3_trailing_director",     # TrailingDirector wired and active
        "g3_deep_task_stable",      # multi-step tasks complete without context loss
    ]
    gate3_required = set(gate3_ordered)

    # Legacy gate 2 landmarks in step order (old GOALS.md — kept for history)
    _legacy_gate2_ordered = [
        "skills_loader_verified",
        "skill_creator_working",
        "ui_skill_sync",
        "skill_creator_end_to_end",
    ]

    def first_missing(ordered: list, done: set) -> str:
        for name in ordered:
            if name not in done:
                return name
        return "unknown"

    gate1_done = gate1_required.issubset(permanent_names)
    gate2_done = gate2_required.issubset(permanent_names)
    gate3_done = gate3_required.issubset(permanent_names)

    if not gate1_done:
        nxt = first_missing(gate1_ordered, permanent_names)
        return 1, f"GATE 1 — DEVELOPER MODE | Next: {nxt}"

    if not gate2_done:
        nxt = first_missing(gate2_ordered, permanent_names)
        return 2, f"GATE 2 — CHAT/TERMINAL HYBRID | Next: {nxt}"

    if not gate3_done:
        nxt = first_missing(gate3_ordered, permanent_names)
        return 3, f"GATE 3 — AGENT KERNEL UPGRADE | Next: {nxt}"

    return 4, "GATE 4 — MEMORY VISUALIZATION | All prior gates cleared"


def print_full_state(store: CoordinateStore):
    """Full state output for session start."""
    session_count  = store.get_session_count()
    landmarks      = store.get_landmarks()
    permanent      = [l for l in landmarks if l["is_permanent"]]
    developing     = [l for l in landmarks if not l["is_permanent"]]
    warnings       = store.get_active_warnings(session_count)
    contracts      = store.get_active_contracts()
    gate_num, gate_desc = get_current_gate(store)

    # Confidence calculation
    conf = min(0.20 + (len(permanent) * 0.05), 0.95)

    # Maturity
    if len(permanent) == 0:
        maturity = "immature"
    elif len(permanent) < 5:
        maturity = "developing"
    elif len(permanent) < 15:
        maturity = "active"
    else:
        maturity = "mature"

    print("=" * 65)
    print("IRIS BOOTSTRAP — SESSION START")
    print("=" * 65)
    print(f"Sessions completed:  {session_count}")
    print(f"Graph maturity:      {maturity}")
    print(f"Confidence:          {conf:.2f}")
    print(f"Permanent landmarks: {len(permanent)}")
    print()

    # Current gate — most important thing to show
    print(f"CURRENT GATE: {gate_desc}")
    print()

    # Permanent landmarks
    print("PERMANENT LANDMARKS (verified features):")
    if permanent:
        for lm in permanent:
            print(f"  [+] {lm['name']}")
            print(f"      {lm['description'][:70]}")
    else:
        print("  none yet")

    # Developing landmarks
    if developing:
        print()
        print("DEVELOPING (needs more test passes to crystallize):")
        for lm in developing:
            print(
                f"  [~] {lm['name']} "
                f"({lm['pass_count']}/{LANDMARK_THRESHOLD} passes) "
                f"— test: {lm['test_command'][:50]}"
            )

    # Gradient warnings — critical for avoiding past mistakes
    print()
    print("GRADIENT WARNINGS (where you have failed before):")
    if warnings:
        for w in warnings[-8:]:  # last 8 warnings
            print(f"  [{w['space']}] {w['description'][:70]}")
            if w["correction"]:
                print(f"    → worked: {w['correction'][:60]}")
    else:
        print("  none recorded yet")

    # Active contracts
    print()
    print("ACTIVE CONTRACTS (rules from your corrections):")
    if contracts:
        for c in contracts:
            print(f"  [{c['confidence']:.2f}] {c['rule'][:75]}")
    else:
        print("  none yet")

    # Last session summary
    print()
    try:
        with store._conn() as conn:
            last = conn.execute(
                "SELECT * FROM sessions ORDER BY session_number DESC LIMIT 1"
            ).fetchone()
        if last:
            tasks = json.loads(last["tasks_completed"])
            print(f"LAST SESSION ({last['session_number']}):")
            for t in tasks[-3:]:  # last 3 tasks from last session
                print(f"  - {t[:75]}")
    except Exception:
        pass

    # ── Semantic layer — the compressed mathematical state ──────────────────
    # This is the primary navigation signal. Episodic events are secondary.
    # As the graph matures, this section grows more precise while the
    # episodic section below shrinks — exactly as the spec describes.
    try:
        semantic_header = store.get_semantic_header()
        print()
        print(semantic_header)
    except Exception:
        pass

    # Pheromone routes — strongest paths through the codebase graph
    # These are not random — they are the trails that have been reinforced
    # by successful test runs. Follow them. They work.
    try:
        routes = store.get_pheromone_routes(limit=5)
        if routes:
            print()
            print("PHEROMONE ROUTES (strongest reinforced paths — follow these):")
            for r in routes:
                src = r.get("source_path") or r.get("source_id", "?")
                tgt = r.get("target_path") or r.get("target_id", "?")
                w = r.get("weight", 1.0)
                rel = r.get("relationship", "→")
                compound = r.get("compound_count", 0)
                print(f"  [{w:.1f}x/{compound}runs] {src} --{rel}--> {tgt}")
    except Exception:
        pass

    # Topology primitives — what each active file IS right now
    # Not what happened to it — what it IS in the coordinate space
    try:
        with store._conn() as conn:
            hot_files = conn.execute(
                "SELECT file_path, confidence, z_trajectory, activation_count "
                "FROM file_nodes WHERE activation_count >= 2 "
                "ORDER BY activation_count DESC LIMIT 8"
            ).fetchall()
        if hot_files:
            print()
            print("FILE TOPOLOGY (what each file is in coordinate space):")
            for fn in hot_files:
                primitive = store.classify_topology_primitive(fn["file_path"])
                z = fn["z_trajectory"] or 0.0
                conf = fn["confidence"] or 0.0
                z_symbol = "↑" if z > 0.05 else ("↓" if z < -0.05 else "→")
                # Trim path for display
                fp = fn["file_path"]
                if len(fp) > 45:
                    fp = "..." + fp[-42:]
                print(f"  {primitive:12s} {z_symbol} [{conf:.2f}] {fp}")
    except Exception:
        pass

    # High-potential failures — not noise, not dead weight
    # These are failures that carry signal. The next agent should read them
    # before touching the same area. They encode what was tried and why it matters.
    try:
        hpf = store.get_high_potential_failures(limit=3)
        if hpf:
            print()
            print("HIGH-SIGNAL FAILURES (scored >= 0.5 — future success candidates):")
            for e in hpf:
                score = e.get("score", 0)
                fp = e.get("file_path", "")
                print(f"  [score:{score:.2f}] {e['description'][:75]}")
                if fp:
                    print(f"    file: {fp}")
    except Exception:
        pass

    # Episodic layer — recent events (secondary; suppressed as semantic matures)
    try:
        graph_summary = store.get_graph_summary()
        total_ev = graph_summary["total_events"]
        if total_ev > 0:
            print()
            near_cryst = graph_summary.get("near_crystallization", 0)
            hpf_count = graph_summary.get("high_potential_failures", 0)
            print(f"CODE GRAPH: {total_ev} events | "
                  f"{graph_summary['file_nodes']} files | "
                  f"{graph_summary['test_nodes']} tests | "
                  f"{near_cryst} near crystallization | "
                  f"{hpf_count} high-signal failures")
    except Exception:
        pass

    print()
    print("CONTEXT WINDOW REMINDER:")
    print("  Target: stay under 55k tokens")
    print("  At 50-55k: run python bootstrap/mid_session_snapshot.py")
    print("  After condense: run python bootstrap/session_start.py --compact")
    print()
    print("OBJECTIVE ANCHOR:")
    print("  Build IRIS until it runs fully autonomously — receives tasks through its")
    print("=" * 65)
    print()
    print("Read IRISVOICE/bootstrap/GOALS.md for your current gate details.")
    print("Then plan your first task for this session.")
    print()


def print_ultra_compact_state(store: CoordinateStore):
    """
    3-line output for conversational prompts — minimal context cost (~40 tokens).
    Gate + landmark count + objective. Nothing else.
    """
    session_count = store.get_session_count()
    permanent = store.get_landmarks(permanent_only=True)
    gate_num, gate_desc = get_current_gate(store)
    print(f"[IRIS] Gate: {gate_desc} | Landmarks: {len(permanent)} permanent")
    print(f"[IRIS] Objective: Build IRIS until fully autonomous — own interface, own backend, self-improving.")


def print_compact_state(store: CoordinateStore):
    """
    Compact state for after context condense.
    Just the essentials — gate, recent landmarks, active warnings, wiki summary.
    Keeps post-condense context addition small (~600 tokens).
    """
    session_count = store.get_session_count()
    permanent     = store.get_landmarks(permanent_only=True)
    warnings      = store.get_active_warnings(session_count)
    contracts     = store.get_active_contracts()
    gate_num, gate_desc = get_current_gate(store)

    print("--- COORDINATE STATE (post-condense) ---")
    print(f"Gate: {gate_desc}")
    print(f"Permanent landmarks: {len(permanent)}")

    # Only show last 3 permanent landmarks
    if permanent:
        print("Recent:")
        for lm in permanent[-3:]:
            print(f"  [+] {lm['name']}: {lm['description'][:55]}")

    # Only show last 3 warnings
    if warnings:
        print("Warnings (last 3):")
        for w in warnings[-3:]:
            print(f"  [{w['space']}] {w['description'][:60]}")

    # Only show top 2 contracts
    if contracts:
        print("Contracts:")
        for c in contracts[:2]:
            print(f"  {c['rule'][:65]}")

    # PiN summary — count + 2 most recent titles
    try:
        recent_pins = store.get_pins(limit=2)
        all_pins = store.get_pins(limit=1000)
        perm_pins = [p for p in all_pins if p.get("is_permanent")]
        if all_pins:
            print(f"PiNs: {len(all_pins)} ({len(perm_pins)} permanent)")
            for p in recent_pins[:2]:
                perm_flag = " ★" if p.get("is_permanent") else ""
                ptype = p.get("pin_type", "note")
                print(f"  [{p['pin_id'][:8]}]{perm_flag} [{ptype}] {p['title'][:50]}")
    except Exception:
        pass  # pins table may not exist on older DBs

    print(f"Objective: Build IRIS until fully autonomous — own interface, own backend, self-improving.")
    print("--- END COORDINATE STATE ---")
    print()
    print("Continue from where you left off. Check GOALS.md for current gate.")


def print_gate_only(store: CoordinateStore):
    """Just show current gate status — minimal output."""
    gate_num, gate_desc = get_current_gate(store)
    permanent = store.get_landmarks(permanent_only=True)
    print(f"Current gate: {gate_desc}")
    print(f"Permanent landmarks: {len(permanent)}")


if __name__ == "__main__":
    # Check if bootstrap directory exists — Session 1 guard
    db_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "coordinates.db"
    )

    if not os.path.exists(db_path):
        print("=" * 65)
        print("IRIS BOOTSTRAP — FIRST RUN DETECTED")
        print("=" * 65)
        print()
        print("No coordinate database found.")
        print("This is your first session.")
        print()
        print("Your first task: build the coordinate store.")
        print("Read: IRISVOICE/bootstrap/GOALS.md")
        print("Then: python bootstrap/coordinates.py --test")
        print()
        print("Objective: Build IRIS until fully autonomous — own interface, own backend, self-improving.")
        print("=" * 65)
        sys.exit(0)

    store = CoordinateStore(db_path)
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # IRISVOICE/

    # Auto-sync: record any git commits not yet in code_events (idempotent, silent)
    if "--no-sync" not in sys.argv:
        auto_sync_commits(store, root_dir)

    # Decay pass — runs once per session, applies time-based confidence decay
    # to non-landmark nodes. Stale context fades, permanent landmarks never decay.
    # This is what keeps the DB from accumulating stale gate/objective state.
    try:
        import time
        with store._conn() as conn:
            last_decay = conn.execute(
                "SELECT MAX(created_at) FROM code_events WHERE event_type='decay_pass'"
            ).fetchone()[0]
        now = time.time()
        days_since = (now - (last_decay or 0)) / 86400
        if days_since >= 1.0:
            store.run_decay_pass(days_elapsed=max(days_since, 1.0))
            store.record_code_event(
                agent_id="session_start",
                event_type="decay_pass",
                description=f"decay pass: {days_since:.1f} days elapsed",
            )
    except Exception:
        pass  # never block session load

    if "--ultra-compact" in sys.argv:
        print_ultra_compact_state(store)
    elif "--compact" in sys.argv:
        print_compact_state(store)
    elif "--gate" in sys.argv:
        print_gate_only(store)
    else:
        print_full_state(store)