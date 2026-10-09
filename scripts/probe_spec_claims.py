"""PROBE (read-only, offline): three load-bearing claims of
specs/oracle-native-decision-surface, verified before Wave 0.

  P1  STABILITY   - does d1 give the same answer for the SAME question?
                    Published decision-model work measured 3.25% and 11.14%
                    run-to-run reversal on identical inputs. If d1 is unstable
                    here, confidence does not rank anything and the whole
                    banded-accuracy approach collapses.
  P2  LABEL JOIN  - would joining Oracle rows to real tool OUTCOMES produce
                    usable labels? Both classes must appear, or the bar is
                    unreachable no matter how many rows arrive.
  P3  REAL SCREEN - does d1 ground an actual screenshot over an indexed
                    candidate list? The earlier probe used 1/2/3 coloured
                    circles, which is trivially easy. Ground truth here is
                    COMPUTED from the pixels, so no human labels it.

Nothing is written to the store. Usage:
    python scripts/probe_spec_claims.py
"""

from __future__ import annotations

import base64
import io
import math
import statistics
import sys
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, ".")

import httpx

PORT = 8082
BASE = f"http://127.0.0.1:{PORT}"
N_PROBS = 512

_client: Optional[httpx.Client] = None


def client() -> httpx.Client:
    global _client
    if _client is None:
        _client = httpx.Client(timeout=120.0)
    return _client


def name_ids(keys: Sequence[str]) -> Dict[str, List[int]]:
    """Single-token ids for criterion NAMES, from the server's tokenizer."""
    out: Dict[str, List[int]] = {}
    for key in keys:
        for form in (key, f" {key}"):
            try:
                r = client().post(f"{BASE}/tokenize",
                                  json={"content": form, "add_special": False},
                                  timeout=10.0)
                toks = (r.json() or {}).get("tokens") or []
                ids = [t["id"] if isinstance(t, dict) else int(t) for t in toks]
                if len(ids) == 1:
                    out.setdefault(key, []).append(ids[0])
            except Exception:
                continue
    return out


def ask(image_png: Optional[bytes], text: str,
        readout: Dict[str, List[int]]) -> Optional[Dict[str, Any]]:
    """One forward pass. Max-pool per NAME token, then softmax."""
    content: List[Dict[str, Any]] = []
    if image_png is not None:
        content.append({"type": "image_url", "image_url": {
            "url": "data:image/png;base64," + base64.b64encode(image_png).decode()}})
    content.append({"type": "text", "text": text})
    try:
        r = client().post(f"{BASE}/v1/chat/completions", json={
            "messages": [{"role": "user", "content": content}],
            "max_tokens": 1, "temperature": 0.0, "n_probs": N_PROBS})
    except Exception as e:  # noqa: BLE001
        return {"error": repr(e)}
    if r.status_code != 200:
        return {"error": f"HTTP {r.status_code}: {r.text[:200]}"}
    ch = (r.json().get("choices") or [{}])[0]
    logz: Dict[int, float] = {}
    for comp in (ch.get("completion_probabilities") or []):
        for e in (comp.get("top_logprobs") or []):
            if e.get("id") is not None and e.get("logprob") is not None:
                logz[int(e["id"])] = float(e["logprob"])
    if not logz:
        for tok in (((ch.get("logprobs") or {}).get("content")) or []):
            for e in (tok.get("top_logprobs") or []):
                tid = e.get("id")          # `id` is the token id; bytes[0] is NOT
                if tid is not None and e.get("logprob") is not None:
                    logz[int(tid)] = float(e["logprob"])
    if not logz:
        return {"error": "no logprobs"}
    scores = []
    for k in readout:
        vals = [logz[t] for t in readout[k] if t in logz]
        scores.append(max(vals) if vals else float("-inf"))
    if all(s == float("-inf") for s in scores):
        return {"error": f"no readout token in top logprobs; top={sorted(logz.items(), key=lambda kv: -kv[1])[:5]}"}
    m = max(scores)
    ex = [math.exp(s - m) if s > float("-inf") else 0.0 for s in scores]
    tot = sum(ex) or 1.0
    probs = {k: e / tot for k, e in zip(readout, ex)}
    return {"choice": max(probs, key=probs.get), "probs": probs}


# ── P1: stability ────────────────────────────────────────────────────────────

def p1_stability(repeats: int = 5) -> int:
    print("\n" + "=" * 72)
    print("P1  STABILITY: identical question, repeated. Does the answer hold?")
    print("=" * 72)
    from backend.agent.decision_engine import get_consumer_spec
    probes: List[Tuple[str, str, Dict[str, str]]] = []
    for cid in ("tool_choice", "review_verdict", "done", "click_safety"):
        spec = None
        try:
            spec = get_consumer_spec(cid)
        except Exception:
            spec = None
        instr = getattr(spec, "instruction", None) or f"Is this a good {cid} decision?"
        if cid == "done":
            crit = {"yes": "The task is finished",
                    "no": "The task still needs work"}
        elif cid == "click_safety":
            crit = {"yes": "Safe to take without asking",
                    "no": "Needs the user to approve first"}
        elif cid == "review_verdict":
            crit = {"pass": "The step did its part",
                    "refine": "The step is vague or incomplete",
                    "veto": "The step must not run"}
        else:
            crit = {"yes": "Proceed with this tool",
                    "no": "Prefer a different action"}
        probes.append((cid, instr, crit))

    flips = 0
    trials = 0
    for cid, instr, crit in probes:
        names = list(crit)
        rid = name_ids(names)
        if not rid:
            print(f"  [{cid:<14}] SKIP - no single-token criteria names")
            continue
        text = (f"{instr}\n\nOptions:\n"
                + "\n".join(f"{k}: {v}" for k, v in crit.items())
                + "\n\nReply with the option name only.")
        got, probs = [], []
        for _ in range(repeats):
            r = ask(None, text, rid)
            got.append((r or {}).get("choice"))
            probs.append((r or {}).get("probs") or {})
        uniq = sorted({g for g in got if g})
        trials += 1
        spread = 0.0
        for k in names:
            vals = [p[k] for p in probs if k in p]
            if len(vals) > 1:
                spread = max(spread, max(vals) - min(vals))
        bad = len(uniq) > 1
        flips += int(bad)
        print(f"  [{cid:<14}] answers={got}  distinct={len(uniq)}  "
              f"max_prob_spread={spread:.4f}  {'UNSTABLE' if bad else 'stable'}")
    if trials:
        print(f"\n  reversal rate: {flips}/{trials} consumers changed their answer "
              f"across {repeats} identical calls")
        print("  VERDICT: " + ("STABLE at temperature 0." if flips == 0 else
                               "UNSTABLE - confidence does not rank anything. STOP."))
    return 0


# ── P2: label join ───────────────────────────────────────────────────────────

def p2_label_join() -> int:
    print("\n" + "=" * 72)
    print("P2  LABEL JOIN: would real tool OUTCOMES label the Oracle rows?")
    print("=" * 72)
    import sqlite3
    from scripts._app_store import app_store_path
    path = app_store_path()
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            "SELECT rowid, outcome, interaction_payload FROM system_events "
            "WHERE actor = 'agent_tool_bridge' ORDER BY rowid DESC LIMIT 4000"
        ).fetchall()
    except Exception as e:  # noqa: BLE001
        print(f"  could not read the store: {e!r}")
        return 2
    finally:
        con.close()

    import json
    from backend.agent.decision_engine import job_input  # noqa: F401

    have_outcome = {"incumbent_only": 0, "dispatched": 0, "no_payload": 0}
    consumers: Dict[str, int] = {}
    for r in rows:
        try:
            payload = json.loads(r["interaction_payload"] or "{}")
        except Exception:
            have_outcome["no_payload"] += 1
            continue
        dec = payload.get("decision") or {}
        if not dec:
            have_outcome["no_payload"] += 1
            continue
        cid = str(dec.get("consumer_id") or "")
        consumers[cid] = consumers.get(cid, 0) + 1
        if r["outcome"] in ("shadow", "no_tool"):
            have_outcome["incumbent_only"] += 1
        else:
            have_outcome["dispatched"] += 1

    print(f"  rows scanned: {len(rows)}")
    print(f"  breakdown: {have_outcome}")
    print(f"  consumers present: {sorted(consumers)}")
    print()
    print("  KEY QUESTION - for each consumer, can an OUTCOME label be joined?")
    print("  A consumer is JOINABLE if some of its rows are DISPATCHED (a real")
    print("  action ran and its result exists). Only dispatched rows carry truth;")
    print("  shadow rows carry the incumbent's answer.")
    for cid in ("tool_choice", "review_verdict", "depth_route", "narration"):
        n = consumers.get(cid, 0)
        print(f"    {cid:<16} rows={n:<5} joinable: "
              f"{'YES' if n else 'NO ROWS AT ALL'}")
    tot_d = have_outcome["dispatched"]
    print()
    print(f"  dispatched (outcome-bearing) rows in the scan: {tot_d}")
    print("  VERDICT: " + (
        "JOINABLE - dispatched rows exist, so true labels are obtainable." if tot_d
        else "NOT JOINABLE - no dispatched rows in the scan; the join has no truth source."))
    return 0


# ── P3: real screen ──────────────────────────────────────────────────────────

def _shot(width: int = 768) -> bytes:
    import mss
    from PIL import Image
    with mss.mss() as sct:
        raw = sct.grab(sct.monitors[1])
        img = Image.frombytes("RGB", (raw.width, raw.height), raw.rgb)
    if img.width > width:
        img = img.resize((width, int(img.height * width / img.width)))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue(), img


def p3_real_screen() -> int:
    print("\n" + "=" * 72)
    print("P3  REAL SCREEN: an actual screenshot over an indexed candidate list.")
    print("Ground truth is COMPUTED from the pixels, so nothing is hand-labelled.")
    print("=" * 72)
    try:
        png, img = _shot()
    except Exception as e:  # noqa: BLE001
        print(f"  no screen capture available: {e!r}")
        return 2
    from PIL import ImageStat
    W, H = img.size
    COLS, ROWS = 3, 2          # 6 cells: matches candidate_cap = 6
    cells = []
    for r in range(ROWS):
        for c in range(COLS):
            box = (c * W // COLS, r * H // ROWS,
                   (c + 1) * W // COLS, (r + 1) * H // ROWS)
            cell = img.crop(box).convert("L")
            stat = ImageStat.Stat(cell)
            cells.append({"name": chr(ord("A") + r * COLS + c),
                          "box": box, "stddev": stat.stddev[0],
                          "mean": stat.mean[0]})
    print(f"  screen {W}x{H}, {COLS}x{ROWS} = {len(cells)} cells (candidate_cap=6)")
    for c in cells:
        print(f"    {c['name']}  detail(stddev)={c['stddev']:6.2f}  mean={c['mean']:6.2f}")

    questions = [
        ("Which region of the screen has the MOST detail?",
         max(cells, key=lambda c: c["stddev"])["name"]),
        ("Which region of the screen is the DARKEST?",
         min(cells, key=lambda c: c["mean"])["name"]),
        ("Which region of the screen is the BRIGHTEST?",
         max(cells, key=lambda c: c["mean"])["name"]),
    ]
    names = [c["name"] for c in cells]
    rid = name_ids(names)
    if not rid:
        print("  SKIP - cell letters are not single-token")
        return 2
    desc = {"A": "top-left", "B": "top-centre", "C": "top-right",
            "D": "bottom-left", "E": "bottom-centre", "F": "bottom-right"}
    crit = "\n".join(f"{n}: the {desc[n]} region" for n in names)

    hit = 0
    for q, gold in questions:
        text = f"{q}\n\nOptions:\n{crit}\n\nReply with the option name only."
        r = ask(png, text, rid)
        got = (r or {}).get("choice")
        ok = got == gold
        hit += int(ok)
        conf = (r or {}).get("probs", {}).get(got or "", 0.0)
        print(f"  {q[:44]:<44} gold={gold} got={got} "
              f"conf={conf:.2f} {'OK' if ok else 'MISS'}")
    print(f"\n  real-screen grounding: {hit}/{len(questions)}")
    print("  VERDICT: " + (
        "GROUNDS on a real screen." if hit >= 2 else
        "DOES NOT GROUND on a real screen (the synthetic circles were too easy)."))
    return 0


def main() -> int:
    for p in (p1_stability, p2_label_join, p3_real_screen):
        try:
            p()
        except Exception as e:  # noqa: BLE001
            print(f"  {p.__name__} FAILED: {e!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())