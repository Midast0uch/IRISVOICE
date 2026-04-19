"""
MCM — Model Context Memory trigger layer.

Provides system-triggered compression and recall for the IRIS agent runtime.
MCM makes the context window *dynamically sizable* from inside the application
rather than relying on the hosting CLI (Claude Code / OpenCode) to do it.

Key design rule (NBL-first):
  Every compress() call produces an NBL string as its primary output — a
  ≤40-token coordinate state that encodes the full session topology.  Recall
  prefers NBL over raw episodes because 33 numbers decode to full topology
  at near-zero token cost.  This is the single biggest token saving in the
  system and drives the whole architecture.

Compression lifecycle:
  1. MCM.should_compress(current_tokens, max_context) fires at 70% budget.
  2. compress() reads coordinate state → builds NBL → saves checkpoint.
  3. inject_recovery() replaces the bloated context with:
       [system_prompt, user_task, recovery_preamble]   (~200 tokens total)
  4. On next turn the agent has full topology knowledge from <40 NBL tokens.

Recall lifecycle:
  1. Agent calls recall(query) after compaction or resume.
  2. Fallback ladder: NBL checkpoint → episodic similarity → file-name match.
  3. Returns list of dicts the caller injects as context or logs.

Token counting:
  - Local path: Llama.tokenize() when a model reference is available.
  - Remote / API path: tiktoken 'cl100k_base' fallback (no model needed).
  - Rough fallback: chars / 4 (used when neither is available).
"""

from __future__ import annotations

import json
import logging
import time
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from backend.memory.interface import MemoryInterface
    from backend.memory.mycelium.store import CoordinateStore

logger = logging.getLogger(__name__)

# Compression fires at this fraction of the model's max context.
_DEFAULT_BUDGET_PCT: float = 0.70

# Target size for the recovery preamble in tokens.
_RECOVERY_TARGET_TOKENS: int = 200


class MCM:
    """
    Model Context Memory — budget-triggered compression and NBL-first recall.

    Args:
        memory_interface:   MemoryInterface instance (access to runtime DB).
        session_id:         Current agent session identifier.
        thread_id:          Immortus thread_id, if active.  None = no chain.
        budget_pct:         Fraction of max_context that triggers compression.
                            Default 0.70 (70%).
    """

    def __init__(
        self,
        memory_interface: "MemoryInterface",
        session_id: str,
        thread_id: Optional[str] = None,
        budget_pct: float = _DEFAULT_BUDGET_PCT,
    ) -> None:
        self._mi = memory_interface
        self.session_id = session_id
        self.thread_id = thread_id
        self.budget_pct = budget_pct
        self._store: Optional["CoordinateStore"] = self._resolve_store()

    # ── Public API ────────────────────────────────────────────────────────

    def should_compress(self, current_tokens: int, max_context: int) -> bool:
        """Return True when the context has consumed ≥ budget_pct of max_context."""
        if max_context <= 0:
            return False
        return (current_tokens / max_context) >= self.budget_pct

    def compress(
        self,
        active_task: Optional[str] = None,
        active_files: Optional[list] = None,
        unverified_edits: Optional[list] = None,
        warnings: Optional[list] = None,
        temporal_coord=None,
    ) -> dict:
        """
        Compress the current session state into a lightweight checkpoint.

        Steps:
          1. Build NBL string (≤40 tokens, primary output).
          2. Save checkpoint to mcm_checkpoints (NBL is the key payload).
          3. Append memory_chain entry (if thread_id is set).
          4. Return a recovery dict the caller passes to inject_recovery().

        Returns dict with keys:
          nbl, active_task, active_files, unverified_edits, warnings,
          recovery_preamble (≤200 token string), compressed_at.
        """
        nbl = self._build_nbl(temporal_coord)
        active_files = active_files or []
        unverified_edits = unverified_edits or []
        warnings = warnings or []

        # Save checkpoint to runtime DB
        if self._store:
            try:
                self._store.save_checkpoint(
                    session_id=self.session_id,
                    nbl=nbl,
                    active_task=active_task,
                    active_files=active_files,
                    unverified_edits=unverified_edits,
                    warnings=warnings,
                )
            except Exception as exc:
                logger.warning("[MCM] checkpoint save failed: %s", exc)

        # Append to memory chain (Immortus Layer 1b)
        if self._store and self.thread_id:
            try:
                self._store.chain_append(
                    thread_id=self.thread_id,
                    result="landmark",
                    coords_from=["context"],
                    coords_to=["capability"],
                    nbl_outcome=" ".join(nbl.split()[:6]),  # first 6 tokens
                    insight=f"MCM compress: {(active_task or '')[:60]}",
                )
                self._store.chain_distill(self.thread_id, threshold=50)
            except Exception as exc:
                logger.warning("[MCM] chain_append failed: %s", exc)

        recovery_preamble = self._build_recovery_preamble(
            nbl, active_task, active_files, unverified_edits, warnings
        )

        return {
            "nbl": nbl,
            "active_task": active_task,
            "active_files": active_files,
            "unverified_edits": unverified_edits,
            "warnings": warnings,
            "recovery_preamble": recovery_preamble,
            "compressed_at": time.time(),
        }

    def recall(self, query: str) -> list[dict]:
        """
        Recall relevant context for *query* using the NBL-first fallback ladder:

          1. Load NBL checkpoint for session_id  (≤40 tokens, free).
          2. Search episodic memory for similar tasks via semantic retrieval.
          3. File-name match against active_files in the checkpoint.

        Returns a list of result dicts.  Callers inject these into context
        or display them as a "recovering state" preamble.
        """
        results: list[dict] = []

        # Pass 1 — NBL checkpoint (always try this first)
        checkpoint = self._load_checkpoint()
        if checkpoint:
            results.append({
                "source": "nbl_checkpoint",
                "session_id": self.session_id,
                "nbl": checkpoint.get("nbl", ""),
                "active_task": checkpoint.get("active_task"),
                "active_files": checkpoint.get("active_files", []),
                "unverified_edits": checkpoint.get("unverified_edits", []),
            })

        # Pass 2 — episodic similarity search
        if self._mi and hasattr(self._mi, "episodic") and self._mi.episodic:
            try:
                ep_ctx = self._mi.episodic.assemble_episodic_context(query)
                if ep_ctx and ep_ctx.strip():
                    results.append({
                        "source": "episodic",
                        "content": ep_ctx.strip(),
                    })
            except Exception as exc:
                logger.debug("[MCM] episodic recall skipped: %s", exc)

        # Pass 3 — file-name match in checkpoint active_files
        if checkpoint and query:
            q_lower = query.lower()
            matched = [
                f for f in checkpoint.get("active_files", [])
                if q_lower in f.lower()
            ]
            if matched:
                results.append({
                    "source": "file_match",
                    "files": matched,
                })

        return results

    def inject_recovery(
        self, messages: list[dict], compressed: dict
    ) -> list[dict]:
        """
        Replace *messages* with a compact recovery context.

        Keeps:
          - messages[0]  (system prompt)
          - A fresh user message containing the active task
          - A system message with the recovery_preamble

        This brings the context from potentially 20k+ tokens down to ~200.
        """
        if not messages:
            return messages

        system_msg = messages[0]
        task = compressed.get("active_task") or "Continue previous task."
        preamble = compressed.get("recovery_preamble", "")

        recovered = [
            system_msg,
            {"role": "user", "content": task},
        ]
        if preamble:
            recovered.append({"role": "system", "content": preamble})

        logger.info(
            "[MCM] Context replaced: %d → %d messages", len(messages), len(recovered)
        )
        return recovered

    # ── Token counting ─────────────────────────────────────────────────────

    @staticmethod
    def count_tokens(messages: list[dict], model_ref=None) -> int:
        """
        Count tokens in *messages* using the best available method.

          1. model_ref.tokenize() — local Llama.cpp model.
          2. tiktoken 'cl100k_base' — remote/API path.
          3. chars / 4 — rough fallback.
        """
        text = " ".join(
            m.get("content", "") if isinstance(m.get("content"), str)
            else json.dumps(m.get("content", ""))
            for m in messages
        )
        if model_ref is not None:
            try:
                tokens = model_ref.tokenize(text.encode(), add_bos=False)
                return len(tokens)
            except Exception:
                pass
        try:
            import tiktoken
            enc = tiktoken.get_encoding("cl100k_base")
            return len(enc.encode(text))
        except Exception:
            pass
        return max(1, len(text) // 4)

    # ── Internal helpers ───────────────────────────────────────────────────

    def _resolve_store(self) -> Optional["CoordinateStore"]:
        """Extract the runtime CoordinateStore from MemoryInterface if available."""
        if self._mi is None:
            return None
        try:
            mycelium = getattr(self._mi, "_mycelium", None)
            if mycelium is None:
                return None
            return getattr(mycelium, "_store", None)
        except Exception:
            return None

    def _build_nbl(self, temporal_coord) -> str:
        """Build NBL string via the shared nbl module."""
        try:
            from backend.memory.nbl import build_nbl
            conn = self._get_conn()
            if conn is not None:
                return build_nbl(
                    conn,
                    session_id=self.session_id,
                    thread_id=self.thread_id,
                    temporal_coord=temporal_coord,
                )
        except Exception as exc:
            logger.warning("[MCM] NBL build failed: %s", exc)
        return "MYCELIUM: context:[0.10,0.00,0.00]@gate1 | confidence:0.10"

    def _get_conn(self):
        """Get the raw DB connection from the memory interface."""
        try:
            mycelium = getattr(self._mi, "_mycelium", None)
            if mycelium:
                return getattr(mycelium, "_conn", None)
        except Exception:
            pass
        return None

    def _load_checkpoint(self) -> Optional[dict]:
        if self._store:
            try:
                return self._store.load_checkpoint(self.session_id)
            except Exception:
                pass
        return None

    def _build_recovery_preamble(
        self,
        nbl: str,
        active_task: Optional[str],
        active_files: list,
        unverified_edits: list,
        warnings: list,
    ) -> str:
        """Build the ≤200-token recovery preamble injected after compression."""
        lines = ["## MCM Recovery State"]
        lines.append(nbl)

        if active_task:
            lines.append(f"Active task: {active_task[:120]}")

        if active_files:
            files_str = ", ".join(active_files[:5])
            if len(active_files) > 5:
                files_str += f" (+{len(active_files) - 5} more)"
            lines.append(f"Active files: {files_str}")

        if unverified_edits:
            edits_str = ", ".join(unverified_edits[:3])
            lines.append(f"⚠ Unverified edits: {edits_str}")

        if warnings:
            lines.append(f"⚠ Warnings: {'; '.join(str(w) for w in warnings[:2])}")

        lines.append("Trust the NBL above — do NOT re-read files already in active_files.")
        return "\n".join(lines)
