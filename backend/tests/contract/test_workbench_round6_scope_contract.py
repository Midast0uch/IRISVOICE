"""Workbench Round 6 scope and safety contract (owner 2026-11-16).

C8 ("Private scratch folder"): `manager.scratch_workdir(conversation_id)` is a per-conversation
folder under <profile>/AppData/LocalLow/iris-workbench/scratch (Low-integrity already; never
the IRIS repo). The same path on every call; removed when the conversation closes or the
backend exits; KEPT by an idle end (the next step may still need the files).

C10 ("Yes, refuse them"): a CONFINED (personal-mode) worker refuses socket connects to
loopback and private networks with PermissionError (use tools.browser_open for the web).
Public addresses stay allowed; developer mode is unchanged. Child processes are not covered.

The package under test is WORKBENCH_PKG / WORKBENCH_PKG_PATH (the broken-copy demonstrations).
"""
import importlib.util
import os
import socket
import tempfile
import time
import uuid

import pytest

from backend.tests.contract._wb_common import HERE, drop, mod

manager_mod = mod("manager")
client_mod = mod("client")
REPO = HERE.parents[2]          # the directory that holds backend/

windows_only = pytest.mark.skipif(os.name != "nt", reason="LocalLow / OS confinement are Windows-only")


def _norm(p):
    return os.path.normcase(os.path.realpath(p))


def _cid():
    return "r6-" + uuid.uuid4().hex[:10]


def _manager(mode, **kw):
    return manager_mod.WorkbenchManager(mode_of=lambda: mode, **kw)


# --- C8: the scratch folder -----------------------------------------------------------------
@windows_only
def test_scratch_is_a_locallow_folder_outside_the_repo_and_the_same_path_twice():
    cid = _cid()
    m = _manager("personal")
    try:
        p1 = manager_mod.scratch_workdir(cid)
        p2 = manager_mod.scratch_workdir(cid)
        assert p1 == p2 and os.path.isdir(p1)
        low = _norm(os.path.join(os.environ["USERPROFILE"], "AppData", "LocalLow", "iris-workbench", "scratch"))
        assert os.path.commonpath([_norm(p1), low]) == low and _norm(p1) != low
        assert os.path.commonpath([_norm(p1), _norm(REPO)]) != _norm(REPO)       # never in the IRIS repo
        assert _norm(p1) not in (_norm(os.environ["USERPROFILE"]), os.path.splitdrive(_norm(p1))[0] + "\\")
        assert manager_mod.scratch_workdir(cid + "x") != p1                      # one folder per conversation
    finally:
        m.close_all()


@windows_only
def test_scratch_ids_that_clean_to_the_same_name_stay_apart():
    m = _manager("personal")
    try:
        assert manager_mod.scratch_workdir("r6/a b") != manager_mod.scratch_workdir("r6_a_b")
    finally:
        m.close_all()


@windows_only
def test_scratch_is_removed_after_close():
    cid = _cid()
    m = _manager("personal")
    p = manager_mod.scratch_workdir(cid)
    open(os.path.join(p, "f.txt"), "w").write("x")
    assert m.close(cid) is False            # no live workbench: close still removes the folder
    assert not os.path.exists(p)
    assert manager_mod.scratch_workdir(cid) == p and os.path.isdir(p)       # a fresh one on demand
    m.close_all()


@windows_only
def test_scratch_is_removed_after_close_all():
    a, b = _cid(), _cid()
    m = _manager("personal")
    pa, pb = manager_mod.scratch_workdir(a), manager_mod.scratch_workdir(b)
    m.close_all()
    assert not os.path.exists(pa) and not os.path.exists(pb)


@windows_only
def test_scratch_is_kept_after_an_idle_end_and_a_confined_worker_writes_in_it():
    cid = _cid()
    m = _manager("personal", idle_s=0.2, reap_every_s=3600)
    try:
        p = manager_mod.scratch_workdir(cid)
        c = m.workbench_for(cid, p)
        assert c is not None
        rep = c.exec("open('note.txt', 'w').write('kept')")
        assert rep["ok"], rep.get("error")
        time.sleep(0.4)
        assert m.reap_once() == 1 and m.stats()["live"] == 0                 # the worker ended idle
        assert os.path.isfile(os.path.join(p, "note.txt"))                    # the files stay
    finally:
        m.close_all()
    assert not os.path.exists(p)


# --- C10: the decision function -------------------------------------------------------------
@pytest.fixture(scope="module")
def worker():
    spec = importlib.util.spec_from_file_location("_wb_worker_r6_" + uuid.uuid4().hex[:6], client_mod.WORKER_PATH)
    w = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(w)
    return w


@pytest.mark.parametrize("addr", [
    "127.0.0.1", "127.9.9.9", "::1", "localhost", "LOCALHOST", "10.0.0.5", "172.16.0.1", "172.31.255.255",
    "192.168.1.1", "169.254.10.10", "fc00::1", "fd12:3456::1", "fe80::1", "fe80::1%12", "::ffff:127.0.0.1",
    "0.0.0.0", ""])
def test_loopback_and_private_addresses_are_refused(worker, addr):
    assert worker._refused_address(addr), addr


@pytest.mark.parametrize("addr", [
    "93.184.216.34", "8.8.8.8", "1.1.1.1", "172.15.255.255", "172.32.0.1", "192.169.0.1", "11.0.0.1",
    "2606:4700:4700::1111", "::ffff:93.184.216.34"])
def test_public_addresses_are_allowed(worker, addr):
    assert worker._refused_address(addr) is None, addr


# --- C10: the confined worker ---------------------------------------------------------------
@pytest.fixture
def listener():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen(5)
    s.settimeout(1.0)
    yield s
    s.close()


@pytest.fixture
def project():
    p = tempfile.mkdtemp(prefix="_wbr6_proj_")
    yield p
    drop(p)


def _connect_code(port, host="127.0.0.1"):
    return (f"import socket\n"
            f"try:\n"
            f"    socket.create_connection(({host!r}, {port}), timeout=2).close()\n"
            f"    out = 'connected'\n"
            f"except PermissionError as e:\n"
            f"    out = 'refused: ' + str(e)\n"
            f"except OSError as e:\n"
            f"    out = 'os: ' + repr(e)\n"
            f"out")


def _listener_saw_a_connection(listener):
    try:
        conn, _ = listener.accept()
    except socket.timeout:
        return False
    conn.close()
    return True


@windows_only
@pytest.mark.parametrize("host", ["127.0.0.1", "localhost"])
def test_a_confined_worker_cannot_connect_to_loopback(project, listener, host):
    m = _manager("personal")
    try:
        c = m.workbench_for("r6-net", project)
        assert c is not None and c.confined is True
        rep = c.exec(_connect_code(listener.getsockname()[1], host))
        assert rep["ok"], rep.get("error")
        assert "refused: workbench: network address" in rep["value"], rep["value"]
        assert "tools.browser_open" in rep["value"]
        assert not _listener_saw_a_connection(listener), "the listener got a connection"
    finally:
        m.shutdown()


@windows_only
def test_a_confined_worker_cannot_use_a_raw_socket_connect_either(project, listener):
    m = _manager("personal")
    try:
        c = m.workbench_for("r6-net2", project)
        code = (f"import socket\ns = socket.socket()\n"
                f"try:\n    s.connect(('127.0.0.1', {listener.getsockname()[1]})); out = 'connected'\n"
                f"except PermissionError:\n    out = 'refused'\nout")
        rep = c.exec(code)
        assert rep["ok"] and "refused" in rep["value"], rep
        assert not _listener_saw_a_connection(listener)
    finally:
        m.shutdown()


def test_developer_mode_refuses_direct_network_too(project, listener):
    """STATED CHANGE (owner 2026-11-17: scripts reach the web "only [through] the browser in
    the application with the tools and should block if the webswitch isnt on"): this test
    pinned "developer mode still connects"; a script's direct network is now refused in every
    mode - the web goes through tools.browser_* (egress guard + the web switch)."""
    m = _manager("developer")
    try:
        c = m.workbench_for("r6-dev", project)
        assert c is not None and c.confined is False
        rep = c.exec(_connect_code(listener.getsockname()[1]))
        assert rep["ok"] and "refused: workbench: network address" in rep["value"], rep
        assert not _listener_saw_a_connection(listener)
    finally:
        m.shutdown()


@pytest.mark.parametrize("mode", ["personal", "developer"])
def test_a_public_address_and_a_name_lookup_are_refused_in_every_mode(project, mode):
    """A public address and a DNS lookup (a lookup alone can carry data out) are refused too.
    No packet leaves: the audit hook raises before the socket call runs."""
    m = _manager(mode)
    try:
        c = m.workbench_for(f"r6-pub-{mode}", project)
        code = ("import socket\nres = []\n"
                "for f in (lambda: socket.create_connection(('93.184.216.34', 80), timeout=1),\n"
                "          lambda: socket.getaddrinfo('example.com', 80)):\n"
                "    try:\n        f(); res.append('reached')\n"
                "    except PermissionError as e:\n        res.append('refused')\n"
                "    except OSError:\n        res.append('oserror')\n"
                "res")
        rep = c.exec(code)
        assert rep["ok"] and rep["value"] == "['refused', 'refused']", rep
    finally:
        m.shutdown()


def test_child_processes_get_the_dead_proxy():
    """Children (sh / subprocess: curl, npm, pip, python) inherit proxies to a dead port; a
    child that ignores proxy variables is NOT covered (firewall / AppContainer later)."""
    from backend.agent.workbench import client as cl

    for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "npm_config_proxy"):
        assert cl.NO_NET_ENV[k] == "http://127.0.0.1:9"
    assert cl.NO_NET_ENV["npm_config_offline"] == "true" and cl.NO_NET_ENV["PIP_NO_INDEX"] == "1"


def test_the_scratch_base_is_a_registered_root_and_lowlow_is_not():
    """Round 6 C8 end to end: the node binds manager.scratch_workdir(conv) as the session's
    workdir, and the dev-tools branch refuses any cwd outside _registered_roots() as
    workdir_denied. The scratch BASE must be a root (the folder itself under it); LocalLow and
    the workbench temp folders must not be."""
    import os as _os

    from backend.agent.tool_bridge import AgentToolBridge
    from backend.agent.workbench.client import low_root

    roots = [_os.path.normcase(r) for r in AgentToolBridge()._registered_roots()]
    base = _os.path.normcase(_os.path.normpath(_os.path.join(low_root(), "scratch")))
    assert base in roots
    assert _os.path.normcase(_os.path.normpath(low_root())) not in roots
    assert _os.path.normcase(_os.path.dirname(low_root())) not in roots
