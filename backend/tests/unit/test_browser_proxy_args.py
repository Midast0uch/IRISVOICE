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
