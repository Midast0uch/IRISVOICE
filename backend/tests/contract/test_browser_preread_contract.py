"""CT (2026-10-13): Chromium file pre-read warms the OS cache before launch.

Measured on this machine: a cold chrome-headless-shell.exe (199 MB) on the 99%-full
C: HDD took 25.9 s to launch and 10.6 s to the first page. After one sequential read
it took 2.0 s and 2.4 s. On the D: SSD 0.9 s and 0.2 s. Live g04 reply 144-155 s -> 58.5 s.

Hermetic: fake files under tmp_path, no real browser, no network.
Pins: the file list, one read per window, and both start points (set_web_hold, _start_browser).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import threading
import types

import pytest

from backend.vision import browser_pool as bp


def _shell_rev() -> str:
    """The headless-shell revision, read the same way browser_pool reads it."""
    import playwright

    pkg = os.path.join(os.path.dirname(playwright.__file__), "driver", "package")
    with open(os.path.join(pkg, "browsers.json"), encoding="utf-8") as fh:
        return next(b["revision"] for b in json.load(fh)["browsers"]
                    if b["name"] == "chromium-headless-shell")


def _make_shell_folder(root, rev: str):
    folder = root / f"chromium_headless_shell-{rev}" / "chrome-headless-shell-win64"
    folder.mkdir(parents=True)
    return folder


def test_files_resolve_under_playwright_browsers_path(tmp_path, monkeypatch):
    folder = _make_shell_folder(tmp_path, _shell_rev())
    exe = folder / "chrome-headless-shell.exe"
    exe.write_bytes(b"\0" * 16)
    (folder / "vk_swiftshader.dll").write_bytes(b"\0" * 16)  # created first, sorts last
    (folder / "ffmpeg.dll").write_bytes(b"\0" * 16)
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path))

    files = bp._headless_shell_files()

    expected = [str(exe), str(folder / "ffmpeg.dll"), str(folder / "vk_swiftshader.dll")]
    assert [os.path.normpath(f) for f in files] == [os.path.normpath(f) for f in expected]


def test_missing_exe_gives_no_files(tmp_path, monkeypatch):
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(empty))

    assert bp._headless_shell_files() == []


def test_preread_reads_every_file_once_per_window(tmp_path, monkeypatch, caplog):
    folder = _make_shell_folder(tmp_path, _shell_rev())
    (folder / "chrome-headless-shell.exe").write_bytes(b"\0" * 3_000_000)
    (folder / "ffmpeg.dll").write_bytes(b"\0" * 1_000_000)
    (folder / "vk_swiftshader.dll").write_bytes(b"\0" * 2_000_000)
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path))
    # Each preread thread calls _headless_shell_files() exactly once, so this counts threads.
    real_files = bp._headless_shell_files
    listed: list = []

    def _counting_files():
        listed.append(1)
        return real_files()

    monkeypatch.setattr(bp, "_headless_shell_files", _counting_files)
    # -inf, not 0.0: time.monotonic() counts from boot, so 0.0 would look "read
    # just now" on a machine up less than 300 s. -inf means "never read".
    monkeypatch.setattr(bp, "_exe_preread_done_at", float("-inf"))
    monkeypatch.setattr(bp, "_exe_preread_busy", False)

    with caplog.at_level(logging.INFO, logger="backend.vision.browser_pool"):
        bp._preread_browser_files()
        bp._preread_browser_files()  # inside the window and while busy: must not start a thread
        workers = [t for t in threading.enumerate() if t.name == "iris-browser-preread"]
        for t in workers:
            t.join(10)
            assert not t.is_alive()

    assert len(listed) == 1, "exactly one preread thread for two back-to-back calls"
    assert any(r.getMessage().startswith(
        "[browser_pool] Chromium files read into the OS cache: 6 MB in")
        for r in caplog.records)
    assert bp._exe_preread_done_at > 0
    assert bp._exe_preread_busy is False


def test_cold_launch_and_web_toggle_start_the_preread(monkeypatch, caplog):
    import backend.vision.browser_session as browser_session

    calls: list = []
    monkeypatch.setattr(bp, "_preread_browser_files", lambda: calls.append(1))

    # (a) The web toggle ON starts the preread. Nothing real starts.
    async def _no_prewarm():
        return None

    monkeypatch.setattr(bp, "_prewarm_on_host", _no_prewarm)
    monkeypatch.setattr(browser_session, "warm_keyring", lambda: None)
    try:
        with caplog.at_level(logging.WARNING, logger="backend.vision.browser_pool"):
            bp.set_web_hold(True)
        assert len(calls) == 1
        assert not any("web hold" in r.getMessage() for r in caplog.records)
    finally:
        bp.set_web_hold(False)

    # (b) A cold launch starts the preread before the Playwright import.
    def _playwright_missing():
        raise ImportError("playwright not installed (test double)")

    fake_async_api = types.ModuleType("playwright.async_api")
    fake_async_api.async_playwright = _playwright_missing
    monkeypatch.setitem(sys.modules, "playwright.async_api", fake_async_api)
    before = len(calls)
    with pytest.raises(ImportError):
        asyncio.run(bp._start_browser())
    assert len(calls) == before + 1
