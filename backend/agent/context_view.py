"""The live view (CLM-1, specs/clm-memory) - Wave 1: parity only.

Plain picture: the desk. Every paper that reaches the desk is a Block with a
filing number (Ref). ``render()`` lays the papers out in the order they were
admitted and hands the provider the same message list the old builder made.
Nothing leaves the desk in this wave: no zones, no policy, no placeholders.

The view is derived and in memory: built from the record per turn or run,
never persisted. It never mutates what it is given (the lists, and so
``ConversationMemory.messages``, design Q4): it stores a copy of each list and
renders fresh dict copies.

Pure module: no I/O, no kernel import. Single-threaded by design (one view
per turn or run, never shared between conversations), so it holds no lock.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from backend.agent.context_gauge import estimate_tokens

# Block kinds on the direct path. These are the names the Wave 0 instrument
# already uses (``clm_baseline.record_direct`` parts), so the baseline and the
# view speak the same words. The node path adds its kinds in T1.3.
SYSTEM_PROMPT = "system_prompt"
RECALL_EPISODIC = "recall_episodic"
RECALL_PROFILE = "recall_profile"
RECALL_CHUNKS = "recall_chunks"
HISTORY = "history"
CURRENT_USER = "current_user"


@dataclass(frozen=True)
class Ref:
    """Address of a block in the record. ``ephemeral`` has no row (id is "")."""

    kind: str           # "chunk" | "chain" | "episode" | "thread" | "pin" | "landmark" | "ephemeral"
    id: str = ""
    thread_id: str = ""  # incidence key (recall REQ-10)


EPHEMERAL = Ref(kind="ephemeral")


@dataclass
class Block:
    block_id: str       # short, stable within the view: "b1" (what the model names)
    ref: Ref
    kind: str
    messages: List[Dict[str, Any]]  # provider-shaped; a tool call stays with its result
    tokens: int         # raw gauge count at admit (``estimate_tokens``, uncalibrated)
    ts: float = 0.0
    zone: str = ""      # unused until Wave 4; carried so the data model is final
    domain: str = ""
    open_items: Tuple[Any, ...] = ()
    protected: bool = False


class ContextView:
    """Blocks in admission order; ``render()`` returns the provider messages."""

    def __init__(self) -> None:
        self._blocks: List[Block] = []

    @property
    def blocks(self) -> Tuple[Block, ...]:
        return tuple(self._blocks)

    def admit(
        self,
        kind: str,
        messages: Sequence[Dict[str, Any]],
        *,
        ref: Optional[Ref] = None,
        ts: float = 0.0,
        zone: str = "",
        domain: str = "",
        open_items: Tuple[Any, ...] = (),
        protected: bool = False,
    ) -> Block:
        """Append one block, in the order the old builder appended its messages.

        An empty ``messages`` admits an empty block (it renders nothing), so a
        call site can admit every part unconditionally, in order.
        """
        held = [dict(m) for m in messages]
        block = Block(
            block_id=f"b{len(self._blocks) + 1}",
            ref=ref if ref is not None else EPHEMERAL,
            kind=kind,
            messages=held,
            tokens=estimate_tokens(held),
            ts=ts,
            zone=zone,
            domain=domain,
            open_items=open_items,
            protected=protected,
        )
        self._blocks.append(block)
        return block

    def render(self) -> List[Dict[str, Any]]:
        """The provider message list: blocks in order, fresh dict copies.

        The dicts are shallow copies: a caller that edits a rendered message
        does not touch the view or the record. Nested values (``tool_calls``)
        are shared, as they are in the old builder's list.
        """
        return [dict(m) for block in self._blocks for m in block.messages]
