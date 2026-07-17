"""
Extract + Cite (REQ-8).

Runs DataExtractor to build the structured DashboardData, then binds EVERY factual
claim to a chunk_id (-> url) producing cited_markdown with `[n](url)` annotations.
Claims that cannot be grounded are flagged `[?]` and recorded in unsourced_claims.
"""
from __future__ import annotations

import logging
import re

from .crawler_engine import CrawlResult
from .orchestrator import Passage

logger = logging.getLogger(__name__)


async def extract_and_cite(
    query: str,
    fetched: CrawlResult,
    passages: list[Passage],
    instructions: str,
    result_type: str,
    title: str,
    extractor=None,
) -> tuple[dict, str, list[int]]:
    """Return (dashboard_data, cited_markdown, unsourced_claim_indices)."""
    # 1) Extract structured answer via the real DataExtractor (REQ-8 AC1)
    if extractor is None:
        from .data_extractor import get_data_extractor
        extractor = get_data_extractor()
    try:
        dashboard_data = await extractor.extract(
            result=fetched, instructions=instructions,
            result_type=result_type, title=title,
        )
    except Exception as exc:
        logger.error("[cite] extraction failed: %s", exc)
        dashboard_data = {"title": title, "summary": "", "key_findings": [], "sources": []}

    # 2) Build cited_markdown by grounding each summary sentence to a passage (REQ-8 AC2-AC4)
    summary = (dashboard_data.get("summary") or dashboard_data.get("answer") or "")
    cited_markdown, unsourced = _bind_citations(summary, passages)

    # 3) Also annotate key_findings if present
    findings = dashboard_data.get("key_findings") or []
    if findings:
        annotated = []
        for f in findings:
            cm, un = _bind_citations(str(f), passages)
            annotated.append(cm)
            unsourced.extend(un)
        dashboard_data["key_findings"] = annotated

    return dashboard_data, cited_markdown, unsourced


def _bind_citations(text: str, passages: list[Passage]) -> tuple[str, list[int]]:
    """Annotate each sentence with the best-matching passage's url; flag unsourced."""
    if not text.strip():
        return text, []
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    out_parts: list[str] = []
    unsourced: list[int] = []
    # precompute passage token sets for grounding
    passage_tokens = [_tok(p.text) for p in passages]

    for idx, sent in enumerate(sentences):
        if not sent.strip():
            continue
        best_idx, best_overlap = _best_match(sent, passage_tokens, passages)
        if best_idx is None or best_overlap < 1:
            out_parts.append(f"{sent} [?]")  # REQ-8 AC4: unsourced marker
            unsourced.append(idx)
        else:
            url = passages[best_idx].url
            out_parts.append(f"{sent} [{idx + 1}]({url})")
    return " ".join(out_parts), unsourced


def _tok(t: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", t.lower()))


def _best_match(sent: str, passage_tokens: list[set[str]], passages: list[Passage]):
    st = _tok(sent)
    if not st:
        return None, 0
    best_idx = None
    best = 0
    for i, pt in enumerate(passage_tokens):
        overlap = len(st & pt)
        if overlap > best:
            best = overlap
            best_idx = i
    return best_idx, best
