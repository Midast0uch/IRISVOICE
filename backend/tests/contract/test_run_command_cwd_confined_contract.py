"""A model-supplied run_command cwd stays inside the bound project folder.

MEASURED 2026-11-09 (c14_run_and_report, a FAIL): the model passed a stale
absolute cwd from an earlier eval run (gone: "[WinError 267] The directory
name is invalid"), then `cwd=..`, which listed the eval root, read another
task's hidden tests, hit the 13-call step limit and replied "could not
verify". The tool description also said cwd "defaults to IRISVOICE root", so
the model believed it had to name a folder. Pins, through the real dev-tool
path and a real process:
  * `..` (outside the project) runs in the project folder;
  * a missing folder runs in the project folder;
  * a real subfolder of the project is kept;
  * with no bound project folder nothing changes (the explicit cwd wins).
"""
import asyncio
import os
import sys

from backend.agent.tool_bridge import AgentToolBridge

_PWD = f'"{sys.executable}" -c "import os; print(os.getcwd())"'


def _bridge(tmp_path, monkeypatch, bound=True):
    b = AgentToolBridge.__new__(AgentToolBridge)
    b.__init_bridge_state__()
    if bound:
        b._session_workdirs["s"] = str(tmp_path / "proj")
    monkeypatch.setattr(AgentToolBridge, "_registered_roots",
                        lambda self: [str(tmp_path)])
    return b


def _cwd_of(bridge, cwd):
    res = asyncio.run(bridge._execute_dev_tool(
        "run_command", {"command": _PWD, "cwd": cwd}, "s"))
    out = str(res.get("stdout") or res.get("output") or "").strip().splitlines()
    return os.path.normcase(os.path.normpath(out[-1])) if out else ""


def _norm(p):
    return os.path.normcase(os.path.normpath(str(p)))


def test_dotdot_runs_in_the_project_folder(tmp_path, monkeypatch):
    (tmp_path / "proj").mkdir()
    assert _cwd_of(_bridge(tmp_path, monkeypatch), "..") == _norm(tmp_path / "proj")


def test_a_missing_folder_runs_in_the_project_folder(tmp_path, monkeypatch):
    (tmp_path / "proj").mkdir()
    gone = str(tmp_path / "iris-evals" / "20261107-134631" / "c17_name_failing_tests")
    assert _cwd_of(_bridge(tmp_path, monkeypatch), gone) == _norm(tmp_path / "proj")


def test_a_real_subfolder_is_kept(tmp_path, monkeypatch):
    (tmp_path / "proj" / "pkg").mkdir(parents=True)
    assert _cwd_of(_bridge(tmp_path, monkeypatch), "pkg") == _norm(tmp_path / "proj" / "pkg")


def test_a_stale_repo_path_runs_in_the_project_folder(tmp_path, monkeypatch):
    """repo_path wins over cwd in the resolution, so it needs the same rule."""
    (tmp_path / "proj").mkdir()
    b = _bridge(tmp_path, monkeypatch)
    res = asyncio.run(b._execute_dev_tool(
        "run_command", {"command": _PWD, "repo_path": ".."}, "s"))
    out = str(res.get("stdout") or res.get("output") or "").strip().splitlines()
    assert out and _norm(out[-1]) == _norm(tmp_path / "proj")


def test_a_relative_file_path_may_not_climb_out_of_the_project(tmp_path, monkeypatch):
    """c12 (2026-11-09) read ../c10_create_module/_eval_hidden/test_hidden.py:
    a relative file-tool path that leaves the bound project is refused before
    the file tool runs; a path inside, and an absolute path, are not."""
    (tmp_path / "proj").mkdir()
    b = _bridge(tmp_path, monkeypatch)
    assert b._relative_escape({"path": "../c10/_eval_hidden/test_hidden.py"}, "s")
    assert b._relative_escape({"file_path": "pkg/../../x.py"}, "s")
    assert not b._relative_escape({"path": "pkg/mod.py"}, "s")
    assert not b._relative_escape({"path": str(tmp_path / "other" / "x.py")}, "s")
    unbound = _bridge(tmp_path, monkeypatch, bound=False)
    assert not unbound._relative_escape({"path": "../x.py"}, "s")
    import inspect

    src = inspect.getsource(AgentToolBridge.execute_mcp_tool)
    assert src.index("_relative_escape(") < src.index("_anchor_file_paths("), \
        "the escape check must run before the path is anchored"


def test_no_bound_project_keeps_the_explicit_cwd(tmp_path, monkeypatch):
    (tmp_path / "other").mkdir()
    b = _bridge(tmp_path, monkeypatch, bound=False)
    assert _cwd_of(b, str(tmp_path / "other")) == _norm(tmp_path / "other")
