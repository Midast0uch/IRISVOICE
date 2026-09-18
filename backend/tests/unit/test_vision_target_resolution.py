"""Unit tests for REQ-2 bounded description->handle resolution (T8).

Pure functions from ``backend.vision.browser_session``: a model-named target
is either a CSS selector (used directly) or a ``role "name"`` description that
gets a BOUNDED role/name resolution step (REQ-2 AC4). No browser, no network.
"""

from backend.vision.browser_session import _parse_role_name, _role_name_selectors


def test_parse_role_name_accepts_all_quote_styles():
    assert _parse_role_name('button "Sign in"') == ("button", "Sign in")
    assert _parse_role_name("link 'Home'") == ("link", "Home")
    assert _parse_role_name("textbox `Search`") == ("textbox", "Search")


def test_parse_role_name_rejects_non_descriptions():
    """A bare CSS selector or free prose is NOT a role+name description, so
    the caller treats it as a selector (REQ-2 AC4 'bounded' step only)."""
    assert _parse_role_name("#submit") is None
    assert _parse_role_name("a[href='https://x']") is None
    assert _parse_role_name("the big blue button") is None
    assert _parse_role_name('button ""') is None
    assert _parse_role_name("") is None


def test_role_name_selectors_are_bounded_and_role_aware():
    sels = _role_name_selectors("button", "Sign in")
    # Bounded: a handful of candidates, not an unbounded crawl.
    assert 0 < len(sels) <= 12
    # Role-aware: button candidates lead.
    assert any("button" in s for s in sels)
    # The accessible name is carried in the selector.
    assert all("Sign in" in s for s in sels)


def test_unknown_role_still_yields_generic_candidates():
    """An unrecognised role falls back to accessible-name selectors, so a
    description still has a resolution attempt before being declared
    unresolvable (REQ-2 AC4)."""
    sels = _role_name_selectors("widget", "Go")
    assert sels
    assert all("Go" in s for s in sels)
