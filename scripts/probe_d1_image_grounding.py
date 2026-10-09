"""PROBE (offline, read-only): can d1-3B ground a CANDIDATE SET in an IMAGE?

Owner question (2026-10-08): d1 is the only vision model. Before building any
screen-grounding on it, prove it ranks image-grounded candidates — or report
that it does not. No production code is touched by this script.

WHAT IS MEASURED
    d1's native shapes (noul / choice / score) driven with an IMAGE attached,
    using the SAME prompt template and the SAME readout the live backend uses
    (``decision_backend_d1``): max-pool per option letter over one completion
    token's logprobs, then softmax.

THE CONTROL CONDITION (this is what makes the probe a measurement)
    Every question is asked TWICE: once WITH the image and once WITHOUT it.
    If the no-image control scores the same, the model is answering from text
    priors and the image did nothing. A probe without this control proves
    nothing.

GROUND TRUTH
    Synthetic panels with a visible word at a KNOWN position. The correct
    option letter is known by construction, so no human labels the data.

USAGE
    python scripts/probe_d1_image_grounding.py
    python scripts/probe_d1_image_grounding.py --trials 8 --save-dir screenshots
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import math
import statistics
import sys
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

import httpx

PORT = 8082
BASE = f"http://127.0.0.1:{PORT}"
N_PROBS = 512

# Panel words (deliberately not A/B/C, so the model cannot match a word to a
# letter by shape). COLOURS are deliberately far apart in hue.
WORDS = ["ZEPHYR", "QUARTZ", "NIMBUS", "FLINT", "OBSIDIAN", "CINDER"]

# Three candidate positions. The option CODE is the index (A, B, C).
POSITIONS: List[Tuple[str, Tuple[int, int, int, int]]] = [
    ("the top-left panel", (20, 20, 240, 120)),
    ("the top-right panel", (508, 20, 240, 120)),
    ("the bottom-center panel", (264, 300, 240, 120)),
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


def build_image(placement: Dict[int, str]) -> bytes:
    """Render one panel per position. placement maps position index -> word."""
    from PIL import Image, ImageDraw

    img = Image.new("RGB", CANVAS, (245, 245, 245))
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, CANVAS[0] - 1, CANVAS[1] - 1], outline=(0, 0, 0), width=3)
    font = _font(28)
    for idx, (_, (x, y, w, h)) in enumerate(POSITIONS):
        word = placement[idx]
        draw.rectangle([x, y, x + w, y + h], fill=COLOURS[idx % len(COLOURS)],
                       outline=(0, 0, 0), width=2)
        tw = draw.textbbox((0, 0), word, font=font)
        draw.text((x + (w - (tw[2] - tw[0])) / 2 - tw[0],
                   y + (h - (tw[3] - tw[1])) / 2 - tw[1]),
                  word, fill=(255, 255, 255), font=font)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ── server plumbing ──────────────────────────────────────────────────────────

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


def letter_ids(keys: Sequence[str]) -> Dict[str, List[int]]:
    """Single-token ids for the option letters, from the server's tokenizer —
    the SAME readout vocabulary decision_backend_d1._ensure_letter_ids uses."""
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


def yes_no_ids() -> Dict[str, List[int]]:
    from backend.agent.decision_backend_d1 import _NO_FORMS, _YES_FORMS
    out: Dict[str, List[int]] = {}
    for key, forms in (("yes", _YES_FORMS), ("no", _NO_FORMS)):
        for form in forms:
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


def score(image_png: Optional[bytes], question: str,
          readout: Dict[str, List[int]]) -> Optional[Dict[str, Any]]:
    """One completion token WITH image; max-pool per option group; softmax.

    ``image_png=None`` is the control: the identical question, no image.

    The prompt is built by ``decision_backend_d1``'s OWN renderers, so the
    probe measures the calibrated shape the backend actually serves — not a
    prompt invented here.
    """
    from backend.agent.decision_backend_d1 import D1Backend as _B

    content: List[Dict[str, Any]] = []
    if image_png is not None:
        b64 = base64.b64encode(image_png).decode("ascii")
        content.append({"type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{b64}"}})
    # _state_block renders a plain string as itself, exactly as the backend does.
    content.append({"type": "text", "text": _B._state_block(question)})

    t0 = time.time()
    try:
        r = client().post(f"{BASE}/v1/chat/completions", json={
            "messages": [{"role": "user", "content": content}],
            "max_tokens": 1,
            "temperature": 0.0,
            "n_probs": N_PROBS,
        })
    except Exception as e:  # noqa: BLE001
        return {"error": f"request failed: {e!r}", "ms": int((time.time() - t0) * 1000)}
    ms = int((time.time() - t0) * 1000)
    if r.status_code != 200:
        return {"error": f"HTTP {r.status_code}: {r.text[:400]}", "ms": ms}

    try:
        data = r.json()
    except Exception as e:  # noqa: BLE001
        return {"error": f"bad json: {e!r}", "ms": ms}

    choice = ((data.get("choices") or [{}])[0])
    # ROUTE PROOF: the image is in the prompt iff prompt_tokens grows. Without
    # this, "with image" and "no image" are the SAME request and the whole
    # comparison is void (the confound that made the first run unreadable).
    n_prompt = int((data.get("usage") or {}).get("prompt_tokens") or 0)
    # Two shapes: llama.cpp's completion_probabilities, or OpenAI logprobs.
    logz: Dict[int, float] = {}
    for comp in (choice.get("completion_probabilities") or []):
        for e in (comp.get("top_logprobs") or comp.get("top_probs") or []):
            if e.get("id") is not None and e.get("logprob") is not None:
                logz[int(e["id"])] = float(e["logprob"])
    if not logz:
        for tok in (((choice.get("logprobs") or {}).get("content")) or []):
            for e in (tok.get("top_logprobs") or []):
                # `id` is the TOKEN id. `bytes` is the utf-8 byte list, so
                # reading bytes[0] yields a CHARACTER CODE (e.g. 116 == "t"),
                # which silently mismatches every readout. Prefer `id`.
                tid = e.get("id")
                if tid is None:
                    b = e.get("bytes")
                    tid = b[0] if isinstance(b, list) and b else None
                if tid is not None and e.get("logprob") is not None:
                    logz[int(tid)] = float(e["logprob"])
    if not logz:
        return {"error": f"no logprobs in response: {json.dumps(choice)[:400]}",
                "ms": ms, "prompt_tokens": n_prompt}

    scores = []
    for key in readout:
        vals = [logz[t] for t in readout[key] if t in logz]
        scores.append(max(vals) if vals else float("-inf"))
    if all(s == float("-inf") for s in scores):
        top = sorted(logz.items(), key=lambda kv: -kv[1])[:8]
        return {"error": f"none of {list(readout)} in top logprobs; "
                         f"top ids={top}", "ms": ms, "prompt_tokens": n_prompt}
    m = max(scores)
    exps = [math.exp(s - m) if s > float("-inf") else 0.0 for s in scores]
    tot = sum(exps) or 1.0
    probs = {k: e / tot for k, e in zip(readout, exps)}
    best = max(probs, key=probs.get)
    return {"choice": best, "probs": probs, "ms": ms,
            "prompt_tokens": n_prompt,
            "text": (choice.get("message") or {}).get("content")}


# ── the probe ────────────────────────────────────────────────────────────────

# ── NATIVE Decision Index schema (LiquidAI d1-3B model card, Oct 2026) ──────
# The published API is system_one(state, questions, images=None):
#   * images are a SEPARATE argument, not part of the text;
#   * "A state is a string, any JSON value, or None when the images are the
#     whole state";
#   * `criteria` is a DICT {name: description} - the answer is the NAME, and
#     d1 is trained on named options, NOT on A/B/C letters.
# Our backend flattens names to letters for /completion. That letter scheme is
# off-distribution for the vision path, so this probe uses the NATIVE schema.
NATIVE_CRITERIA = {"one": "One", "two": "Two", "more": "Three or more"}


def build_shapes_image(n: int) -> bytes:
    """n distinct filled circles. The count is ground truth by construction."""
    from PIL import Image, ImageDraw

    img = Image.new("RGB", CANVAS, (250, 250, 250))
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, CANVAS[0] - 1, CANVAS[1] - 1], outline=(0, 0, 0), width=3)
    cols = [(200, 40, 40), (30, 150, 60), (40, 70, 200)]
    w = 120
    x0 = (CANVAS[0] - (n * w + (n - 1) * 40)) // 2
    for i in range(n):
        cx = x0 + i * (w + 40)
        cy = (CANVAS[1] - w) // 2
        draw.ellipse([cx, cy, cx + w, cy + w], fill=cols[i % len(cols)],
                     outline=(0, 0, 0), width=3)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def native_probe(save_dir: Optional[str]) -> int:
    """LiquidAI's own schema, verbatim. Counts 1/2/3 against named criteria.

    Two content orders are tested because the model card is inconsistent about
    them (the transformers example puts the image first, the vLLM example puts
    the text first). Both are one request each, so the cost is trivial.
    """
    ok, why = server_has_vision()
    print(f"server vision: {ok}  ({why})")
    if not ok:
        print("BLOCKED: no vision on the server.")
        return 2

    names = list(NATIVE_CRITERIA)
    nids = letter_ids(names)
    print(f"criteria name token ids: {nids}")
    if not nids:
        print("BLOCKED: no single-token criteria names.")
        return 2

    instruction = "How many circles are there?"
    crit_lines = "\n".join(f"{k}: {v}" for k, v in NATIVE_CRITERIA.items())
    text = (f"{instruction}\n\nOptions:\n{crit_lines}\n\n"
            "Reply with the option name only.")
    gold_by_n = {1: "one", 2: "two", 3: "more"}

    if save_dir:
        import os
        os.makedirs(save_dir, exist_ok=True)
        for n in (1, 2, 3):
            with open(os.path.join(save_dir, f"d1-native-{n}.png"), "wb") as fh:
                fh.write(build_shapes_image(n))

    hits = {"image_first": 0, "text_first": 0}
    print("\n=== NATIVE Decision Index schema (state=None, images=[img]) ===")
    for n in (1, 2, 3):
        img = build_shapes_image(n)
        gold = gold_by_n[n]
        row = []
        for order in ("image_first", "text_first"):
            content: List[Dict[str, Any]] = []
            ipart = {"type": "image_url", "image_url": {
                "url": "data:image/png;base64," +
                       base64.b64encode(img).decode("ascii")}}
            tpart = {"type": "text", "text": text}
            content = [ipart, tpart] if order == "image_first" else [tpart, ipart]
            try:
                r = client().post(f"{BASE}/v1/chat/completions", json={
                    "messages": [{"role": "user", "content": content}],
                    "max_tokens": 1, "temperature": 0.0, "n_probs": N_PROBS,
                })
                d = r.json()
                ch = (d.get("choices") or [{}])[0]
                logz: Dict[int, float] = {}
                for comp in (ch.get("completion_probabilities") or []):
                    for e in (comp.get("top_logprobs") or []):
                        if e.get("id") is not None and e.get("logprob") is not None:
                            logz[int(e["id"])] = float(e["logprob"])
                if not logz:
                    # OpenAI-shaped logprobs. `id` is the token id; `bytes` is
                    # the utf-8 byte list and must NOT be used as the id.
                    for tok in (((ch.get("logprobs") or {}).get("content")) or []):
                        for e in (tok.get("top_logprobs") or []):
                            tid = e.get("id")
                            if tid is None:
                                bb = e.get("bytes")
                                tid = bb[0] if isinstance(bb, list) and bb else None
                            if tid is not None and e.get("logprob") is not None:
                                logz[int(tid)] = float(e["logprob"])
                if not logz:
                    row.append(f"{order}=ERR(no logprobs)")
                    continue
                sc = []
                for k in names:
                    v = [logz[t] for t in nids[k] if t in logz]
                    sc.append(max(v) if v else float("-inf"))
                if all(s == float("-inf") for s in sc):
                    top = sorted(logz.items(), key=lambda kv: -kv[1])[:5]
                    row.append(f"{order}=ERR(none in top {top})")
                    continue
                m = max(sc)
                ex = [math.exp(s - m) if s > float("-inf") else 0.0 for s in sc]
                tot = sum(ex) or 1.0
                pr = {k: e / tot for k, e in zip(names, ex)}
                got = max(pr, key=pr.get)
                hits[order] += int(got == gold)
                row.append(f"{order}={got}({pr[got]:.2f})")
            except Exception as e:  # noqa: BLE001
                row.append(f"{order}=ERR({e!r})")
        print(f"  {n} circle(s), gold={gold:<5} " + "  ".join(row))

    print(f"\n  native-schema correct, image first: {hits['image_first']}/3")
    print(f"  native-schema correct, text first:  {hits['text_first']}/3")
    print("  (LiquidAI reference: same questions with images removed score ~45.1 "
          "vs 74.1 with them)")
    best = max(hits["image_first"], hits["text_first"])
    verdict = ("NATIVE SCHEMA GROUNDS: d1 reads the image through LiquidAI's "
               "published schema.") if best >= 2 else (
               "NATIVE SCHEMA ALSO FAILS: d1 does not ground the image through "
               "llama.cpp even with LiquidAI's own schema.")
    print(f"\nVERDICT: {verdict}")
    with open("benchmarks/d1_native_schema_probe.json", "w", encoding="utf-8") as fh:
        json.dump({"hits": hits, "verdict": verdict}, fh, indent=2)
    print("wrote benchmarks/d1_native_schema_probe.json")
    return 0


def run(trials: int, save_dir: Optional[str]) -> int:
    sys.path.insert(0, ".")
    ok, why = server_has_vision()
    print(f"server vision: {ok}  ({why})")
    if not ok:
        print("BLOCKED: the shared server does not report vision. Nothing to probe.")
        return 2

    letters = [chr(ord("A") + i) for i in range(len(POSITIONS))]
    lids = letter_ids(letters)
    yn = yes_no_ids()
    print(f"letter token ids: {lids}")
    print(f"yes/no token ids: {yn}")
    if not lids:
        print("BLOCKED: no single-token option letters from the tokenizer.")
        return 2

    def options_text() -> str:
        return "\n".join(f"{letters[i]} {name}"
                         for i, (name, _) in enumerate(POSITIONS))

    results: List[Dict[str, Any]] = []

    # ── CHOICE shape: "which panel shows WORD?" — answers spread over A/B/C ──
    print("\n=== CHOICE shape (image vs no-image control) ===")
    hit_i = hit_c = 0
    lat: List[int] = []
    for t in range(trials):
        word = WORDS[t % len(WORDS)]
        target = t % len(POSITIONS)          # vary WHICH panel holds the word
        placement = {i: WORDS[(t + i) % len(WORDS)] for i in range(len(POSITIONS))}
        placement[target] = word
        gold = letters[target]
        img = build_image(placement)
        if save_dir and t == 0:
            import os
            os.makedirs(save_dir, exist_ok=True)
            with open(os.path.join(save_dir, "d1-probe-grounding.png"), "wb") as fh:
                fh.write(img)

        q = (f"QUESTION:\nWhich panel shows the word {word}?\n\n"
             f"Options:\n{options_text()}\n\nReply with the option code only.")
        with_img = score(img, q, lids)
        no_img = score(None, q, lids)
        ci = (with_img or {}).get("choice")
        cc = (no_img or {}).get("choice")
        hit_i += int(ci == gold)
        hit_c += int(cc == gold)
        if (with_img or {}).get("ms"):
            lat.append(int(with_img["ms"]))
        results.append({"shape": "choice", "word": word, "gold": gold,
                        "with_image": ci, "no_image": cc,
                        "probs_with": (with_img or {}).get("probs"),
                        "prompt_tokens_with": (with_img or {}).get("prompt_tokens"),
                        "prompt_tokens_without": (no_img or {}).get("prompt_tokens"),
                        "error_with": (with_img or {}).get("error")})
        print(f"  trial {t + 1}: word={word:<9} gold={gold} "
              f"with_image={ci} no_image={cc} "
              f"conf={(with_img or {}).get('probs', {}).get(ci or '', 0):.3f}"
              + (f"  ERR={(with_img or {}).get('error')}" if (with_img or {}).get("error") else ""))

    # ── NOUL shape: "does any panel show WORD?" — polarity must track ───────
    print("\n=== NOUL shape (image vs no-image control) ===")
    if yn.get("yes") and yn.get("no"):
        nhit_i = nhit_c = 0
        for t in range(min(trials, 6)):
            present = (t % 2 == 0)
            word = WORDS[t % len(WORDS)]
            placement = {i: WORDS[(i + 3) % len(WORDS)] for i in range(len(POSITIONS))}
            if present:
                placement[t % len(POSITIONS)] = word
            gold = "yes" if present else "no"
            img = build_image(placement)
            q = (f"QUESTION:\nDoes any panel show the word {word}?\n\n"
                 "Reply with yes or no only.")
            with_img = score(img, q, yn)
            no_img = score(None, q, yn)
            ci = (with_img or {}).get("choice")
            cc = (no_img or {}).get("choice")
            nhit_i += int(ci == gold)
            nhit_c += int(cc == gold)
            results.append({"shape": "noul", "word": word, "gold": gold,
                            "with_image": ci, "no_image": cc,
                            "probs_with": (with_img or {}).get("probs"),
                            "error_with": (with_img or {}).get("error")})
            print(f"  trial {t + 1}: word={word:<9} gold={gold:<3} "
                  f"with_image={ci} no_image={cc}")
        print(f"  noul correct WITH image:    {nhit_i}/6")
        print(f"  noul correct WITHOUT image: {nhit_c}/6  (control)")
    else:
        print("  no single-token yes/no from the tokenizer; noul shape skipped")

    # ── THE CONFOUND-FREE TEST ────────────────────────────────────────────
    # Everything above still varies the QUESTION per trial, so a model could
    # score by reading the word alone. This one holds the question BYTE-IDENTICAL
    # and moves only the image: the same word walks through all three panels.
    # If d1 reads the image, the answer MUST walk with it. If the answer stays
    # put, d1 is ignoring the image and no accuracy number means anything.
    print("\n=== PERMUTATION TEST (question byte-identical, only the image moves) ===")
    letters_p = [chr(ord("A") + i) for i in range(len(POSITIONS))]
    lids_p = letter_ids(letters_p)
    probe_word = "ZEPHYR"
    q_fixed = (f"QUESTION:\nWhich panel shows the word {probe_word}?\n\n"
               f"Options:\n{options_text()}\n\nReply with the option code only.")
    moved: List[str] = []
    for pos in range(len(POSITIONS)):
        placement = {i: WORDS[(i + 2) % len(WORDS)] for i in range(len(POSITIONS))}
        placement[pos] = probe_word
        img = build_image(placement)
        r = score(img, q_fixed, lids_p)
        got = (r or {}).get("choice")
        moved.append(got or "?")
        print(f"  word at panel {pos + 1} (gold {letters_p[pos]}): "
              f"answered {got}  conf="
              f"{(r or {}).get('probs', {}).get(got, 0):.3f}"
              + (f"  ERR={(r or {}).get('error')}" if (r or {}).get("error") else ""))
    follows = all(moved[p] == letters_p[p] for p in range(len(moved)))
    distinct = len(set(moved))
    print(f"  answers as the word moves: {moved}")
    print(f"  distinct answers: {distinct}/{len(moved)}  "
          f"(1 = the image is being ignored; {len(moved)} = it is being read)")
    print(f"  answer follows the image: {follows}")
    results.append({"shape": "permutation", "word": probe_word,
                    "answers_as_word_moves": moved, "follows": follows,
                    "distinct": distinct})

    # ── verdict ──────────────────────────────────────────────────────────────
    # The route proof comes FIRST: if the image did not raise prompt_tokens,
    # every number below is void, so say so before quoting them.
    tok_with = [r.get("prompt_tokens_with") for r in results
                if r.get("shape") == "choice" and r.get("prompt_tokens_with")]
    tok_without = [r.get("prompt_tokens_without") for r in results
                   if r.get("shape") == "choice" and r.get("prompt_tokens_without")]
    route_ok = bool(tok_with and tok_without
                    and min(tok_with) > max(tok_without))
    print("\n=== RESULT ===")
    if route_ok:
        print(f"ROUTE PROVEN: prompt_tokens with image {min(tok_with)}-{max(tok_with)} "
              f"vs without {min(tok_without)}-{max(tok_without)} "
              f"(+{min(tok_with) - max(tok_without)} image tokens)")
    else:
        print("ROUTE NOT PROVEN: the image did not reach the model "
              f"(with={tok_with[:3]} without={tok_without[:3]}). "
              "EVERY NUMBER BELOW IS VOID.")
    print(f"choice top-1 WITH image:    {hit_i}/{trials}  "
          f"({hit_i / max(1, trials):.0%})")
    print(f"choice top-1 WITHOUT image: {hit_c}/{trials}  "
          f"({hit_c / max(1, trials):.0%})   <- control")
    print(f"gain from the image:        {hit_i - hit_c:+d} of {trials}")
    if lat:
        print(f"latency with image: p50 {int(statistics.median(lat))} ms  "
              f"max {max(lat)} ms")
    verdict = (
        "GROUNDS: the image changes the answer above the no-image control."
        if hit_i > hit_c else
        "DOES NOT GROUND: the image does not beat the no-image control."
    )
    if follows:
        verdict = ("GROUNDS: the answer tracks the image when only the image "
                   "changes (permutation test passed).")
    elif distinct == 1:
        verdict = ("DOES NOT GROUND: the answer is INVARIANT to the image - "
                   "one answer for every placement. d1 is not reading it.")
    if not route_ok:
        verdict = "INCONCLUSIVE: image route not proven."
    print(f"\nVERDICT: {verdict}")
    with open("benchmarks/d1_image_grounding_probe.json", "w", encoding="utf-8") as fh:
        json.dump({"trials": trials, "route_proven": route_ok, "results": results,
                   "choice_with_image": hit_i, "choice_without_image": hit_c,
                   "verdict": verdict}, fh, indent=2)
    print("wrote benchmarks/d1_image_grounding_probe.json")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--trials", type=int, default=6)
    ap.add_argument("--save-dir", default="")
    ap.add_argument("--mode", choices=("backend", "native"), default="backend",
                    help="backend = our /completion shape; native = LiquidAI's "
                         "published Decision Index schema")
    a = ap.parse_args()
    if a.mode == "native":
        return native_probe(a.save_dir or None)
    return run(a.trials, a.save_dir or None)


if __name__ == "__main__":
    raise SystemExit(main())