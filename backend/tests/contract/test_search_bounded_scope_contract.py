"""Contract: a ROOT-wide search is bounded (it timed out and failed a run).

LIVE 2026-09-25: an agent step called grep_files with no path, so ripgrep walked
the whole repo root — node_modules, .next, data/har, a 2.75 GB memory.db — and
the 60 s guard fired:

    [TOOL_DISPATCH] failure tool=grep_files error_type=transient
    error='grep_files timed out after 60s searching 'C:\\dev\\IRISVOICE''

That single timeout turned a satisfied request (three files created and read
back) into "I couldn't complete that task", and burned a minute of the turn.
"""
import backend.agent.search_tools as st


class _Proc:
    returncode = 1
    stdout = ""
    stderr = ""


def _capture(monkeypatch, scope_root):
    seen = {}

    def _fake_run(args, cwd=None, timeout=None):
        seen["args"] = args
        return _Proc()

    monkeypatch.setattr(st, "_run_rg", _fake_run)
    monkeypatch.setattr(st, "resolve_rg", lambda: "rg")
    monkeypatch.setattr(st.os, "getcwd", lambda: str(scope_root))
    return seen


def test_root_scope_excludes_the_heavy_trees(tmp_path, monkeypatch):
    seen = _capture(monkeypatch, tmp_path)
    st.grep_files("needle")  # no path -> the repo root
    joined = " ".join(seen["args"])
    for skip in ("!node_modules/**", "!.next/**", "!data/**", "!screenshots/**",
                 "!.git/**", "!*.db", "!*.har"):
        assert skip in joined, skip
    assert "--max-filesize" in seen["args"]


def test_an_explicit_directory_keeps_full_access(tmp_path, monkeypatch):
    seen = _capture(monkeypatch, tmp_path)
    sub = tmp_path / "sub"
    sub.mkdir()
    st.grep_files("needle", path=str(sub))
    joined = " ".join(seen["args"])
    assert "!data/**" not in joined, "a named directory is searched as asked"
    assert "!node_modules/**" not in joined
