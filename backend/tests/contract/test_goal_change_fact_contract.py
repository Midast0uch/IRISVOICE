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


# Live c05 (2026-10-27): the edit and a clean "python greet.py --shout World" run both
# committed UNVERIFIED (the text check could not confirm them), C stayed 0, the
# coverage gap re-planned 3 steps that redid the work: reply 43-70 s vs a 25 s standard.
C05_REQUEST = (
    r"The project is in C:\Users\midas\AppData\Local\Temp\iris-evals\x\c05_add_cli_flag. "
    "Add a --shout flag to greet.py. With --shout the greeting is printed in upper case. "
    "Without it the output stays exactly the same."
)
C05_CHECKED = "Verified.\n\nActions:\n- run_command python greet.py World; python greet.py --shout World -> ok"


def test_an_unverified_step_that_ran_the_code_cleanly_covers_a_change_fact():
    c = _contract(C05_REQUEST)
    assert gc.mark_coverage(c, ["UNVERIFIED"], [C05_CHECKED]).C == 1.0
    edit_then_run = "Done.\n\nActions:\n- edit_file greet.py -> ok\n- run_command python greet.py --shout World -> ok"
    assert gc.mark_coverage(c, ["UNVERIFIED"], [edit_then_run]).C == 1.0


def test_an_unverified_step_needs_a_passing_run_after_its_change():
    c = _contract(C05_REQUEST)
    assert gc.mark_coverage(c, ["UNVERIFIED"], ["Done.\n\nActions:\n- edit_file greet.py -> ok"]).C == 0.0
    run_then_edit = "Done.\n\nActions:\n- run_command python greet.py World -> ok\n- edit_file greet.py -> ok"
    assert gc.mark_coverage(c, ["UNVERIFIED"], [run_then_edit]).C == 0.0
    assert gc.mark_coverage(c, ["UNVERIFIED"], [C05_CHECKED + "\n\n" + NON_ZERO]).C == 0.0
    assert gc.mark_coverage(c, ["FAILED"], [C05_CHECKED]).C == 0.0                       # never a failed step
    plain = gc.Contract(required=("compare Bun vs Deno",))                                 # not a change fact
    assert gc.mark_coverage(plain, ["UNVERIFIED"], ["Bun vs Deno\n\nActions:\n- run_command python x.py -> ok"]).C == 0.0


def test_naming_a_python_file_is_not_running_the_code():
    c = _contract(C05_REQUEST)
    for cmd in ("cat greet.py", "type greet.py", "ls main.go"):
        read = f"Read it.\n\nActions:\n- run_command {cmd} -> ok"
        assert gc._checked_after_change(read) is False, cmd
        assert gc.mark_coverage(c, ["UNVERIFIED"], [read]).C == 0.0, cmd
    assert gc._checked_after_change("x\n\nActions:\n- run_command py -3 greet.py -> ok") is True


def test_a_heredoc_command_keeps_its_action_line_readable():
    from backend.agent.node_executor import NodeResult, _target

    cmd = "cat > greet.py <<'EOF'\nimport argparse\n\n\ndef main():\n    pass\nEOF\npython greet.py World"
    line = NodeResult(True, "Wrote it.", calls=[{"tool": "run_command", "target": _target({"command": cmd}), "ok": True}])
    assert gc._ACTION_RE.findall(line.as_step_result())[0][0] == "run_command"
