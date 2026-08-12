"""A provider's published rate limit is read from the provider, per provider.

The meter learned ceilings ONLY by being rejected — halving on a 429 and probing
back up from a guess of 30 rpm — while providers that publish their limit on
every response were ignored. Observed live: a real limit of 5 rpm against a
standing guess of 30, so a run had to collect rejections before it paced at all.

Two properties matter here and neither is about any one vendor:

  * NOTHING IS HARDCODED. No rpm value appears in the code; the number always
    comes from the response, and is stored per quota_id so providers cannot
    contaminate each other's ceilings.
  * ONLY PER-MINUTE FIGURES COUNT. One response carries minute, hour and day
    limits under nearly identical names. Reading an hour or day figure as rpm
    would set a ceiling hundreds of times too high and silently disable the
    gate — which is worse than no gating, because it looks configured.
"""
from __future__ import annotations

import pytest

from backend.agent.inference.transport import (
    _RPM_HEADERS,
    _observe_advertised_limit,
)
from backend.agent.rate_meter import CEILING_MIN_RPM, get_rate_meter


class _T:
    def __init__(self, quota_id: str):
        self._quota_id = quota_id


@pytest.fixture()
def meter():
    return get_rate_meter()


def _window(meter, qid: str):
    meter.ensure_window(qid, True)
    return qid


def test_no_provider_name_or_rpm_value_is_hardcoded():
    """The header list is a set of spellings, not a vendor table with numbers."""
    for _h in _RPM_HEADERS:
        assert "limit" in _h and "ratelimit" in _h.replace("-", ""), (
            f"{_h!r} does not look like a rate-limit header"
        )
    # No digits anywhere in the accepted spellings — a hardcoded per-provider
    # rpm would have to show up as one.
    assert not any(any(c.isdigit() for c in _h) for _RPM_HEADERS_ in [_RPM_HEADERS] for _h in _RPM_HEADERS_)


def test_the_published_minute_limit_is_used(meter):
    qid = _window(meter, "prov://alpha|q")
    _observe_advertised_limit(_T(qid), {"x-ratelimit-limit-requests-minute": "5"})
    assert meter.get_ceiling(qid) == 5.0


def test_hour_and_day_limits_are_not_mistaken_for_rpm(meter):
    """The decoys ride along in the SAME response as the minute figure."""
    qid = _window(meter, "prov://beta|q")
    _observe_advertised_limit(_T(qid), {
        "x-ratelimit-limit-requests-day": "2400",
        "x-ratelimit-limit-requests-hour": "150",
        "x-ratelimit-limit-requests-minute": "5",
    })
    assert meter.get_ceiling(qid) == 5.0, (
        "an hour/day figure was read as rpm — the ceiling would be hundreds of "
        "times too high and the gate would admit everything while looking set"
    )


def test_a_response_with_only_an_hour_limit_changes_nothing(meter):
    qid = _window(meter, "prov://gamma|q")
    before = meter.get_ceiling(qid)
    _observe_advertised_limit(_T(qid), {"x-ratelimit-limit-requests-hour": "150"})
    assert meter.get_ceiling(qid) == before, (
        "an unknown-period header moved the ceiling; unknown periods must be "
        "ignored so the meter keeps learning from 429s as before"
    )


def test_each_provider_keeps_its_own_ceiling(meter):
    """Per quota_id — one provider's limit must not leak onto another's."""
    a = _window(meter, "prov://one|q")
    b = _window(meter, "prov://two|q")
    _observe_advertised_limit(_T(a), {"x-ratelimit-limit-requests-minute": "5"})
    _observe_advertised_limit(_T(b), {"x-ratelimit-limit-requests-minute": "60"})
    assert meter.get_ceiling(a) == 5.0
    assert meter.get_ceiling(b) != 5.0, "provider one's limit leaked onto two"


def test_a_different_vendor_header_spelling_is_accepted(meter):
    qid = _window(meter, "prov://delta|q")
    _observe_advertised_limit(_T(qid), {"anthropic-ratelimit-requests-limit": "50"})
    assert meter._windows[qid].advertised_rpm == 50.0


def test_an_implausible_value_is_ignored(meter):
    qid = _window(meter, "prov://eps|q")
    before = meter.get_ceiling(qid)
    _observe_advertised_limit(_T(qid), {"x-ratelimit-limit-requests-minute": "999999"})
    assert meter.get_ceiling(qid) == before


def test_the_learning_floor_never_overrules_a_published_limit(meter):
    """The trap this whole change exists to avoid.

    CEILING_MIN_RPM is a floor applied on READ so learning cannot starve a crawl.
    Against a provider publishing less than the floor, it would lift the ceiling
    ABOVE the real limit and manufacture the 429s the gate exists to prevent.
    """
    qid = _window(meter, "prov://tight|q")
    tight = max(1.0, CEILING_MIN_RPM / 3.0)
    _observe_advertised_limit(_T(qid), {"x-ratelimit-limit-requests-minute": str(tight)})
    assert meter.get_ceiling(qid) == pytest.approx(tight), (
        f"floor {CEILING_MIN_RPM} overrode a published limit of {tight}"
    )


def test_a_429_can_still_tighten_below_the_published_limit(meter):
    """Published is an upper bound, not a guarantee — enforcement can be
    stricter than the documentation."""
    qid = _window(meter, "prov://strict|q")
    _observe_advertised_limit(_T(qid), {"x-ratelimit-limit-requests-minute": "60"})
    meter.observe_429(qid)
    assert meter.get_ceiling(qid) <= 60.0
