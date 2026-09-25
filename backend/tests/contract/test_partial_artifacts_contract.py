"""Contract: a multi-file ask is COMPLETED, not silently truncated.

LIVE 2026-09-25: "create three files in the repo root: vv_a.md, vv_b.md and
vv_c.md, each with one bullet about tea, then read all three back to me" wrote
ONE file. A DER step is ONE tool call (``ToolDecisionBox.resolve`` is
single-shot), so that step could never write the other two — and the run still
told the user the files had been created.

The detector is pure and bounded; the graft that fixes it is wired into the DER
loop after every file-writing step finalizes (pinned by a source contract).
"""
import inspect

from backend.agent.agent_kernel import AgentKernel


def test_declared_file_names_are_extracted_in_order_and_deduped():
    text = ("create three files in the repo root: vv_a.md, vv_b.md and vv_c.md, "
            "each with one bullet about tea, then read all three back to me")
    assert AgentKernel._declared_file_names(text) == ["vv_a.md", "vv_b.md", "vv_c.md"]
    # Deduped, order preserved, unrelated words ignored.
    assert AgentKernel._declared_file_names("b.md then a.md then b.md") == ["b.md", "a.md"]
    assert AgentKernel._declared_file_names("no file names here") == []
    # Bounded, whatever the task says.
    assert len(AgentKernel._declared_file_names(" ".join(f"f{i}.md" for i in range(20)))) == 8


def test_artifact_missing_means_absent_or_empty(tmp_path):
    present = tmp_path / "present.md"
    present.write_text("- tea", encoding="utf-8")
    empty = tmp_path / "empty.md"
    empty.write_text("", encoding="utf-8")
    assert AgentKernel._artifact_missing(str(present)) is False
    # The 0-byte file IS missing work, even though the path exists.
    assert AgentKernel._artifact_missing(str(empty)) is True
    assert AgentKernel._artifact_missing(str(tmp_path / "ghost.md")) is True


def test_the_der_loop_grafts_the_remainder_after_a_file_step():
    """Source contract: the remainder check runs AFTER the step is finalized.

    Before it, the step that owes the files is still in flight and the queue
    cannot accept the grafts.
    """
    src = inspect.getsource(AgentKernel)
    finalize_at = src.find("_tokens_used = self._der_finalize_step(")
    graft_at = src.find("self._der_graft_missing_artifacts(")
    assert finalize_at != -1, "the DER step finalize call moved or was renamed"
    assert graft_at != -1, "the DER loop no longer grafts missing artifacts"
    assert graft_at > finalize_at, (
        "the remainder graft must run AFTER _der_finalize_step"
    )
    # Bounded three ways: tool scope, the shared graft budget, one attempt each.
    assert "DER_MAX_GRAFTS" in src
    assert "_artifact_graft_attempted" in src
