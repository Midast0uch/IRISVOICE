"""PROBE (offline, read-only): can d1 ground a CANDIDATE SET in an IMAGE?

Owner question (2026-10-08): d1 is the only vision model. Before building any
screen-grounding on it, prove it ranks image-grounded candidates — or report
that it does not. No production code is touched by this script.

WHAT IS MEASURED
    d1's native Decision Index API (``POST /v1/systemone``) driven with an IMAGE
    attached, using the same question shape the live backend sends
    (``decision_backend_d1._native_question``). No logprobs, no letters: the
    model answers with the option NAME it picked.

THE CONTROL CONDITION (this is what makes the probe a measurement)
    Every question is asked TWICE: once WITH the image and once WITHOUT it.
    If the no-image control scores the same, the model is answering from text
    priors and the image did nothing.

GROUND TRUTH
    * count test: n filled circles, n is known by construction;
    * permutation test: one word walks through known panels; the answer MUST
      walk with it. If it stays put, the image is being ignored.

USAGE
    python scripts/probe_d1_image_grounding.py
    python scripts/probe_d1_image_grounding.py --save-dir screenshots
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import os
import statistics
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

import httpx

PORT = 8082
BASE = f"http://127.0.0.1:{PORT}"

# Panel words (deliberately not A/B/C, so the model cannot match a word to a
# position by shape). COLOURS are deliberately far apart in hue.
WORDS = ["ZEPHYR", "QUARTZ", "NIMBUS", "FLINT", "OBSIDIAN", "CINDER"]
PANELS: List[Tuple[str, Tuple[int, int, int, int]]] = [
    ("top-left panel", (20, 20, 240, 120)),
    ("top-right panel", (508, 20, 240, 120)),
    ("bottom-center panel", (264, 300, 240, 120)),
]
CANVAS = (768, 440)
COLOURS = [(200, 40, 40), (30, 150, 60), (40, 70, 200)]


# ── image construction (ground truth by construction) ────────────────────────

def _font(size: int):
    from PIL import ImageFont
    for name in ("arialbd.ttf", "arial.ttf", "segoeuib.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            continue
    try:
        return ImageFont.load_default(size=size)
    except Exception:
        return ImageFont.load_default()


def build_image(placement: Optional[Dict[int, str]] = None,
                circles: int = 0) -> bytes:
    """One CANVAS: either ``circles`` filled circles, or one panel per
    position with ``placement`` mapping position index -> word."""
    from PIL import Image, ImageDraw

    img = Image.new("RGB", CANVAS, (245, 245, 245))
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, CANVAS[0] - 1, CANVAS[1] - 1], outline=(0, 0, 0),
                   width=3)
    if circles:
        w = 120
        x0 = (CANVAS[0] - (circles * w + (circles - 1) * 40)) // 2
        for i in range(circles):
            cx = x0 + i * (w + 40)
            cy = (CANVAS[1] - w) // 2
            draw.ellipse([cx, cy, cx + w, cy + w], fill=COLOURS[i % len(COLOURS)],
                         outline=(0, 0, 0), width=3)
    else:
        font = _font(28)
        for idx, (_, (x, y, w, h)) in enumerate(PANELS):
            word = (placement or {}).get(idx, WORDS[idx % len(WORDS)])
            draw.rectangle([x, y, x + w, y + h], fill=COLOURS[idx % len(COLOURS)],
                           outline=(0, 0, 0), width=2)
            tw = draw.textbbox((0, 0), word, font=font)
            draw.text((x + (w - (tw[2] - tw[0])) / 2 - tw[0],
                       y + (h - (tw[3] - tw[1])) / 2 - tw[1]),
                      word, fill=(255, 255, 255), font=font)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ── native transport ─────────────────────────────────────────────────────────

_client: Optional[httpx.Client] = None


def client() -> httpx.Client:
    global _client
    if _client is None:
        _client = httpx.Client(timeout=120.0)
    return _client


def server_has_vision() -> Tuple[bool, str]:
    try:
        r = client().get(f"{BASE}/props", timeout=10.0)
        r.raise_for_status()
        mods = (r.json() or {}).get("modalities") or {}
        return bool(mods.get("vision")), f"modalities={mods}"
    except Exception as e:  # noqa: BLE001
        return False, f"props failed: {e!r}"


def ask(instruction: str, criteria: Dict[str, str],
        image_png: Optional[bytes] = None) -> Dict[str, Any]:
    """One native question; ``image_png=None`` is the control (no image).

    Returns {"choice": name, "probs": {...}, "ms": int} or {"error": str}.
    """
    question = {"type": "choice", "instructions": instruction,
                "criteria": dict(criteria)}
    payload: Dict[str, Any] = {"state": "",
                               "questions": {"q0": question}}
    if image_png is not None:
        payload["images"] = [
            "data:image/png;base64," + base64.b64encode(image_png).decode("ascii")
        ]
    t0 = time.time()
    try:
        r = client().post(f"{BASE}/v1/systemone", json=payload)
    except Exception as e:  # noqa: BLE001
        return {"error": f"request failed: {e!r}", "ms": int((time.time() - t0) * 1000)}
    ms = int((time.time() - t0) * 1000)
    if r.status_code != 200:
        return {"error": f"HTTP {r.status_code}: {r.text[:300]}", "ms": ms}
    try:
        ans = (r.json() or {}).get("answers") or {}
    except Exception as e:  # noqa: BLE001
        return {"error": f"bad json: {e!r}", "ms": ms}
    a = ans.get("q0")
    if not isinstance(a, dict):
        return {"error": f"no answer for q0: {json.dumps(ans)[:300]}", "ms": ms}
    choice = a.get("choice")
    return {"choice": choice, "probs": a.get("probabilities") or {},
            "confidence": a.get("confidence"), "ms": ms}


# ── the probe ────────────────────────────────────────────────────────────────

COUNT_CRITERIA = {"one": "One circle", "two": "Two circles",
                  "three": "Three circles"}


def count_probe(save_dir: Optional[str], results: List[Dict[str, Any]]) -> None:
    """1/2/3 circles, named answers, WITH image vs WITHOUT (the control)."""
    print("\n=== COUNT test (native schema, image vs no-image control) ===")
    gold_by_n = {1: "one", 2: "two", 3: "three"}
    lat: List[int] = []
    hits = {"with": 0, "without": 0}
    for n in (1, 2, 3):
        img = build_image(circles=n)
        q = f"How many circles are in the image?"
        with_img = ask(q, COUNT_CRITERIA, img)
        no_img = ask(q, COUNT_CRITERIA, None)
        cw, cn = with_img.get("choice"), no_img.get("choice")
        hits["with"] += int(cw == gold_by_n[n])
        hits["without"] += int(cn == gold_by_n[n])
        if with_img.get("ms"):
            lat.append(int(with_img["ms"]))
        results.append({"shape": "count", "n": n, "gold": gold_by_n[n],
                        "with_image": cw, "no_image": cn,
                        "probs_with": with_img.get("probs"),
                        "error_with": with_img.get("error")})
        print(f"  {n} circle(s) gold={gold_by_n[n]:<6} "
              f"with_image={cw} no_image={cn}"
              + (f"  ERR={with_img['error']}" if with_img.get("error") else ""))
        if save_dir:
            os.makedirs(save_dir, exist_ok=True)
            with open(os.path.join(save_dir, f"d1-count-{n}.png"), "wb") as fh:
                fh.write(img)
    print(f"  correct WITH image:    {hits['with']}/3")
    print(f"  correct WITHOUT image: {hits['without']}/3  (control)")
    if lat:
        print(f"  latency with image: p50 {int(statistics.median(lat))} ms  "
              f"max {max(lat)} ms")
    results.append({"shape": "count_summary", **hits})


def permutation_probe(save_dir: Optional[str],
                      results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Question byte-identical, only the image moves: the answer must follow."""
    print("\n=== PERMUTATION test (question identical, only the image moves) ===")
    criteria = {name: name for name, _ in PANELS}
    probe_word = "ZEPHYR"
    moved: List[str] = []
    for pos in range(len(PANELS)):
        placement = {i: WORDS[(i + 2) % len(WORDS)] for i in range(len(PANELS))}
        placement[pos] = probe_word
        img = build_image(placement=placement)
        r = ask(f"Which panel shows the word {probe_word}?", criteria, img)
        got = r.get("choice") or "?"
        moved.append(got)
        print(f"  word at {PANELS[pos][0]:<18} (gold {PANELS[pos][0]}): "
              f"answered {got}"
              + (f"  ERR={r['error']}" if r.get("error") else ""))
        if save_dir and pos == 0:
            os.makedirs(save_dir, exist_ok=True)
            with open(os.path.join(save_dir, "d1-permutation.png"), "wb") as fh:
                fh.write(img)
    follows = all(moved[p] == PANELS[p][0] for p in range(len(moved)))
    distinct = len(set(moved))
    print(f"  answers as the word moves: {moved}")
    print(f"  distinct answers: {distinct}/{len(moved)}  "
          f"(1 = the image is ignored; {len(moved)} = it is read)")
    print(f"  answer follows the image: {follows}")
    out = {"shape": "permutation", "word": probe_word,
           "answers_as_word_moves": moved, "follows": follows,
           "distinct": distinct}
    results.append(out)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="d1 image-grounding probe")
    ap.add_argument("--trials", type=int, default=3,
                    help="unused; kept so old invocations do not break")
    ap.add_argument("--save-dir", default="")
    a = ap.parse_args()

    ok, why = server_has_vision()
    print(f"server vision: {ok}  ({why})")
    if not ok:
        print("BLOCKED: the shared server does not report vision.")
        return 2

    save_dir = a.save_dir or None
    results: List[Dict[str, Any]] = []
    count_probe(save_dir, results)
    perm = permutation_probe(save_dir, results)

    summary = next(r for r in results if r.get("shape") == "count_summary")
    if perm["follows"]:
        verdict = ("GROUNDS: the answer tracks the image when only the image "
                   "changes (permutation test passed).")
    elif perm["distinct"] == 1:
        verdict = ("DOES NOT GROUND: the answer is INVARIANT to the image - "
                   "one answer for every placement.")
    elif summary["with"] > summary["without"]:
        verdict = ("GROUNDS: the image beats the no-image control.")
    else:
        verdict = "DOES NOT GROUND: the image does not beat the no-image control."
    print(f"\nVERDICT: {verdict}")
    with open("benchmarks/d1_image_grounding_probe.json", "w",
              encoding="utf-8") as fh:
        json.dump({"count": summary, "permutation": perm, "results": results,
                   "verdict": verdict}, fh, indent=2)
    print("wrote benchmarks/d1_image_grounding_probe.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
