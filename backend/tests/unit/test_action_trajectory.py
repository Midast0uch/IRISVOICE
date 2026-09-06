"""Unit tests for ActionTrajectory + visual delta (REQ-17, T7).

Pure-logic tests: sliding window, no-progress detection, prompt formatting,
termination gate, and the delta metric (PIL-generated fixtures).
"""

import io

import pytest

from backend.vision.fetch_vision import (
    NO_PROGRESS_DELTA,
    NO_PROGRESS_LIMIT,
    TRAJECTORY_WINDOW,
    ActionTrajectory,
    visual_delta,
)

PIL = pytest.importorskip("PIL", reason="delta fixtures need PIL")
from PIL import Image  # noqa: E402


def _png(color, size=(100, 80)):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


def _png_noisy(base=(10, 10, 10), size=(100, 80)):
    img = Image.new("RGB", size)
    px = img.load()
    for x in range(size[0]):
        for y in range(size[1]):
            px[x, y] = ((x * 13 + y * 7) % 256, base[1], base[2])
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_identical_frames_score_zero():
    shot = _png("red")
    assert visual_delta(shot, shot) == 0.0


def test_first_frame_scores_changed():
    assert visual_delta(None, _png("red")) == 1.0


def test_different_frames_score_above_threshold():
    assert visual_delta(_png("black"), _png_noisy()) > NO_PROGRESS_DELTA


def test_trajectory_window_keeps_last_three():
    traj = ActionTrajectory()
    for i in range(5):
        traj.record(f"act{i}", target=f"t{i}", outcome="ok", visual_delta=0.9)
    assert len(traj) == TRAJECTORY_WINDOW
    assert [s.action for s in traj.window_steps()] == ["act2", "act3", "act4"]


def test_zero_delta_streak_and_termination():
    """AC17.3: three consecutive no-progress actions terminate the loop."""
    traj = ActionTrajectory()
    assert not traj.should_terminate
    traj.record("click", target="a", outcome="ok", visual_delta=0.9)
    traj.record("click", target="b", outcome="ok", visual_delta=0.01)
    assert traj.no_progress_streak() == 1
    assert not traj.should_terminate
    traj.record("click", target="c", outcome="ok", visual_delta=0.02)
    traj.record("click", target="d", outcome="ok", visual_delta=0.0)
    assert traj.no_progress_streak() == NO_PROGRESS_LIMIT
    assert traj.should_terminate


def test_same_target_twice_counts_as_no_progress():
    """AC4.2: retargeting the same element twice stalls even with big delta."""
    traj = ActionTrajectory()
    traj.record("click", target="x", outcome="ok", visual_delta=0.9)
    traj.record("click", target="x", outcome="ok", visual_delta=0.9)
    assert traj.no_progress_streak() == 1


def test_progress_resets_streak():
    traj = ActionTrajectory()
    traj.record("click", target="a", outcome="ok", visual_delta=0.9)
    traj.record("click", target="a", outcome="ok", visual_delta=0.9)
    traj.record("click", target="b", outcome="ok", visual_delta=0.8)
    assert traj.no_progress_streak() == 0
    assert not traj.should_terminate


def test_prompt_formats_window_and_negative_constraint():
    """AC17.2: last-3 window plus the prohibition line when stalled."""
    traj = ActionTrajectory()
    assert "No prior actions" in traj.format_prompt()
    traj.record("click", target="a", params={"x": 1}, outcome="ok", visual_delta=0.9)
    traj.record("click", target="b", outcome="ok", visual_delta=0.01)
    text = traj.format_prompt()
    assert "click" in text and "'b'" in text and "delta=0.01" in text
    assert "Negative constraint" in text and "do NOT repeat" in text
    traj.record("click", target="c", outcome="ok", visual_delta=0.0)
    traj.record("click", target="d", outcome="ok", visual_delta=0.0)
    assert "TERMINATE" in traj.format_prompt()
