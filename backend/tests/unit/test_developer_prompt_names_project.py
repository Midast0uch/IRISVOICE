"""Regression (2026-09-29): a developer turn bound to a project OUTSIDE the IRIS
repo is told that folder, not "full access to the IRISVOICE source ... commit to
the iris-agent branch" plus IRIS's PROJECT.md (which pointed the planner at the
wrong codebase in every eval coding turn)."""

import os
from types import SimpleNamespace

from backend.agent.agent_kernel import AgentKernel

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def _kernel(workdir):
    k = AgentKernel.__new__(AgentKernel)
    k.session_id = "s"
    k._turn_session_id = "s"
    k._tool_bridge = SimpleNamespace(_session_workdirs={"s": workdir} if workdir else {})
    return k


def test_outside_project_is_named(tmp_path):
    assert _kernel(str(tmp_path))._bound_external_project() == str(tmp_path)


def test_iris_repo_and_unbound_sessions_keep_the_iris_prompt():
    assert _kernel(_REPO)._bound_external_project() == ""
    assert _kernel(os.path.join(_REPO, "backend"))._bound_external_project() == ""
    assert _kernel(None)._bound_external_project() == ""
