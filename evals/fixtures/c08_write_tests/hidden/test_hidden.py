"""The agent's tests must pass on the real Stack and catch broken ones."""

import shutil
import subprocess
import sys

import conftest as h
import pytest

MUTANTS = {
    "pop_returns_none_when_empty": ("        if not self._items:\n            raise IndexError(\"pop from empty stack\")\n        return self._items.pop()",
                                    "        if not self._items:\n            return None\n        return self._items.pop()"),
    "peek_removes_item": ("        return self._items[-1]", "        return self._items.pop()"),
    "len_off_by_one": ("        return len(self._items)", "        return len(self._items) + 1"),
    "pop_takes_first": ("        return self._items.pop()", "        return self._items.pop(0)"),
}


def _run_suite(folder):
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "test_stack.py"],
        cwd=folder, capture_output=True, text=True, timeout=120,
    )


def test_suite_exists_and_passes():
    assert (h.WORKDIR / "test_stack.py").is_file()
    proc = _run_suite(h.WORKDIR)
    assert proc.returncode == 0, proc.stdout[-500:]


def test_suite_has_enough_tests():
    text = h.read("test_stack.py")
    assert text.count("def test") >= 5


def test_stack_itself_unchanged():
    assert h.unchanged("stack.py")


@pytest.mark.parametrize("name", sorted(MUTANTS))
def test_suite_catches_mutant(name, tmp_path):
    original, broken = MUTANTS[name]
    source = (h.HIDDEN / "originals" / "stack.py").read_text(encoding="utf-8")
    assert original in source, "mutant pattern out of date"
    (tmp_path / "stack.py").write_text(source.replace(original, broken, 1), encoding="utf-8")
    shutil.copy2(h.WORKDIR / "test_stack.py", tmp_path / "test_stack.py")
    proc = _run_suite(tmp_path)
    assert proc.returncode != 0, f"tests did not catch mutant {name}"
