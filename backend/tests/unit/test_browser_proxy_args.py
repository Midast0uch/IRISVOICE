"""Unit: the browser launch passes ``--no-proxy-server`` unless a proxy is set.

Measured 2026-10-12: with no flag, Chromium ran Windows proxy auto-detect
(WPAD) and held its first connection 18 s, so cold page opens took 9-69 s.
A proxy the user set (env var or Windows settings) must keep the system path.
The winreg module is faked, so the test reads no real registry.
"""

import sys
import types

import pytest

from backend.vision.browser_pool import _proxy_args

_PROXY_ENV = (
    "HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY",
    "https_proxy", "http_proxy", "all_proxy",
)
_INTERNET_SETTINGS = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"


class _FakeKey:
    def __init__(self, values):
        self.values = values

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def no_proxy_env(monkeypatch):
    for name in _PROXY_ENV:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def _fake_winreg(monkeypatch, values):
    """Insert a fake winreg whose Internet Settings key holds ``values``."""
    fake = types.ModuleType("winreg")
    fake.HKEY_CURRENT_USER = 0x80000001

    def OpenKey(hive, path):
        assert hive == fake.HKEY_CURRENT_USER
        assert path == _INTERNET_SETTINGS
        return _FakeKey(values)

    def QueryValueEx(key, name):
        if name not in key.values:
            raise FileNotFoundError(name)
        return (key.values[name], 1)

    fake.OpenKey = OpenKey
    fake.QueryValueEx = QueryValueEx
    monkeypatch.setitem(sys.modules, "winreg", fake)


def test_no_proxy_disables_proxy_auto_detect(no_proxy_env):
    _fake_winreg(no_proxy_env, {})
    assert _proxy_args() == ["--no-proxy-server"]


def test_proxy_env_var_keeps_system_proxy(no_proxy_env):
    _fake_winreg(no_proxy_env, {})
    no_proxy_env.setenv("HTTPS_PROXY", "http://proxy.example:8080")
    assert _proxy_args() == []


def test_windows_proxy_enabled_keeps_system_proxy(no_proxy_env):
    _fake_winreg(no_proxy_env, {"ProxyEnable": 1})
    assert _proxy_args() == []


def test_windows_auto_config_url_keeps_system_proxy(no_proxy_env):
    _fake_winreg(no_proxy_env, {"AutoConfigURL": "http://wpad.example/wpad.dat"})
    assert _proxy_args() == []


def test_the_launch_fails_tracker_hosts_fast():
    """Measured 2026-10-13 (A/B, 4 cold rounds x 5 sites): the previous args
    166.5 (two timeouts) / 15.6 / 1.7 / 1.9 s per round; with ad/analytics
    hosts resolving to not-found 5.3 / 1.6 / 1.6 / 1.6 s. The rule rides the
    ONE launch; it is a resolver rule, not a route (a route switches the HTTP
    cache off), and no second --disable-features switch is passed (Chromium
    keeps one value, so it would replace Playwright's own list)."""
    import inspect

    from backend.vision import browser_pool as bp

    assert not any(a.startswith("--disable-features") for a in bp._SPEED_ARGS)
    rules = next(a for a in bp._SPEED_ARGS if a.startswith("--host-resolver-rules="))
    for host in ("googletagmanager.com", "google-analytics.com", "doubleclick.net"):
        assert f"MAP *.{host} ~NOTFOUND" in rules and f"MAP {host} ~NOTFOUND" in rules
    src = inspect.getsource(bp)
    assert "args=_LAUNCH_ARGS + _SPEED_ARGS + _proxy_args()" in src
