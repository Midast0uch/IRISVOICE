#!/usr/bin/env python3
"""LoRA fine-tune of d1-3B on IRIS's own verified tool decisions (2026-10-11).

WHAT IT LEARNS: the ONE answer-slot token. Each example (from
scripts/export_tool_choice_training.py) is exactly the prompt d1 reads in IRIS
(manual im_start markup, state, QUESTION, coded options, "Reply with the option
code only.") and the option CODE of a tool call that WORKED. The loss is the
cross-entropy of that code at the answer slot - the same position and the same
readout (code max-pooled with its space form) IRIS uses, so training and
serving cannot drift apart.

HOW IT FITS: the base model loads in 4-bit (bitsandbytes NF4) with a LoRA
adapter on the attention, conv and MLP projections; sequences are a few hundred
tokens; an 8 GB GPU holds it. STOP THE BACKEND FIRST - the served d1 shares the GPU.

HONEST EVALUATION: the split is by TASK (examples of one task never sit on both
sides), and the held-out set is scored BEFORE and AFTER with the IRIS readout
(accuracy, and accuracy per confidence band). A fine-tune that does not raise
held-out accuracy at high confidence is not shipped.

OUTPUT: --out/adapter (LoRA) and, with --merge, --out/merged (bf16 weights,
ready for llama.cpp convert_hf_to_gguf.py + llama-quantize). A merged model is
a NEW decision identity: the served GGUF filename changes, every consumer's
calibration restarts, nothing inherits the old thresholds (AC25.8).

Usage (the base weights must already be on disk - downloading them is a separate,
approved step):
    python scripts/finetune_d1_lora.py --model D:/models/d1-3B --data data/training/tool_choice.jsonl \
        --out D:/models/d1-3B-iris-lora --epochs 3 --merge
"""

from __future__ import annotations

import argparse
import json
import math
import random
from collections import defaultdict
from pathlib import Path


def load_examples(path: str):
    rows = [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
    return [r for r in rows if r.get("prompt") and r.get("completion")]


def task_key(ex) -> str:
    """Group examples by their task so a split never leaks one task across
    sides: the state's first line is the step goal; the eval work folder's
    timestamp would differ per run, so it is stripped."""
    first = ex["prompt"].split("\n", 2)[1] if "\n" in ex["prompt"] else ex["prompt"]
    return " ".join(w for w in first.split() if "iris-evals" not in w)[:80]


def split(examples, holdout: float, seed: int):
    groups = defaultdict(list)
    for ex in examples:
        groups[task_key(ex)].append(ex)
    keys = sorted(groups)
    random.Random(seed).shuffle(keys)
    n_hold = max(1, int(len(keys) * holdout))
    hold = {k for k in keys[:n_hold]}
    train = [ex for k in keys if k not in hold for ex in groups[k]]
    test = [ex for k in hold for ex in groups[k]]
    return train, test


def code_ids(tok, prompt: str, code: str):
    """The readout group for one option code: the bare and space forms that
    are SINGLE tokens (decision_backend_d1._letter_readout)."""
    out = []
    for form in (code, f" {code}"):
        ids = tok.encode(form, add_special_tokens=False)
        if len(ids) == 1 and ids[0] not in out:
            out.append(ids[0])
    return out


def option_codes_in(prompt: str):
    """The option codes the prompt renders ("A ...", "B ..." lines after Options:)."""
    body = prompt.split("Options:\n", 1)[-1].split("\n\nReply", 1)[0]
    return [line.split(" ", 1)[0] for line in body.splitlines() if line.strip()]


def score(model, tok, examples, device, torch):
    """IRIS readout on each example: P over the option codes at the answer
    slot; returns [(confidence, correct)]."""
    out = []
    model.eval()
    with torch.no_grad():
        for ex in examples:
            ids = tok(ex["prompt"], add_special_tokens=False, return_tensors="pt").input_ids.to(device)
            logits = model(input_ids=ids).logits[0, -1].float()
            logz = logits - torch.logsumexp(logits, dim=-1)
            codes = option_codes_in(ex["prompt"])
            scores = []
            for c in codes:
                g = code_ids(tok, ex["prompt"], c)
                scores.append(max(float(logz[i]) for i in g) if g else -math.inf)
            m = max(scores)
            ps = [math.exp(s - m) if s > -math.inf else 0.0 for s in scores]
            tot = sum(ps) or 1.0
            ps = [p / tot for p in ps]
            best = max(range(len(ps)), key=ps.__getitem__)
            out.append((ps[best], codes[best] == ex["completion"]))
    return out


def report(tag, res):
    n = len(res)
    if not n:
        print(f"{tag}: no examples")
        return
    print(f"{tag}: n={n} accuracy={sum(c for _, c in res) / n:.3f}")
    for lo, hi in ((0, .6), (.6, .8), (.8, .9), (.9, 1.01)):
        b = [c for p, c in res if lo <= p < hi]
        if b:
            print(f"   conf[{lo:.2f},{hi:.2f}) n={len(b):4d} accuracy={sum(b) / len(b):.3f}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True, help="local path of the bf16 d1-3B weights")
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--epochs", type=int, default=3)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--rank", type=int, default=16)
    ap.add_argument("--smoothing", type=float, default=0.1,
                    help="label smoothing over the OPTIONS (small data: no 100%% certainty)")
    ap.add_argument("--holdout", type=float, default=0.2)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--merge", action="store_true")
    args = ap.parse_args()

    import torch
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
    from transformers import AutoModelForImageTextToText, AutoTokenizer, BitsAndBytesConfig

    examples = load_examples(args.data)
    train, test = split(examples, args.holdout, args.seed)
    print(f"examples={len(examples)} train={len(train)} held-out={len(test)} (split by task)")

    tok = AutoTokenizer.from_pretrained(args.model, trust_remote_code=True)
    model = AutoModelForImageTextToText.from_pretrained(
        args.model, trust_remote_code=True, device_map={"": 0},
        quantization_config=BitsAndBytesConfig(
            load_in_4bit=True, bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.bfloat16),
    )
    device = next(model.parameters()).device
    report("BEFORE (held-out)", score(model, tok, test, device, torch))

    model = prepare_model_for_kbit_training(model)
    model = get_peft_model(model, LoraConfig(
        r=args.rank, lora_alpha=2 * args.rank, lora_dropout=0.05, bias="none",
        # the LANGUAGE model only: the SigLIP2 vision tower uses the same
        # q/k/v/out_proj names, and tool decisions are text decisions
        target_modules=r".*language_model.*\.(q_proj|k_proj|v_proj|out_proj|in_proj|w1|w2|w3)$",
    ))
    model.print_trainable_parameters()
    opt = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=args.lr)
    rng = random.Random(args.seed)

    def option_logits(logits, prompt):
        """The READOUT's scores: per option code, the best of its forms - the
        loss is over THESE (the distribution IRIS reads), not the 128k vocab."""
        codes = option_codes_in(prompt)
        groups = [code_ids(tok, prompt, c) for c in codes]
        if any(not g for g in groups):
            return None, codes
        return torch.stack([logits[g].max() for g in groups]), codes

    def heldout_nll():
        """Mean -log P(target) over the held-out examples - the calibration-
        aware score the best epoch is chosen by (overconfidence is punished)."""
        model.eval()
        tot, n = 0.0, 0
        with torch.no_grad():
            for ex in test:
                ids = tok(ex["prompt"], add_special_tokens=False, return_tensors="pt").input_ids.to(device)
                s, codes = option_logits(model(input_ids=ids).logits[0, -1].float(), ex["prompt"])
                if s is None or ex["completion"] not in codes:
                    continue
                tot += float(-torch.log_softmax(s, 0)[codes.index(ex["completion"])])
                n += 1
        return tot / max(1, n)

    best_nll, best_state = heldout_nll(), None
    print(f"held-out NLL before training: {best_nll:.4f}")
    for epoch in range(args.epochs):
        model.train()
        rng.shuffle(train)
        total = 0.0
        for ex in train:
            ids = tok(ex["prompt"], add_special_tokens=False, return_tensors="pt").input_ids.to(device)
            s, codes = option_logits(model(input_ids=ids).logits[0, -1].float(), ex["prompt"])
            if s is None or ex["completion"] not in codes:
                continue
            loss = torch.nn.functional.cross_entropy(
                s.unsqueeze(0), torch.tensor([codes.index(ex["completion"])], device=device),
                label_smoothing=args.smoothing)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            opt.zero_grad(set_to_none=True)
            total += float(loss.detach())
        nll = heldout_nll()
        print(f"epoch {epoch + 1}: train loss {total / max(1, len(train)):.4f} held-out NLL {nll:.4f}")
        if nll < best_nll:
            best_nll = nll
            best_state = {k: v.detach().clone() for k, v in model.state_dict().items() if "lora_" in k}
    if best_state is None:
        print("no epoch beat the base model on held-out NLL - nothing to keep")
        return 1
    model.load_state_dict(best_state, strict=False)
    report("AFTER (held-out, best epoch)", score(model, tok, test, device, torch))

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(out / "adapter")
    if args.merge:
        # merge into full-precision base weights (a 4-bit base cannot be merged)
        from peft import PeftModel

        base = AutoModelForImageTextToText.from_pretrained(
            args.model, trust_remote_code=True, torch_dtype=torch.bfloat16)
        merged = PeftModel.from_pretrained(base, out / "adapter").merge_and_unload()
        merged.save_pretrained(out / "merged")
        tok.save_pretrained(out / "merged")
        print(f"merged weights -> {out / 'merged'} (convert with llama.cpp convert_hf_to_gguf.py)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
