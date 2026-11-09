"""Contract: the tool_choice action-class label (the Oracle's own question).

Measured 2026-11-07: the outcome label graded the assistant's execution, not the
Oracle's pick. All 5 failed rows chose read_file for a read/inspect/verify step.
This label asks only what the Oracle controls: the tool CLASS.
"""
from backend.agent.tool_choice_action_class import (
    READ, RUN, WRITE, action_class_ok, allowed_tools, always_enabled,
    class_decision_enabled, class_masses, classify_tool, required_class,
    required_classes, shortlist_from_distribution, shortlist_k,
)


def test_tool_classes():
    assert classify_tool("read_file") == READ
    assert classify_tool("grep_files") == READ
    assert classify_tool("write_file") == WRITE
    assert classify_tool("edit_file") == WRITE
    assert classify_tool("run_command") == RUN
    assert classify_tool("unknown_tool") == "UNKNOWN"


def test_read_goal_needs_read():
    goal = "Read calc.py and determine which functions implement multiplication"
    assert required_class(goal) == READ
    assert action_class_ok("read_file", goal) is True
    assert action_class_ok("edit_file", goal) is False


def test_the_action_is_the_first_verb_not_a_noun():
    # "implementation" must not make this a WRITE step; "test configuration"
    # must not make it a RUN step.
    assert required_class(
        "Read textstats.py and assess each function's implementation") == READ
    assert required_class(
        "Identify the project's test suite and runner configuration") == READ


def test_run_goal_needs_run():
    goal = "Run the focused duration tests and the complete suite"
    assert required_class(goal) == RUN
    assert action_class_ok("run_command", goal) is True
    # read is always safe; a WRITE is the wrong class in a run step
    assert action_class_ok("read_file", goal) is True
    assert action_class_ok("edit_file", goal) is False


def test_create_acts_now_but_fix_gathers_first():
    assert required_class("Create a module named textutils.py") == WRITE
    assert required_class("Fix the bug in mathutils.py") == READ
    assert required_class("Fix the bug in mathutils.py",
                          "read_file mathutils.py ok") == WRITE


def test_ambiguous_goal_is_not_labelled():
    assert required_class("Handle the request") is None
    assert action_class_ok("read_file", "Handle the request") is None


def test_plan_phase_stops_false_misses():
    # s1 gathers, so a read is right even for a "fix" plan.
    assert action_class_ok("read_file", "Implement parse_duration", "", "s1") is True
    # s2 acts: the edit is right; a read in s2 is allowed while gathering.
    assert action_class_ok("edit_file", "Implement parse_duration", "", "s2") is True
    assert action_class_ok("read_file", "Implement parse_duration", "", "s2") is True
    # s3 runs or verifies; a run is right for a verify+execute step.
    assert action_class_ok("run_command", "Verify and execute the entry point", "", "s3") is True
    # read is always safe: a READ pick on a Run step is allowed (gather)
    assert action_class_ok("read_file", "Run the full test suite", "", "s3") is True
    # a WRITE on a pure read step is the wrong class
    assert action_class_ok("edit_file", "Read mathutils.py", "", "s1") is False


def test_the_guard_narrows_the_menu_to_the_required_class():
    tools = ["read_file", "grep_files", "edit_file", "write_file", "run_command"]
    kept, need = allowed_tools(tools, "Read mathutils.py")
    assert need == frozenset({READ})
    assert kept == ["read_file", "grep_files"]
    # read is ALWAYS allowed: a run step may gather before it runs
    kept, need = allowed_tools(tools, "Run the test suite")
    assert need == frozenset({READ, RUN})
    assert kept == ["read_file", "grep_files", "run_command"]
    # a known class with no offered tool -> empty, the caller abstains
    kept, need = allowed_tools(["edit_file"], "Read mathutils.py")
    assert need == frozenset({READ})
    assert kept == []
    # an unknown goal -> no guard (None), the full menu stays
    kept, need = allowed_tools(tools, "Handle the request")
    assert need is None
    assert kept == tools


def test_the_shortlist_is_the_oracle_top_k_without_controls():
    from types import SimpleNamespace

    dist = [
        SimpleNamespace(name="edit_file", prob=0.05),
        SimpleNamespace(name="read_file", prob=0.60),
        SimpleNamespace(name="grep_files", prob=0.20),
        SimpleNamespace(name="run_command", prob=0.10),
        SimpleNamespace(name="NONE", prob=0.05),
        SimpleNamespace(name="DELEGATE", prob=0.00),
    ]
    assert shortlist_from_distribution(dist, 2) == ["read_file", "grep_files"]
    assert shortlist_from_distribution(dist, 4) == [
        "read_file", "grep_files", "run_command", "edit_file"]
    assert shortlist_from_distribution(dist, 0) == []


def test_a_low_value_tool_is_demoted_not_removed():
    from types import SimpleNamespace

    dist = [
        SimpleNamespace(name="list_directory", prob=0.50),
        SimpleNamespace(name="read_file", prob=0.35),
        SimpleNamespace(name="grep_files", prob=0.10),
    ]
    # list_directory - 0.20 = 0.30, below read_file's 0.35
    assert shortlist_from_distribution(dist, 2) == ["read_file", "list_directory"]
    # but it is still present when there is room
    assert "list_directory" in shortlist_from_distribution(dist, 3)


def test_the_shortlist_depth_reads_the_env(monkeypatch):
    monkeypatch.delenv("IRIS_ORACLE_TOOL_CHOICE_SHORTLIST_K", raising=False)
    assert shortlist_k() == 0
    monkeypatch.setenv("IRIS_ORACLE_TOOL_CHOICE_SHORTLIST_K", "5")
    assert shortlist_k() == 5
    monkeypatch.setenv("IRIS_ORACLE_TOOL_CHOICE_SHORTLIST_K", "junk")
    assert shortlist_k() == 0


def test_the_always_enforce_flag_reads_the_env(monkeypatch):
    monkeypatch.delenv("IRIS_ORACLE_TOOL_CHOICE_ALWAYS", raising=False)
    assert always_enabled() is False
    monkeypatch.setenv("IRIS_ORACLE_TOOL_CHOICE_ALWAYS", "1")
    assert always_enabled() is True
    monkeypatch.setenv("IRIS_ORACLE_TOOL_CHOICE_ALWAYS", "0")
    assert always_enabled() is False

def test_class_masses_and_margin():
    from types import SimpleNamespace

    dist = [
        SimpleNamespace(name="read_file", prob=0.60),
        SimpleNamespace(name="grep_files", prob=0.10),
        SimpleNamespace(name="edit_file", prob=0.20),
        SimpleNamespace(name="run_command", prob=0.10),
    ]
    masses, margin = class_masses(dist)
    assert round(masses[READ], 6) == 0.70
    assert round(masses[WRITE], 6) == 0.20
    assert round(masses[RUN], 6) == 0.10
    assert round(margin, 6) == 0.50


def test_the_class_decision_flag_reads_the_env(monkeypatch):
    monkeypatch.delenv("IRIS_ORACLE_TOOL_CHOICE_CLASS_DECISION", raising=False)
    assert class_decision_enabled() is False
    monkeypatch.setenv("IRIS_ORACLE_TOOL_CHOICE_CLASS_DECISION", "1")
    assert class_decision_enabled() is True
