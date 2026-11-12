"""Deterministic fixtures for the `context` eval group (CLM T2.7).

Run:  python evals/fixtures/_context/generate.py [--out DIR] [--check]

Writes, under DIR (default: evals/fixtures):
  x01_log_triage/repo/service-logs/svc-01..14.txt
  x02_needle_retention/repo/notes/00_provisioning.md + repo/reports/vendor_01..12.txt
  x03_kv_chain/repo/kv/shard-01..24.kv
  x04_sketchpad/repo/data/{orders.csv,zones.csv,classes.csv,tax.txt}
  x05_history_needle/turns/t1..t7.txt        (pasted chunks sent as earlier turns)
and, beside this script, answers.json (every expected value) and tasks_context.json
(the task entries, graders included). Every byte comes from a seeded random.Random:
the same script gives the same files. `--check` regenerates into a temp dir and
compares with what is committed (exit 1 on any difference).

Why these sizes (see the T2.7 report): a node reads a file through read_file and the
result is clipped to 8,000 chars (node_executor NodeContext.result_chars), so a file
stays under ~7,800 chars to arrive whole; a node may make 12 calls (max_calls), so
14 / 12+1 / 24 files cannot be read by one node; a step result later steps see keeps
only NODE_BLOCK_HEAD = 2,500 chars per read, so the facts sit deep in each file.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import re
import shutil
import sys
import tempfile
from fractions import Fraction
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIXTURES = HERE.parent


def _w(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # newline="\n": the same bytes on every platform
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def _fill(rng: random.Random, lines: list, target: int, make) -> list:
    """Append make() lines until the text reaches `target` chars (never past +120)."""
    size = sum(len(x) + 1 for x in lines)
    while size < target:
        line = make()
        lines.append(line)
        size += len(line) + 1
    return lines


# -- x01 log triage ------------------------------------------------------------------

ERR_CODES = {
    "E-4417": "upstream timeout after retries",
    "E-2203": "checksum mismatch on shard",
    "E-8810": "lease expired before commit",
    "E-1096": "schema version rejected",
    "E-5531": "disk quota exceeded on volume",
    "E-7742": "token signature invalid",
    "E-3369": "queue overflow, dropping batch",
}
# file index (1-based) -> {code: number of ERROR lines}
ERR_PLAN = {
    1: {"E-4417": 2},
    2: {"E-2203": 3},
    3: {"E-8810": 1},
    4: {"E-7742": 2},
    5: {"E-1096": 4},
    6: {"E-4417": 3},
    8: {"E-5531": 2},
    9: {"E-2203": 2},
    10: {"E-7742": 1},
    11: {"E-5531": 3},
    12: {"E-4417": 2},
    13: {"E-8810": 2},
    14: {"E-8810": 1, "E-3369": 4},
}
SERVICES = ["auth", "billing", "catalog", "edge", "ingest", "mailer", "search", "sync"]
PATHS = ["/api/v2/items", "/api/v2/cart", "/api/v1/login", "/healthz", "/api/v2/orders", "/static/app.js"]


def gen_logs(out: Path, rng: random.Random, ans: dict) -> None:
    total = 0
    per_file = {}
    for n in range(1, 15):
        svc = f"svc-{n:02d}"
        sec = rng.randrange(0, 3000)

        def stamp():
            nonlocal sec
            sec += rng.randrange(1, 9)
            h, m, s = 6 + (sec // 3600) % 14, (sec // 60) % 60, sec % 60
            return f"2026-03-14 {h:02d}:{m:02d}:{s:02d}"

        def noise():
            k = rng.randrange(7)
            host = f"10.{rng.randrange(1, 4)}.{rng.randrange(0, 9)}.{rng.randrange(2, 99)}"
            if k == 0:
                return (f"{stamp()} {svc} INFO  request id={rng.randrange(10**7, 10**8)} "
                        f"path={rng.choice(PATHS)} status=200 ms={rng.randrange(3, 400)}")
            if k == 1:
                return (f"{stamp()} {svc} INFO  metrics errors=0 error_rate=0.00 "
                        f"p95_ms={rng.randrange(20, 300)} conns={rng.randrange(4, 90)}")
            if k == 2:
                return f"{stamp()} {svc} DEBUG cache hit key=user:{rng.randrange(1000, 9999)} ttl={rng.randrange(10, 600)}s"
            if k == 3:
                return f"{stamp()} {svc} INFO  connected to {rng.choice(SERVICES)} at {host} in {rng.randrange(2, 80)}ms"
            if k == 4:
                return (f"{stamp()} {svc} WARN  slow response from {host} "
                        f"after {rng.randrange(800, 2400)}ms (no error)")
            if k == 5:
                code = rng.choice(["E-4417", "E-2203", "E-9001"])
                return f"{stamp()} {svc} WARN  retrying after {code} on {host} attempt={rng.randrange(1, 3)} (recovered)"
            return f"{stamp()} {svc} INFO  heartbeat ok uptime={rng.randrange(100, 99999)}s rss_mb={rng.randrange(80, 900)}"

        errs = []
        for code, cnt in ERR_PLAN.get(n, {}).items():
            for _ in range(cnt):
                errs.append((code, f"{ERR_CODES[code]} (host=10.{rng.randrange(1, 4)}.{rng.randrange(0, 9)}.{rng.randrange(2, 99)} "
                                   f"attempt={rng.randrange(1, 6)})"))
        lines: list = []
        _fill(rng, lines, 7300, noise)
        # spread the ERROR lines over the whole file, some after char 2,500
        slots = sorted(rng.sample(range(5, len(lines)), len(errs))) if errs else []
        for (code, msg), pos in zip(errs, slots):
            lines[pos] = f"{stamp()} {svc} ERROR [{code}] {msg}"
        text = "\n".join(lines) + "\n"
        assert 7300 <= len(text) <= 7800, (svc, len(text))
        _w(out / "x01_log_triage" / "repo" / "service-logs" / f"{svc}.txt", text)
        per_file[svc] = len(text)
        total += len(errs)
    ans["x01"] = {"codes": sorted(ERR_CODES), "error_lines": total, "file_chars": per_file,
                  "needles": sorted(ERR_CODES)}


# -- x02 needle retention -------------------------------------------------------------

def gen_needle(out: Path, rng: random.Random, ans: dict) -> None:
    token = "RB-7731-KX"
    notes = (
        "# Provisioning notes - region eu-west-3\n\n"
        "Cluster owner: platform-ops. Pager rota changes every second Monday.\n"
        "The previous rollback token (expired last week, do not use): RB-1204-ZZ\n"
        f"The CURRENT rollback token for this cycle: {token}\n"
        "Maintenance windows are announced on the ops calendar, never by chat.\n"
    )
    _w(out / "x02_needle_retention" / "repo" / "notes" / "00_provisioning.md", notes)
    cents = 0
    per_file = {}
    for n in range(1, 13):
        lines = [f"VENDOR REPORT {n:02d} - period 2026-Q1", f"vendor_ref: V{rng.randrange(1000, 9999)}"]

        def noise():
            k = rng.randrange(4)
            amt = rng.randrange(500, 99999) / 100
            if k == 0:
                return f"line_item {rng.randrange(1, 900):03d}: {rng.choice(['bolts', 'cable', 'rack kit', 'licence', 'support hours', 'freight'])} qty={rng.randrange(1, 60)} amount: {amt:.2f}"
            if k == 1:
                return f"note: delivery batch {rng.randrange(100, 999)} acknowledged by {rng.choice(['dock-a', 'dock-b', 'dock-c'])} at {rng.randrange(6, 20):02d}:{rng.randrange(0, 60):02d}"
            if k == 2:
                return f"credit_total: {amt:.2f}"
            return f"invoice_subtotal: {amt:.2f}"

        _fill(rng, lines, 7000, noise)
        for _ in range(4):
            v = rng.randrange(10000, 480000)
            cents += v
            pos = rng.randrange(8, len(lines))
            lines.insert(pos, f"invoice_total: {v // 100}.{v % 100:02d}")
        text = "\n".join(lines) + "\n"
        assert len(text) <= 7800, (n, len(text))
        _w(out / "x02_needle_retention" / "repo" / "reports" / f"vendor_{n:02d}.txt", text)
        per_file[f"vendor_{n:02d}.txt"] = len(text)
    ans["x02"] = {"token": token, "sum": f"{cents // 100}.{cents % 100:02d}", "file_chars": per_file,
                  "needles": [token]}


# -- x03 kv chain ----------------------------------------------------------------------

def gen_kv(out: Path, rng: random.Random, ans: dict) -> None:
    shards = {i: [] for i in range(1, 25)}
    vals = {}
    leaves = [f"base_{c}" for c in "abcdefghijkl"]
    for i, name in enumerate(leaves):
        v = rng.randrange(7, 90)
        vals[name] = v
        shards[1 + i].append(f"{name} = {v}")
    mids = {
        "mid_a": ("sum", ["base_a", "base_b", "base_c", "base_d"], 11, 14),
        "mid_b": ("sum", ["base_e", "base_f", "base_g", "base_h"], -5, 17),
        "mid_c": ("sum", ["base_i", "base_j", "base_k", "base_l"], 3, 19),
    }
    for name, (_op, refs, add, shard) in mids.items():
        vals[name] = sum(vals[r] for r in refs) + add
        shards[shard].append(f"{name} = sum(@{', @'.join(refs)}) + {add}" if add >= 0
                             else f"{name} = sum(@{', @'.join(refs)}) - {-add}")
    vals["final"] = vals["mid_a"] * vals["mid_b"] - vals["mid_c"]
    shards[24].append("final = @mid_a * @mid_b - @mid_c")
    # decoys: same-looking keys that are NOT the ones final refers to
    for i in range(1, 25):
        for _ in range(9):
            decoy = rng.choice(["base_", "mid_", "final_"]) + rng.choice("abcdefghijkl") + rng.choice(["_old", "_draft", "_test", "_v0"])
            shards[i].append(f"{decoy} = {rng.randrange(1, 999)}")
    for i in range(1, 25):
        rng.shuffle(shards[i])
        lines = [f"# kv shard {i:02d} of 24 - format: key = expression ('@key' reads another key)"] + shards[i]

        def pad():
            return f"# {rng.choice(['owner', 'checked', 'synced', 'rev'])}: {rng.choice(['ops', 'infra', 'data'])}-{rng.randrange(100, 999)} {rng.choice(['ok', 'pending', 'stale'])}"

        _fill(rng, lines, 1800, pad)
        _w(out / "x03_kv_chain" / "repo" / "kv" / f"shard-{i:02d}.kv", "\n".join(lines) + "\n")
    ans["x03"] = {"final": vals["final"], "mid_a": vals["mid_a"], "mid_b": vals["mid_b"], "mid_c": vals["mid_c"],
                  "needles": [f"{n} = {vals[n]}" for n in leaves]}


# -- x04 sketchpad ----------------------------------------------------------------------

def gen_sketch(out: Path, rng: random.Random, ans: dict) -> None:
    root = out / "x04_sketchpad" / "repo" / "data"
    zones = {}
    zl = ["zone,region,base_cents,per_kg_cents"]
    for z in range(1, 41):
        region = ["north", "south", "east", "west"][z % 4]
        zones[f"Z-{z:02d}"] = (region, rng.randrange(300, 1200), rng.randrange(40, 160))
        zl.append(f"Z-{z:02d},{region},{zones[f'Z-{z:02d}'][1]},{zones[f'Z-{z:02d}'][2]}")
    _w(root / "zones.csv", "\n".join(zl) + "\n")
    classes = {"standard": 100, "express": 140, "bulky": 165, "fragile": 120}
    cl = ["class,multiplier_percent"] + [f"{k},{v}" for k, v in classes.items()]

    def cpad():
        return f"# revision {rng.randrange(1, 90)}: {rng.choice(['audited', 'unchanged', 'reviewed by finance'])} on 2026-0{rng.randrange(1, 4)}-{rng.randrange(10, 28)}"

    _fill(rng, cl, 600, cpad)
    _w(root / "classes.csv", "\n".join(cl) + "\n")
    tax_pct = {"north": 5, "south": 8, "east": 6, "west": 10}
    tl = ["SHIPPING TAX RULES 2026", "",
          "Tax is added to the shipping cost of an order and depends on the region of its zone."]
    for region, p in tax_pct.items():
        tl.append(f"For zones in the {region} region the tax rate is {p} percent.")

    def tpad():
        return rng.choice([
            "Customs notes are filed quarterly by the compliance desk and do not change these rates.",
            f"Memo {rng.randrange(100, 999)}: carrier {rng.choice(['A', 'B', 'C'])} surcharges are handled elsewhere.",
            "Rounding: the final cost of EACH order is rounded half up to whole cents; totals add the rounded costs.",
            "Weights are rounded UP to the next whole kilogram before the per-kg rate applies.",
            f"Archive ref {rng.randrange(1000, 9999)}: superseded 2025 table, ignore.",
        ])

    pad_lines = []
    _fill(rng, pad_lines, 7000, tpad)
    tl.extend(pad_lines)
    _w(root / "tax.txt", "\n".join(tl) + "\n")
    ol = ["order_id,zone,weight_kg,class"]
    orders = {}
    n = 0
    while sum(len(x) + 1 for x in ol) < 7400:
        n += 1
        oid = f"ORD-{n:04d}"
        z = f"Z-{rng.randrange(1, 41):02d}"
        w = round(rng.randrange(5, 480) / 10, 1)
        c = rng.choice(list(classes))
        orders[oid] = (z, w, c)
        ol.append(f"{oid},{z},{w},{c}")
    _w(root / "orders.csv", "\n".join(ol) + "\n")
    picks = [f"ORD-{k:04d}" for k in (23, 61, 98, 140) if f"ORD-{k:04d}" in orders]
    assert len(picks) == 4, len(orders)
    costs = {}
    for oid in picks:
        z, w, c = orders[oid]
        region, base, per = zones[z]
        cents = Fraction(base + per * math.ceil(w)) * classes[c] / 100 * (100 + tax_pct[region]) / 100
        costs[oid] = int(math.floor(cents + Fraction(1, 2)))   # half up, exact
    total = sum(costs.values())
    ans["x04"] = {"orders": picks, "costs_cents": costs, "total_cents": total,
                  "needles": [f"{o},{orders[o][0]},{orders[o][1]},{orders[o][2]}" for o in picks],
                  "file_chars": {p.name: p.stat().st_size for p in root.iterdir()}}


# -- x05 history needle ------------------------------------------------------------------

def gen_history(out: Path, rng: random.Random, ans: dict) -> None:
    needle = "MW-5532-QF"
    decoys = ["MW-2210-AB", "MW-9047-ZN", "MW-3381-HC", "MW-7765-DR"]
    for t in range(1, 8):
        head = (f"Chunk {t} of 7 of the staging deploy log. Do not analyze it, just reply with the "
                f"single word ok.\n\n")

        def line():
            k = rng.randrange(5)
            ts = f"2026-03-14 {rng.randrange(0, 24):02d}:{rng.randrange(0, 60):02d}:{rng.randrange(0, 60):02d}"
            if k == 0:
                return f"{ts} deploy-agent INFO  step={rng.choice(['fetch', 'verify', 'unpack', 'migrate', 'warm'])} pod=stg-{rng.randrange(1, 40)} ms={rng.randrange(5, 900)}"
            if k == 1:
                return f"{ts} scheduler INFO  placed job {rng.randrange(10**5, 10**6)} on node n{rng.randrange(1, 30)} cpu={rng.randrange(1, 16)}"
            if k == 2:
                return f"{ts} registry INFO  pulled image sha256:{rng.randrange(16**8, 16**9):x} size_mb={rng.randrange(20, 900)}"
            if k == 3:
                return f"{ts} deploy-agent WARN  slow pull for layer {rng.randrange(1, 30)} ({rng.randrange(2, 20)}s)"
            return f"{ts} gate INFO  health check {rng.randrange(1, 50)} passed in {rng.randrange(40, 700)}ms"

        lines: list = []
        _fill(rng, lines, 30000, line)
        if t == 3:
            pos = len(lines) * 2 // 3
            lines.insert(pos, f"2026-03-14 22:41:07 change-board NOTICE tonight's deploy runs in maintenance window id {needle} (approved by ops)")
        else:
            d = decoys[t % len(decoys)]
            lines.insert(len(lines) // 2, f"2026-03-14 09:12:31 change-board NOTICE maintenance window id {d} is the quarterly freeze slot (NOT tonight)")
        _w(out / "x05_history_needle" / "turns" / f"t{t}.txt", head + "\n".join(lines) + "\n")
    ans["x05"] = {"needle": needle, "needle_turn": 3, "turn_chars": 30000, "needles": [needle]}


# -- tasks -----------------------------------------------------------------------------------

def build_tasks(ans: dict) -> list:
    base_dev = {"group": "context", "mode": "developer", "path": "dev_cli", "timeout_s": 1800}
    x04 = ans["x04"]

    def money(cents: int) -> str:
        d = cents // 100
        grouped = f"{d:,}".replace(",", ",?")
        return grouped + r"\." + f"{cents % 100:02d}"

    return [
        {**base_dev, "id": "x01_log_triage",
         "prompt": ("The project is in {workdir}. The service-logs/ folder holds 14 service logs (svc-01.txt to svc-14.txt). "
                    "List every distinct error code (format E-nnnn) that appears on an ERROR line, not on WARN or "
                    "INFO lines, and tell me how many ERROR lines there are in total across all 14 logs. "
                    "Do not change any file."),
         "reply_patterns": [re.escape(c) for c in ans["x01"]["codes"]] + [rf"\b{ans['x01']['error_lines']}\b"],
         "pressure": {"reads": 14, "read_chars": sum(ans["x01"]["file_chars"].values()),
                      "needs": "early and late reads combined: 7 codes over 14 files, count over all"}},
        {**base_dev, "id": "x02_needle_retention",
         "prompt": ("The project is in {workdir}. First read notes/00_provisioning.md and note the CURRENT rollback "
                    "token. Then read every report in reports/ (vendor_01.txt to vendor_12.txt) and add up all the "
                    "invoice_total values (not invoice_subtotal, not credit_total). Reply with the rollback token and "
                    "the sum of the invoice totals. Do not change any file."),
         "reply_patterns": [re.escape(ans["x02"]["token"]), _sum_pattern(ans["x02"]["sum"])],
         "pressure": {"reads": 13, "read_chars": sum(ans["x02"]["file_chars"].values()) + 420,
                      "needs": "fact from the first read used after 12 large reads"}},
        {**base_dev, "id": "x03_kv_chain",
         "prompt": ("The project is in {workdir}. The kv/ folder holds 24 shard files (shard-01.kv to shard-24.kv). "
                    "Each line is 'key = expression' and '@name' means the value of another key, which is defined in "
                    "some shard. Work out the integer value of the key final (not final_a_old or any other look-alike) "
                    "and tell me the number. Do not change any file."),
         "reply_patterns": [rf"(?<![\d,.]){_int_pattern(ans['x03']['final'])}(?![\d])"],
         "pressure": {"reads": 24, "read_chars": 24 * 1850,
                      "needs": "state carried over 24 small reads: 12 leaves, 3 mids, 1 final"}},
        {**base_dev, "id": "x04_sketchpad",
         "prompt": ("The project is in {workdir}. For the orders " + ", ".join(x04["orders"]) +
                    " in data/orders.csv work out the shipping cost of each: the zone's base rate plus its per-kg rate "
                    "times the weight (data/zones.csv), then multiplied by the class multiplier (data/classes.csv), "
                    "then plus the tax for the zone's region (data/tax.txt, which also says how to round). Tell me the "
                    "cost of each order and the grand total, in dollars. Do not change any file."),
         "reply_patterns": [money(c) for c in x04["costs_cents"].values()] + [money(x04["total_cents"])],
         "pressure": {"reads": 4, "read_chars": sum(x04["file_chars"].values()),
                      "needs": "intermediates per order (zone, weight, rates, multiplier, tax) kept until the total"}},
        {"id": "x05_history_needle", "group": "context", "mode": "personal", "path": "text_message",
         "timeout_s": 900, "prior_timeout_s": 600,
         "prior_turns": [{"fixture": f"x05_history_needle/turns/t{t}.txt"} for t in range(1, 8)],
         "prompt": ("In the third chunk of the deploy log I pasted, which maintenance window id did tonight's deploy "
                    "run in? Reply with the id only."),
         "reply_patterns": [re.escape(ans["x05"]["needle"])],
         "pressure": {"reads": 0, "read_chars": 7 * 30000,
                      "needs": "fact in turn 3 of 7 pasted turns; the last 5 turns are 150,000 chars"}},
    ]


def _int_pattern(n: int) -> str:
    return f"{n:,}".replace(",", ",?")


def _sum_pattern(s: str) -> str:
    whole, cents = s.split(".")
    digits = f"{int(whole):,}".replace(",", ",?")
    return digits + r"\." + cents


def generate(out: Path) -> dict:
    ans: dict = {}
    gen_logs(out, random.Random(7101), ans)
    gen_needle(out, random.Random(7102), ans)
    gen_kv(out, random.Random(7103), ans)
    gen_sketch(out, random.Random(7104), ans)
    gen_history(out, random.Random(7105), ans)
    return ans


def _digest(root: Path, names) -> dict:
    d = {}
    for n in names:
        for p in sorted((root / n).rglob("*")):
            if p.is_file():
                d[str(p.relative_to(root)).replace("\\", "/")] = hashlib.sha256(p.read_bytes()).hexdigest()
    return d


TASK_DIRS = ["x01_log_triage", "x02_needle_retention", "x03_kv_chain", "x04_sketchpad", "x05_history_needle"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(FIXTURES))
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    if args.check:
        with tempfile.TemporaryDirectory() as tmp:
            ans = generate(Path(tmp))
            same = _digest(Path(tmp), TASK_DIRS) == _digest(FIXTURES, TASK_DIRS)
            same = same and json.loads((HERE / "answers.json").read_text(encoding="utf-8")) == ans
            same = same and json.loads((HERE / "tasks_context.json").read_text(encoding="utf-8")) == build_tasks(ans)
        print("fixtures reproduce byte for byte" if same else "FIXTURES DIFFER from what generate.py writes")
        return 0 if same else 1
    out = Path(args.out)
    for n in TASK_DIRS:
        shutil.rmtree(out / n, ignore_errors=True)
    ans = generate(out)
    _w(HERE / "answers.json", json.dumps(ans, indent=2) + "\n")
    _w(HERE / "tasks_context.json", json.dumps(build_tasks(ans), indent=2) + "\n")
    print("wrote", ", ".join(TASK_DIRS))
    return 0


if __name__ == "__main__":
    sys.exit(main())
