#!/usr/bin/env python3
"""Replay page_relevance on recorded research pages (offline, read-only).

Asks d1 the LIVE page_relevance question (backend/agent/page_shadow.py) on
pages IRIS already fetched in recorded research turns, and scores each answer
against the SAME outside label the live rows get:

  label True  = the turn PASSED and the extraction cited the page;
  label False = the turn PASSED, the extraction cited >= 1 page, not this one;
  no label    = the turn failed, has no verdict, the result held one page (the
                binding cites the only page by construction), or the
                extraction cited nothing.

DATA (all read-only; nothing is written to the store):
  * the app store's document_data ``fmt='json'`` tool results: the query and the
    combined page content the crawler returned (``--- Source: <url> ---`` + the
    page's markdown, capped at 12000 chars per result) - the page head is the
    same PageData.markdown the live frame reads;
  * the app store's research records (``fmt='research'``): the extraction's
    cited claim urls, joined by (conversation_id, query);
  * evals/results/*.json: the turn verdict, joined by (conversation_id, task id
    from the record's ``eval-<task>-<hash>`` session id); ambiguous joins skip.
DIFFERENCES FROM A LIVE ROW: the recorded block has no page title (the frame's
title is absent); a page cut by the 12000-char cap has a shorter head; the
record's claim urls also hold dashboard CARD urls, which the live label (summary
and key-finding citations only) does not count.

Cost: one d1 consult per distinct labelled page, sequential, capped by --max
(default 300). Needs d1 on :8082. Exit 0 always: a replay is a measurement.

Usage:
  python scripts/replay_page_relevance.py --dry-run     # cohort + labels only
  python scripts/replay_page_relevance.py [--max 300] [--out rows.jsonl]
"""
from __future__ import annotations

import argparse
import glob
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
for _p in (_REPO, _REPO / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from _app_store import app_store_path  # noqa: E402
from backend.agent.page_shadow import cited_urls  # noqa: E402
from backend.memory.db import open_store_read_only  # noqa: E402

_SRC = re.compile(r"--- Source: (\S+) ---\n")
_TASK = re.compile(r"^eval-(.+)-[0-9a-f]{6}$")


def _blocks(content: str):
    """(url, page markdown) per Source block of a combined tool result."""
    parts = _SRC.split(content or "")
    for i in range(1, len(parts) - 1, 2):
        text = parts[i + 1].replace("[...truncated...]", "").strip()
        yield parts[i], text


def _verdicts(results_glob: str) -> dict:
    """(conversation_id, task id) -> [passed, ...] over every recorded run."""
    out: dict = defaultdict(list)
    for path in glob.glob(results_glob):
        try:
            data = json.load(open(path, encoding="utf-8"))
        except Exception:  # noqa: BLE001 - a partial results file is skipped
            continue
        for r in data.get("results") or []:
            if r.get("conversation_id") and r.get("id"):
                out[(r["conversation_id"], r["id"])].append(bool(r.get("passed")))
    return out


def load_cohort(store: str, results_glob: str) -> tuple:
    """Distinct (query, url, head) inputs with their label, plus join counters."""
    c = open_store_read_only(store)
    records: dict = defaultdict(list)
    for (content,) in c.execute("SELECT content FROM document_data WHERE fmt='research'"):
        try:
            d = json.loads(content)
        except Exception:  # noqa: BLE001
            continue
        if not (d.get("summary") or d.get("dashboard")):
            continue  # a quick-tier record: its "claims" are snippets, no extraction
        records[(d.get("conversation_id") or "", d.get("query") or "")].append(d)
    verdicts = _verdicts(results_glob)
    counts = defaultdict(int)
    cohort: dict = {}
    for conv, content in c.execute(
            "SELECT conversation_id, content FROM document_data WHERE fmt='json' "
            "AND content LIKE '%--- Source: http%'"):
        try:
            doc = json.loads(content)
        except Exception:  # noqa: BLE001
            continue
        query = str(doc.get("query") or "") if isinstance(doc, dict) else ""
        if not query:
            continue
        counts["tool_results"] += 1
        recs = records.get((conv or "", query))
        if not recs:
            counts["no_extraction_record"] += 1
            continue
        # the summary's citations ride the claims; the key findings' citations
        # ride the stored dashboard (claims_from_dashboard strips them)
        cited = {u for r in recs for cl in r.get("claims") or [] for u in cl.get("urls") or []}
        cited |= {u for r in recs for u in cited_urls(r.get("dashboard"))}
        m = _TASK.match(str(recs[0].get("session_id") or ""))
        runs = verdicts.get((conv, m.group(1))) if m else None
        if not runs or len(set(runs)) != 1:
            counts["no_or_ambiguous_verdict"] += 1
            passed = None
        else:
            passed = runs[0]
        blocks = [(u, t) for u, t in _blocks(doc.get("content") or "") if t]
        for url, text in blocks:
            counts["pages"] += 1
            if passed is None:
                continue
            if not passed:
                counts["pages_turn_failed"] += 1
                continue
            if len({u for u, _ in blocks}) < 2:
                # the live rule (page_shadow._MIN_JOB_PAGES): the only page of
                # a job is cited by construction, so it carries no label
                counts["pages_single_page_job"] += 1
                continue
            if not cited:
                counts["pages_extraction_cited_nothing"] += 1
                continue
            key = (query, url, " ".join(text.split())[:800])
            cohort[key] = url in cited
    return cohort, dict(counts)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true", help="cohort and labels only")
    ap.add_argument("--max", type=int, default=300, help="consult cap (default 300)")
    ap.add_argument("--results", default=str(_REPO / "evals" / "results" / "2026*.json"))
    ap.add_argument("--out", help="write the scored rows as JSONL here")
    args = ap.parse_args()

    store = app_store_path()
    cohort, counts = load_cohort(store, args.results)
    pos = sum(cohort.values())
    print(f"store: {store}")
    print(f"joins: {counts}")
    print(f"distinct labelled inputs: {len(cohort)} (cited {pos}, not cited {len(cohort) - pos})")
    if args.dry_run or not cohort:
        return 0

    import backend.agent.decision_engine as de
    from backend.agent import page_shadow as ps
    from fit_oracle_calibration import fit_consumer

    eng = de.get_decision_engine()
    ps._register(ps.PAGE_RELEVANCE, ps.RELEVANCE_INSTRUCTION)
    rows, none = [], 0
    for (query, url, head), label in list(cohort.items())[: args.max]:
        frame = ps.relevance_frame(query, "", url, head)
        n = eng.noul(ps.PAGE_RELEVANCE, ps.RELEVANCE_INSTRUCTION, frame,
                     true_label="yes", false_label="no")
        if n is None:
            none += 1
            continue
        said = n.probability >= 0.5
        rows.append({"url": url, "query": query, "label": label, "chosen": said,
                     "probability": round(n.probability, 4),
                     "confidence": round(max(n.probability, 1 - n.probability), 4),
                     "correct": said == label, "repeats": 1})
    print(f"engine: {getattr(eng, 'model_id', '?')}  scored: {len(rows)}  no answer: {none}")
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    if not rows:
        return 0
    right = sum(r["correct"] for r in rows)
    said_yes = sum(r["chosen"] for r in rows)
    print(f"accuracy at 0.5: {right}/{len(rows)} = {right / len(rows):.3f}; "
          f"said yes {said_yes}/{len(rows)}; majority-class rule "
          f"{max(pos, len(cohort) - pos)}/{len(cohort)}")
    for acting in (None, "no"):
        entry = fit_consumer(rows, acting=acting)
        o = entry["oof"]
        print(f"fit (acting={acting}): rows={entry['rows_distinct']} classes={entry['classes']} "
              f"OOF auroc={o['auroc']} ece={o['ece']} t={entry['threshold']} "
              f"above={entry['rows_above']} prec={o['precision_at_t']} wilson={o['wilson_lb']} "
              f"acting_prec={o.get('acting_precision')} baseline={entry.get('baseline')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
