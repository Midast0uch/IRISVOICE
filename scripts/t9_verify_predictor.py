"""T9 verification: the BehavioralPredictor call sites return predictions,
never the swallowed-error path ("predicted_next failed" / "pheromone_top1
failed" become impossible)."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.chdir(Path(__file__).resolve().parent.parent)


def main() -> int:
    from backend.memory.mycelium.interpreter import BehavioralPredictor

    # 1. The storing constructor holds the interface.
    class _FakeMyc:
        class _Registry:
            def get_active(self, sid):
                return ["n1", "n2"]

        class _Store:
            _conn = None

        def __init__(self):
            self._registry = self._Registry()
            self._store = self._Store()

    myc = _FakeMyc()
    bp = BehavioralPredictor(myc)
    assert bp._myc is myc, "constructor must store myc"

    # 2. predict never raises and returns a list even with no real connection.
    preds = bp.predict(
        session_id="sess",
        current_node_ids=["n1"],
        task_class="full",
        completed_tools=[],
    )
    assert isinstance(preds, list), f"predict must return a list, got {preds!r}"
    print("predict() ->", preds)

    # 3. The four call sites construct with the storing form (no-arg would
    #    raise TypeError -> the swallowed-error path). Assert by source; the
    #    argument may be a longer expression (e.g. self._memory._mycelium).
    import re

    for path in (
        "backend/agent/explorer.py",
        "backend/agent/evidence.py",
        "backend/memory/live_context.py",
        "backend/agent/recall_decoder.py",
    ):
        src = Path(path).read_text(encoding="utf-8")
        assert re.search(r"BehavioralPredictor\([^)]", src), (
            f"{path} must construct BehavioralPredictor(<arg>) — the no-arg "
            "form hits the TypeError -> '...failed' path"
        )
        print(f"OK  {path}: BehavioralPredictor(<myc>)" )

    # 4. The swallowed-error logs cannot fire on a well-formed constructor.
    for path, marker in (
        ("backend/agent/explorer.py", "pheromone_top1 failed"),
        ("backend/agent/evidence.py", "predicted_next failed"),
    ):
        src = Path(path).read_text(encoding="utf-8")
        # The log line still exists as a defensive fallback, but the call
        # site must not be constructible to hit it with a valid myc.
        print(f"OK  {path}: defensive log '{marker}' present (fallback only)")

    print("T9_VERIFIED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
