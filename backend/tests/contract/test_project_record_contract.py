"""Projects are recorded at the source (owner 2026-11-23, "Lens + record at source").

Measured before: every conversation's project_id empty (1,137), project_registry 0 rows, no claim knew its project -
the work of another app or an MCP server was mixed into the topic galaxies for good. Now one resolver names a
folder's project (iris / app / mcp), the tool bridge notes it on the `projects` lane (registry + conversation), a new
claim keeps it, and the snapshot serves it to the surface's project lens.
Design: docs/plans/2026-11-23-memory-projects-and-constellations-design.md.

Each test FAILS on the code before this change (no backend.memory.projects, no set_project_if_empty, no project in
the finding, no "projects" in the snapshot).
"""
from __future__ import annotations

import json
import sqlite3
from types import SimpleNamespace

from backend.tests.contract.test_memory_api_contract import NOW, env  # noqa: F401  (the fixture)


def _proj(tmp_path, name, manifest=None, body=""):
    d = tmp_path / name
    (d / "src").mkdir(parents=True)
    (d / (manifest or "pyproject.toml")).write_text(body, encoding="utf-8")
    (d / "src" / "main.py").write_text("x = 1\n", encoding="utf-8")
    return d


def test_the_resolver_names_a_folder_s_project(tmp_path):
    from backend.memory import projects

    app = _proj(tmp_path, "notes_app", body='[project]\nname = "notes"\ndependencies = ["requests"]\n')
    srv = _proj(tmp_path, "weather", "package.json", '{"dependencies": {"@modelcontextprotocol/sdk": "1.0"}}')
    dep = _proj(tmp_path, "tools_srv", body='[project]\ndependencies = ["mcp>=1.2"]\n')
    named = _proj(tmp_path, "files-mcp")
    loose = tmp_path / "loose"
    loose.mkdir()

    a = projects.project_of(str(app / "src"))
    assert a["kind"] == "app" and a["name"] == "notes_app" and a["id"].startswith("proj_")
    assert projects.project_of(str(app / "src" / "main.py"))["id"] == a["id"]          # a file: its folder's project
    assert projects.project_of(str(app)) == a                                         # one id per folder
    assert projects.project_of(str(srv))["kind"] == "mcp"                              # an MCP server being built
    assert projects.project_of(str(dep))["kind"] == "mcp"
    assert projects.project_of(str(named))["kind"] == "mcp"
    assert projects.project_of(str(_proj(tmp_path / "iris-evals", "c05"))) is None      # an evaluation's workspace is not
    assert projects.project_of(str(loose)) is None                                    # a loose folder is not a project
    assert projects.project_of(str(__import__("pathlib").Path.home())) is None         # never the home folder

    iris = projects.project_of(projects.IRIS_ROOT)
    assert iris["kind"] == "iris" and iris["name"] == "IRIS"
    assert projects.project_of_path("backend/main.py")["id"] == iris["id"]             # relative: the backend's folder
    assert projects.project_of_path("src/main.py", str(app))["id"] == a["id"]          # relative: the session workdir
    wt = tmp_path / "sandbox-wt"                                                       # IRIS's self-edit worktree is IRIS
    wt.mkdir()
    (wt / ".git").write_text("gitdir: " + projects.IRIS_ROOT.replace("\\", "/") + "/.git/worktrees/sandbox-wt", encoding="utf-8")
    assert projects.project_of(str(wt)) == iris
    assert projects.project_of(str(_proj(tmp_path, "irisvoice-site")))["kind"] == "app"  # a name is not proof
    gone = projects.project_of(r"Z:\no\such\demo_app", probe=False)                    # old claims: no disk walk
    assert gone["name"] == "demo_app" and gone["kind"] == "app"


def test_a_note_writes_the_registry_and_names_an_empty_conversation_once(env, tmp_path, monkeypatch):  # noqa: F811
    from backend.memory import projects

    mem = sqlite3.connect(":memory:", check_same_thread=False)
    monkeypatch.setattr(projects, "_store_conn", lambda: mem)
    app, other = _proj(tmp_path, "notes_app"), _proj(tmp_path, "other_app")
    root = env.ids["root"]

    projects._resolve_and_write(root, str(app / "src" / "main.py"), None)
    projects._resolve_and_write(root, str(other), None)                                # a second folder: registered only
    pa, po = projects.project_of(str(app)), projects.project_of(str(other))
    from backend.memory.db import app_flush

    app_flush()
    rows = {r[0]: (r[1], r[2]) for r in mem.execute("SELECT project_id, name, kind FROM project_registry")}
    assert rows == {pa["id"]: ("notes_app", "app"), po["id"]: ("other_app", "app")}
    assert env.cs.project_of_conversation(root) == pa["id"]                            # the first project names it
    assert env.cs.set_project_if_empty(root, po["id"]) is False

    # the bridge notes on the lane, once per (session, folder), without touching the disk itself
    from backend.agent.tool_bridge import AgentToolBridge

    calls = []
    monkeypatch.setattr(projects, "note_path", lambda conv, path, base=None: calls.append((conv, path, base)) or True)
    br = AgentToolBridge.__new__(AgentToolBridge)
    br._session_workdirs, br._active_conversation_id = {"s1": str(app)}, {"s1": root}
    br._note_project("s1", "read_file", {"path": "src/main.py"})
    br._note_project("s1", "read_file", {"path": "src/main.py"})
    br._note_project("s1", "web_search", {"query": "x"})
    assert calls == [(root, "src/main.py", str(app))]
    br._active_conversation_id["s1"] = env.ids["strand"]                               # the app: one session, many chats
    br._note_project("s1", "read_file", {"path": "src/main.py"})
    assert calls[1:] == [(env.ids["strand"], "src/main.py", str(app))]
    br._active_conversation_id.clear()
    br._note_project("s1", "list_directory", {"path": str(other)})
    assert calls[-1][0] is None                                                        # a session is not a conversation


def test_the_direct_path_tells_the_bridge_its_conversation():
    """Live 2026-11-23: a direct-path read_file registered the project but stamped no conversation - only the DER path
    bound the bridge's session -> conversation map."""
    from backend.tests._kernel_source import kernel_function_source

    src = kernel_function_source("_respond_direct")
    assert src.index("_conv_map[_tool_session] = self.conversation_id") < src.index("self._tool_bridge.execute_tool(")


def test_a_new_claim_keeps_its_project(env, tmp_path):  # noqa: F811
    from backend.memory import projects
    from backend.memory.interface import claim_finding

    app = _proj(tmp_path, "notes_app")
    ep = SimpleNamespace(turn_id="T1", session_id="conv-none", full_content="[Step 1] done",
                         tool_sequence=[{"tool": "read_file", "target": str(app / "src" / "main.py"), "success": True}])
    f = json.loads(claim_finding(ep))
    assert f["project"] == {"id": projects.project_of(str(app))["id"], "name": "notes_app", "kind": "app"}

    env.cs.set_project_if_empty(env.ids["root"], "proj_bound")                         # the bridge knew the workdir
    ep.session_id = env.ids["root"]
    assert json.loads(claim_finding(ep))["project"] == {"id": "proj_bound"}

    web = SimpleNamespace(turn_id="T2", session_id="conv-none", full_content="[Step 1] 330 m",
                          tool_sequence=[{"tool": "web_search", "target": "eiffel tower", "success": True}])
    assert "project" not in json.loads(claim_finding(web))                             # a web search has no project


def test_the_snapshot_serves_projects_for_the_lens(env):  # noqa: F811
    con = sqlite3.connect(str(env.mem))
    if "finding" not in {r[1] for r in con.execute("PRAGMA table_info(mycelium_landmarks)")}:
        con.execute("ALTER TABLE mycelium_landmarks ADD COLUMN finding TEXT")
    con.execute("CREATE TABLE IF NOT EXISTS project_registry (project_id TEXT PRIMARY KEY, name TEXT NOT NULL, path TEXT,"
                " description TEXT, tags TEXT, created_at REAL, last_active REAL, kind TEXT)")
    con.execute("INSERT INTO project_registry VALUES ('proj_iris', 'IRIS', 'c:/dev/irisvoice', NULL, '[]', ?, ?, 'iris')", (NOW, NOW))
    con.execute("INSERT INTO project_registry VALUES ('proj_srv', 'weather', 'c:/x/weather', NULL, '[]', ?, ?, 'mcp')", (NOW, NOW))
    rows = [("P_KEPT", "Fix the router", None, json.dumps({"result": "ok", "project": {"id": "proj_iris", "name": "IRIS", "kind": "iris"}})),
            ("P_CONV", "Add a forecast tool", env.ids["strand"], None),
            ("P_TEXT", "The project is in C:\\evals\\demo_app. Add a cli flag", None, None),
            ("P_NONE", "Find the height of the Eiffel Tower", None, None)]
    for i, (lid, text, ref, finding) in enumerate(rows):
        con.execute("INSERT INTO mycelium_landmarks (landmark_id, label, task_class, coordinate_cluster, traversal_sequence,"
                    " cumulative_score, micro_abstract_text, activation_count, conversation_ref, created_at, tier, evidence, finding)"
                    " VALUES (?, 'l', 'task_x', '[]', '[]', 0.6, ?, 1, ?, ?, 'candidate', '[]', ?)", (lid, text, ref, NOW + 10 + i, finding))
    con.commit()
    con.close()
    env.cs.set_project_if_empty(env.ids["strand"], "proj_srv")

    snap = env.sq.snapshot(db=env.mem, conv_db=env.cs._DB_PATH)
    by = {lm["id"]: lm for lm in snap["landmarks"]}
    assert by["P_KEPT"]["project"] == "proj_iris" and by["P_KEPT"]["project_inferred"] is False
    assert by["P_CONV"]["project"] == "proj_srv"
    assert by["P_TEXT"]["project"].startswith("proj_") and by["P_TEXT"]["project_inferred"] is True
    assert by["P_NONE"]["project"] is None
    ps = {p["id"]: p for p in snap["projects"]}
    assert ps["proj_iris"]["kind"] == "iris" and ps["proj_iris"]["claims"] == 1
    assert ps["proj_srv"]["kind"] == "mcp" and ps["proj_srv"]["name"] == "weather" and ps["proj_srv"]["claims"] == 1
    assert ps[by["P_TEXT"]["project"]]["name"] == "demo_app" and ps[by["P_TEXT"]["project"]]["inferred"] is True
    assert [p["kind"] for p in snap["projects"]] == sorted((p["kind"] for p in snap["projects"]), key=("iris", "app", "mcp").index)
