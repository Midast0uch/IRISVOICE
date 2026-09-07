"""Dynamic multi-angle query synthesis (T13 / REQ-13).

Two surfaces:
  - ``QuerySynthesizer.new_queue_item(task, brain)``: produces ONE
    ``QueryBatch`` of 2-4 orthogonal facets (axis + query string) to be
    scheduled as a DER batch node — never a single fused query.
  - ``StepFindingsAccumulator``: tracks schema-field coverage as pages are
    ingested by the batch. When a declared field remains untracked the runner
    asks the Brain for a targeted follow-up query and enqueues it WITHOUT
    restarting the plan (AC13.3). No missing fields → no extra query (so
    long runs don't keep asking for more).

Both surfaces never raise. A planner/LLM failure falls back to a single
query driven by the task text, and a missing-field follow-up that produces
nothing leaves the accumulator untouched.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable, Iterable, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class QueryFacet:
    """One orthogonal query — order-preserving string + the axis it tracks.

    axis ∈ {specs, pricing, benchmarks, issues, regulatory, custom} — the
    canonical axes the harness maps to tool/capability lanes.
    """

    axis: str
    query: str


@dataclass
class QueryBatch:
    """The synthesized set ready to dispatch as a BatchToolCall."""

    task: str
    queries: List[QueryFacet] = field(default_factory=list)

    def urls(self) -> list[str]:
        """Union of urls referenced through typical facets — some planners
        produce URLs inline; this lets a batch dispatch merge them by
        normalized path."""
        seen: set[str] = set()
        out: list[str] = []
        for f in self.queries:
            u = getattr(f, "url", None)
            if u and u not in seen:
                seen.add(u)
                out.append(u)
        return out


def synthesize_for_task(
    task: str,
    *,
    brain: Optional[Callable[[str, int, list], List[str]]] = None,
) -> QueryBatch:
    """Ask the Brain for 2–4 orthogonal facets; never raise. If the LLM is
    unavailable, fall back to a single task-text query so the run never
    starves.

    ``brain(task, n_needed, existing_queries)`` returns raw query strings
    in axis order. We wrap them as (axis, text) pairs; existing state is
    supplied so the Brain avoids re-asking a facet it already covered.
    """
    task = (task or "").strip()
    if not task:
        return QueryBatch(task="", queries=[])

    axes_seed = ["specs", "pricing", "reviews"]
    existing: List[str] = []
    texts: List[str] = []
    if brain is not None:
        try:
            # One call, then pair by axis order.
            texts = list(brain(task, 3, existing) or [])
        except Exception as exc:  # noqa: BLE001 — never fail a plan for this
            logger.info("[query_synth] brain unavailable: %s (task=%s)", exc, task[:60])
    if not texts:
        texts = [f"{task} — full context"]

    facets: List[QueryFacet] = []
    for i, text in enumerate(texts[:3]):
        if not text or not str(text).strip():
            continue
        # Axis assignment preserves i but dedupes: same axis twice collapses
        # because the axes list is the canonical universe of coverage.
        current = axes_seed[i] if i < len(axes_seed) else f"axis_{i}"
        facets.append(QueryFacet(axis=current, query=str(text)))
    # De-dupe by axis so the DAG never carries the same axis twice
    facets = [f for i, f in enumerate(facets) if f.axis not in [a.axis for a in facets[:i]]]
    return QueryBatch(task=task, queries=facets)


class QuerySynthesizer:
    """Stateless facade kept for API parity with the original design."""

    @staticmethod
    def synthesize(task: str, **kw) -> QueryBatch:
        return synthesize_for_task(task, **kw)


def _norm(url: str) -> str:
    """Normalize a URL for dedup: lowercase, strip trailing slash."""
    return (url or "").rstrip("/").lower()


class StepFindingsAccumulator:
    """REQ-13 AC3/AC4: batch findings the search runs accrue into the DAG.

    The DER session marks fields found; when a declared field remains absent,
    a follow-up query is synthesized and enqueued — targetedly, not a blind
    re-run of the same query. The DAG adds the follow-up to the SAME batch
    node without restarting done work.
    """

    def __init__(self, goal_fields: set[str]):
        self._goal_fields = {str(f) for f in goal_fields if str(f).strip()}
        self._found_fields: set[str] = set()
        self._seen_urls: set[str] = set()
        self.url_count = 0

    def ingest(self, result: dict, url: str) -> None:
        """Fold one page's extracted JSON payload into the covered-field set."""
        if url:
            self._seen_urls.add(_norm(url))
        self.url_count = len(self._seen_urls)
        for k in self._goal_fields:
            v = result.get(k)
            if v is not None:
                self._found_fields.add(k)

    def missing_fields(self) -> list[str]:
        return sorted(self._goal_fields - self._found_fields)

    def missing_followups(self, brain: Callable[[str, list], List[str]]) -> List[str]:
        """Ask the Brain for a follow-up query ONLY if a goal field is
        missing. Returns the follow-up URLs the Brain proposes (it may
        produce none at all, in which case nothing is queued)."""
        missing = self.missing_fields()
        if not missing:
            return []
        task = "missing: " + ", ".join(missing)
        try:
            return list(brain(task, missing) or [])
        except Exception as exc:  # noqa: BLE001 — never fail the run
            logger.info("[StepFindingsAccumulator] follow-up synthesis failed: %s", exc)
            return []
