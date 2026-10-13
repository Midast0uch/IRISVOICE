"""Fact terms: asking words are not fact terms, and a year is one.

Live g04 (2026-10-13): the fact "tell me how many games they won in 1990" held the
terms tell/many/games/they. The step result showed the Boston Bruins table (Year
1990, Wins 44) without the word "games", so the fact stayed open at C=0.5 and the
run added 3 empty steps. Question words are now stopwords, and a year is a term.
"""
from backend.agent import goal_contract as gc

G04_REQUEST = (
    "On https://www.scrapethissite.com/pages/forms/, look up the Boston Bruins in "
    "the site's team list and tell me how many games they won in 1990."
)
BROWSER_TABLE = (
    "Hockey Teams: Forms, Searching and Pagination\n"
    "Team Name | Year | Wins | Losses\n"
    "Boston Bruins | 1990 | 44 | 24\n"
    "Boston Bruins | 1991 | 36 | 32"
)


def _g04_contract():
    return gc.Contract(required=gc.extract_required(G04_REQUEST))


def test_asking_words_are_not_fact_terms():
    assert gc._distinctive_terms("tell me how many games they won in 1990") == [
        "games", "1990",
    ]
    assert gc._distinctive_terms("tell me the birth date it shows") == ["birth", "date"]


def test_a_year_is_a_fact_term():
    assert "1990" in gc._distinctive_terms("population of Andorra in 1990")
    # A number that is not a standalone year-shaped token is not a term.
    terms = set(gc._distinctive_terms("costs 2,019 or 19.5"))
    assert not {"2019", "019", "195"} & terms


def test_the_answer_row_covers_the_fact_without_the_question_words():
    cov = gc.mark_coverage(_g04_contract(), ["VERIFIED"], [BROWSER_TABLE])
    assert cov.C == 1.0, (cov.covered, cov.required_n)


def test_a_result_without_the_year_leaves_the_fact_open():
    result = "Boston Bruins | 1991 | 36 | 32"
    cov = gc.mark_coverage(_g04_contract(), ["VERIFIED"], [result])
    assert cov.C == 0.5, (cov.covered, cov.required_n)
