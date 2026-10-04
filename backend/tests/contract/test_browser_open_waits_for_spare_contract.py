"""A page open waits for the spare page that is being built (D1, 2026-10-03).

Before: a browser_open that arrived while the pool was still building its
spare context+page took None and built a SECOND page in parallel. Cold run
2026-10-03: the spare took 42 s and the open's own page 29.6 s, side by side,
on a cold Chromium; the first page opened 56 s after the message.

Now: take_spare_page() waits (shielded, bounded) for the in-flight build.
"""

import asyncio

from backend.vision import browser_pool as bp


class _Browser:
    def is_connected(self):
        return True


def test_take_spare_page_waits_for_the_spare_in_flight(monkeypatch):
    monkeypatch.setattr(bp, "_browser", _Browser())
    monkeypatch.setattr(bp, "_web_hold", False)  # no replacement build
    monkeypatch.setattr(bp, "_spare", None)

    async def run():
        async def _build():
            await asyncio.sleep(0.05)
            bp._spare = ("ctx", "page")

        monkeypatch.setattr(bp, "_spare_task", asyncio.get_running_loop().create_task(_build()))
        return await bp.take_spare_page()

    assert asyncio.run(run()) == ("ctx", "page")


def test_a_slow_spare_is_never_cancelled_by_the_wait(monkeypatch):
    monkeypatch.setattr(bp, "_browser", _Browser())
    monkeypatch.setattr(bp, "_web_hold", False)
    monkeypatch.setattr(bp, "_spare", None)
    monkeypatch.setattr(bp, "_SPARE_WAIT_S", 0.01)

    async def run():
        async def _build():
            await asyncio.sleep(0.1)
            bp._spare = ("ctx", "page")

        task = asyncio.get_running_loop().create_task(_build())
        monkeypatch.setattr(bp, "_spare_task", task)
        got = await bp.take_spare_page()
        await task
        return got, task.cancelled(), bp._spare

    got, cancelled, spare = asyncio.run(run())
    assert got is None and cancelled is False and spare == ("ctx", "page")
