"""Unit tests: research cross-check (spec research-memory R3, REQ-2 AC2.3).

``cross_check`` labels each earlier claim against new evidence with token
overlap and number comparison only (no model on the answer path); the section
it feeds is bounded and carries both dates.
"""
from backend.agent.research_memory import (
    SECTION_CAP,
    claims_from_dashboard,
    cross_check,
    format_prior_section,
)


def _prior(*claims, date="2026-09-01", rid="research_a", query="tokyo population"):
    return {
        "id": rid, "query": query, "created_at": f"{date}T10:00:00Z",
        "summary": "Tokyo's population was about 13.96 million in 2021.",
        "claims": [{"text": c, "urls": ["https://stats.example.org/tokyo"]} for c in claims],
    }


def _labels(checks):
    return {c["claim"]: c["label"] for c in checks}


def test_changed_number_same_subject():
    prior = _prior("Tokyo population 13,960,000 (2021)")
    new = "According to the latest census, Tokyo's population is 14,246,219 (2024)."
    checks = cross_check([prior], new)
    assert [c["label"] for c in checks] == ["changed"]
    assert "14,246,219" in checks[0]["new_evidence"]
    assert checks[0]["prior_date"] == "2026-09-01"


def test_same_number_is_confirmed():
    prior = _prior("Tokyo population 13,960,000 (2021)")
    new = "The population of Tokyo was 13,960,000 (2021), the largest in Japan."
    assert [c["label"] for c in cross_check([prior], new)] == ["confirmed"]


def test_unrelated_text_is_not_rechecked():
    prior = _prior("Tokyo population 13,960,000 (2021)")
    new = "Sourdough needs a hydration ratio near 75 percent for an open crumb."
    assert [c["label"] for c in cross_check([prior], new)] == ["not_rechecked"]


def test_subject_match_without_numbers_is_not_rechecked():
    """The new sentence is about the subject but states no number: it is no
    evidence either way, so the claim is neither confirmed nor changed."""
    prior = _prior("Tokyo population 13,960,000 (2021)")
    new = "Tokyo population is a topic many planners study closely."
    assert [c["label"] for c in cross_check([prior], new)] == ["not_rechecked"]


def test_one_confirming_source_wins_over_a_changed_one():
    prior = _prior("Tokyo population 13,960,000 (2021)")
    new = ("Tokyo population reached 14,246,219 in 2024. "
           "Tokyo population was 13,960,000 in 2021.")
    assert [c["label"] for c in cross_check([prior], new)] == ["confirmed"]


def test_new_claims_not_covered_by_prior_are_labelled_new():
    prior = _prior("Tokyo population 13,960,000 (2021)")
    checks = cross_check(
        [prior], "Tokyo population 13,960,000 (2021).",
        new_claims=["Tokyo population 13,960,000 (2021)", "Osaka hosts the Kansai airport hub"],
    )
    assert _labels(checks)["Osaka hosts the Kansai airport hub"] == "new"
    assert sum(1 for c in checks if c["label"] == "new") == 1


def test_cross_check_is_deterministic_and_model_free():
    prior = _prior("Tokyo population 13,960,000 (2021)")
    new = "Tokyo population is 14,246,219 (2024)."
    assert cross_check([prior], new) == cross_check([prior], new)


def test_section_is_bounded_and_carries_both_dates():
    prior = _prior("Tokyo population 13,960,000 (2021)", *[f"Fact number {i} about Tokyo transit ridership {i}00" for i in range(6)])
    checks = cross_check([prior], "Tokyo population is 14,246,219 (2024).")
    section = format_prior_section([prior], checks, today="2026-09-30")
    assert "PRIOR RESEARCH" in section and "CROSS-CHECK" in section
    assert "2026-09-01" in section and "2026-09-30" in section
    assert "changed since 2026-09-01" in section
    assert len(section) <= SECTION_CAP


def test_section_cap_holds_for_huge_records():
    big = _prior(*[("Claim %d " % i) + "word " * 60 for i in range(6)])
    big["summary"] = "s " * 2000
    checks = cross_check([big, big], "nothing relevant here at all, really nothing.")
    assert len(format_prior_section([big, big, big], checks)) <= SECTION_CAP


def test_no_prior_records_no_section():
    assert format_prior_section([], []) == ""


def test_claims_from_dashboard_reads_cited_summary_and_sections():
    dash = {
        "summary": "x",
        "sections": [
            {"type": "metrics", "items": [{"label": "Population", "value": "13,960,000"}]},
            {"type": "cards", "items": [{"title": "Census", "body": "Official count of residents", "url": "https://c.example/1"}]},
        ],
    }
    cited = ("Tokyo had 13,960,000 residents in 2021. [1](https://stats.example.org/t) "
             "An unsupported remark that nobody can source. [?]")
    claims = claims_from_dashboard(dash, cited)
    texts = [c["text"] for c in claims]
    assert texts[0].startswith("Tokyo had 13,960,000")
    assert claims[0]["urls"] == ["https://stats.example.org/t"]
    assert any(t.startswith("Population: 13,960,000") for t in texts)
    assert any(c["urls"] == ["https://c.example/1"] for c in claims)
