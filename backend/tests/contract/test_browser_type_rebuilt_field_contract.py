"""A type action survives a field that is rebuilt by the click (live 2026-10-03).

Before: browser_act type on Wikipedia's search box clicked the box, the page
rebuilt the input (its data-iris-mark vanished), and the select-before-type
`locator.evaluate(...)` waited Playwright's default 30 s, then failed the act
(`Locator.evaluate: Timeout 30000ms exceeded`, wall 40 s).

Now: the element-scoped evaluate calls carry the short point timeout; when the
field is gone, the text is selected in the FOCUSED field (Ctrl+A) and typed.
"""

import asyncio

from backend.vision.browser_session import _ACTION_POINT_TIMEOUT_MS, BrowserSession


class _Keys:
    def __init__(self):
        self.pressed, self.typed = [], []

    async def press(self, key):
        self.pressed.append(key)

    async def type(self, ch):
        self.typed.append(ch)


class _Mouse:
    async def move(self, *a, **k):
        pass

    async def click(self, *a, **k):
        pass


class _Page:
    def __init__(self):
        self.keyboard, self.mouse = _Keys(), _Mouse()


class _GoneLocator:
    def __init__(self):
        self.timeouts = []

    async def evaluate(self, expression, arg=None, *, timeout=None):
        self.timeouts.append(timeout)
        raise TimeoutError("Locator.evaluate: Timeout exceeded")


def test_typing_into_a_rebuilt_field_selects_in_the_focused_field():
    page, loc = _Page(), _GoneLocator()
    box = {"x": 0, "y": 0, "width": 10, "height": 10}
    asyncio.run(BrowserSession.__new__(BrowserSession)._perform(page, "type", loc, box, "Kili"))
    assert loc.timeouts == [_ACTION_POINT_TIMEOUT_MS]  # short, never the 30 s default
    assert page.keyboard.pressed == ["Control+A"]
    assert "".join(page.keyboard.typed) == "Kili"
