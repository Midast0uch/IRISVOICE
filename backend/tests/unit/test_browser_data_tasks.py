"""The browser_data eval group: 4 multi-page extract-and-compute tasks in personal mode.

Each reply_pattern set (all must match, case-insensitive, as run_evals.py judges) accepts a
correct sample answer and rejects a near-miss (one off / wrong tag). Expected values were read
from the public practice sites on 2026-11-17.
"""
import importlib.util
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]

# id -> (correct sample, near-miss)
SAMPLES = {
    "d01_einstein_quote_count": ("There are 6 quotes by Albert Einstein on pages 1 to 3.",
                                 "There are 5 quotes by Albert Einstein on pages 1 to 3."),
    "d02_page1_top_tag": ("The tag 'inspirational' appears most often: 3 times.",
                          "The tag 'life' appears most often: 2 times."),
    "d03_books_top5_total": ("The five prices total £269.66.",
                            "The five prices total £268.66."),
    "d04_countries_first3_population": ("The sum is 34,180,879.",
                                        "The sum is 34,180,878."),
}


def _tasks():
    data = json.loads((ROOT / "evals" / "tasks.json").read_text(encoding="utf-8"))
    return {t["id"]: t for t in data["tasks"] if t.get("group") == "browser_data"}


def _passes(task, text):
    return all(re.search(p, text, re.IGNORECASE) for p in task["reply_patterns"])


def test_four_personal_browser_data_tasks():
    tasks = _tasks()
    assert set(tasks) == set(SAMPLES)
    for t in tasks.values():
        assert t["mode"] == "personal" and t["group"] == "browser_data"


def test_patterns_accept_correct_and_reject_near_miss():
    for tid, task in _tasks().items():
        good, near = SAMPLES[tid]
        assert _passes(task, good), tid
        assert not _passes(task, near), tid


def test_cohorts_cover_browser_groups():
    spec = importlib.util.spec_from_file_location("wb_ab_analysis", ROOT / "evals" / "wb_ab_analysis.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    for name in ("browser", "browser_goal", "browser_data"):
        assert name in mod.COHORTS
    assert mod.cohort_of("d03_books_top5_total") == "browser_data"
    assert mod.cohort_of("g01_quote_author_birth") == "browser_goal"
    assert mod.cohort_of("b05_python_docs_library") == "browser"


def test_the_runner_switches_the_web_on_for_browser_data():
    """2026-11-17: the browser_data smoke runs replied "Web search is currently disabled" -
    the runner turned the web on only for research / browser / browser_goal."""
    src = (Path(__file__).resolve().parents[3] / "evals" / "run_evals.py").read_text(encoding="utf-8")
    assert '"browser_data"' in next(l for l in src.splitlines() if 'task["group"] in ("research"' in l)
