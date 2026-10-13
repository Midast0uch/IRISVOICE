"""A change fact is covered by an edit or a passing run, never by its words.

Live c04 (2026-10-13): the request "The project is in X. Make the tests in
test_durations.py pass by implementing parse_duration in durations.py. Do not
change the tests." was covered at step 1 by a directory listing that named the
files. The turn never edited durations.py, its last pytest FAILED, and the run
still graded pass and replied "I've completed the task".
"""
from backend.agent import goal_contract as gc

C04_REQUEST = (
    "The project is in X. Make the tests in test_durations.py pass by implementing "
    "parse_duration in durations.py. Do not change the tests."
)
G04_REQUEST = (
    "On https://www.scrapethissite.com/pages/forms/, look up the Boston Bruins in "
    "the site's team list and tell me how many games they won in 1990."
)
C04_LISTING = (
    "Listed 4 entries\n\nActions:\n"
    "- list_directory . -> ok\n"
    "durations.py\ntest_durations.py\nREADME.md\nnotes.txt"
)
EDIT_OK = "- edit_file durations.py -> ok"
PYTEST_OK = "- run_command python -m pytest -q -> ok"
PYTEST_FAILED = "- run_command python -m pytest -q -> FAILED"
NON_ZERO = "The last command in this step exited non-zero."


def _contract(request):
    return gc.Contract(required=gc.extract_required(request))


def _cover(request, result):
    return gc.mark_coverage(_contract(request), ["VERIFIED"], [result])


def test_change_asks_are_detected():
    for text in (
        "Make the tests in test_durations.py pass by implementing parse_duration in durations.py",
        "The project is in X. Make the tests in t.py pass by implementing f in d.py",
        "Fix the off-by-one bug in pager.py",
        "Save the quotes to quotes.txt",
    ):
        assert gc._asks_for_change(text) is True, text
    for text in (
        "Write a short summary of the article",
        "tell me how many games they won in 1990",
        "Open https://quotes.toscrape.com in the live browser",
        "Find the population of Andorra on https://www.scrapethissite.com/pages/simple/",
        "Remake the list in notes.txt",
    ):
        assert gc._asks_for_change(text) is False, text


def test_a_listing_that_names_the_files_does_not_cover_a_change_fact():
    cov = _cover(C04_REQUEST, C04_LISTING)
    assert cov.C == 0.0, (cov.covered, cov.required_n)


def test_a_failed_last_test_run_does_not_cover():
    cov = _cover(C04_REQUEST, "\n\nActions:\n" + PYTEST_FAILED + "\n\n" + NON_ZERO)
    assert cov.C == 0.0, (cov.covered, cov.required_n)
    cov = _cover(C04_REQUEST, "\n\nActions:\n" + EDIT_OK + "\n" + PYTEST_FAILED + "\n\n" + NON_ZERO)
    assert cov.C == 0.0, (cov.covered, cov.required_n)


def test_an_edit_or_a_passing_run_covers():
    cov = _cover(C04_REQUEST, "Done.\n\nActions:\n" + EDIT_OK + "\n" + PYTEST_OK)
    assert cov.C == 1.0, (cov.covered, cov.required_n)
    cov = _cover(C04_REQUEST, "Done.\n\nActions:\n" + PYTEST_OK)
    assert cov.C == 1.0, (cov.covered, cov.required_n)
    cov = _cover(C04_REQUEST, "Done.\n\nActions:\n" + EDIT_OK)
    assert cov.C == 1.0, (cov.covered, cov.required_n)


def test_non_change_facts_keep_the_word_rule():
    result = "Team Name | Year | Wins\nBoston Bruins | 1990 | 44"
    cov = _cover(G04_REQUEST, result)
    assert cov.C == 1.0, (cov.covered, cov.required_n)
