"""Offline validation of the `context` group (CLM T2.7). No backend, no model.

    python evals/fixtures/_context/validate.py

1. the committed fixtures are what generate.py writes (byte for byte);
2. the group loads through the harness's own loader and every task has fixtures;
3. each grader PASSES a correct answer built from answers.json and FAILS wrong ones
   (a missing item, an off-by-one total, a decoy value);
4. prints the pressure arithmetic (see the T2.7 report for where each limit lives).
"""
from __future__ import annotations

import json
import math
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
EVALS = HERE.parents[1]
sys.path.insert(0, str(EVALS))

import run_evals as R  # noqa: E402

ANS = json.loads((HERE / "answers.json").read_text(encoding="utf-8"))
failures: list = []


def check(name: str, ok: bool) -> None:
    print(("ok    " if ok else "FAIL  ") + name)
    if not ok:
        failures.append(name)


# 1 -- reproducible
rc = subprocess.run([sys.executable, str(HERE / "generate.py"), "--check"], capture_output=True, text=True)
check("fixtures reproduce byte for byte from generate.py", rc.returncode == 0)

# 2 -- loader
tasks = R._load_tasks(["context"], [])
check("group `context` selects >= 5 tasks", len(tasks) >= 5)
for t in tasks:
    if t["path"] == "dev_cli":
        check(f"{t['id']}: fixture repo exists", (R.FIXTURES_DIR / t["id"] / "repo").is_dir())
    for pt in t.get("prior_turns", []):
        check(f"{t['id']}: prior turn fixture {pt['fixture']}", (R.FIXTURES_DIR / pt["fixture"]).is_file())
    check(f"{t['id']}: has reply_patterns", bool(t.get("reply_patterns")))
by_id = {t["id"]: t for t in tasks}


def grade(tid: str, text: str) -> list:
    return R._check_patterns(by_id[tid], text)


def money(c: int) -> str:
    return f"${c // 100:,}.{c % 100:02d}"


# 3 -- graders
x1 = ANS["x01"]
good = f"Distinct ERROR codes: {', '.join(x1['codes'])}. Total ERROR lines: {x1['error_lines']}."
check("x01 passes a correct answer", grade("x01_log_triage", good) == [])
check("x01 fails with one code missing", grade("x01_log_triage", good.replace(x1["codes"][3], "")) != [])
check("x01 fails with a WARN-inflated total", grade("x01_log_triage", good.replace(str(x1["error_lines"]), str(x1["error_lines"] + 5))) != [])
x2 = ANS["x02"]
whole, cents = x2["sum"].split(".")
good = f"Rollback token {x2['token']}; invoice totals add up to {int(whole):,}.{cents}."
check("x02 passes a correct answer (with thousands commas)", grade("x02_needle_retention", good) == [])
check("x02 passes the same sum without commas", grade("x02_needle_retention", good.replace(f"{int(whole):,}", whole)) == [])
check("x02 fails on the expired token", grade("x02_needle_retention", good.replace(x2["token"], "RB-1204-ZZ")) != [])
check("x02 fails on an off-by-one-cent sum", grade("x02_needle_retention", good.replace("." + cents, f".{(int(cents) + 1) % 100:02d}")) != [])
x3 = ANS["x03"]
check("x03 passes the right value", grade("x03_kv_chain", f"final = {x3['final']:,}") == [])
check("x03 fails when a mid is used instead", grade("x03_kv_chain", f"final = {x3['mid_a'] * x3['mid_b']}") != [])
x4 = ANS["x04"]
good = "; ".join(f"{o}: {money(c)}" for o, c in x4["costs_cents"].items()) + f"; total {money(x4['total_cents'])}"
check("x04 passes a correct answer", grade("x04_sketchpad", good) == [])
check("x04 fails on a wrong grand total", grade("x04_sketchpad", good.replace(money(x4["total_cents"]), money(x4["total_cents"] + 1))) != [])
x5 = ANS["x05"]
check("x05 passes the needle", grade("x05_history_needle", f"{x5['needle']}") == [])
check("x05 fails on a decoy window id", grade("x05_history_needle", "MW-2210-AB") != [])

# 3b -- x05 turns must take the DIRECT path: tier0_classify -> QUESTION (no planning) for every prior turn and the ask
code = (
    "import json,sys;from backend.agent.semantic_gate import tier0_classify,is_web_search_request;"
    "ctx=[{'role':'assistant','content':'ok'}];out=[]\n"
    "for a in sys.argv[1:]:\n"
    "    t=open(a,encoding='utf-8').read() if a.endswith('.txt') else a\n"
    "    out.append([tier0_classify(t,ctx).intent.name,is_web_search_request(t)])\n"
    "print(json.dumps(out))")
turn_files = sorted(str(p) for p in (R.FIXTURES_DIR / "x05_history_needle" / "turns").glob("t*.txt"))
rc = subprocess.run([sys.executable, "-c", code, *turn_files, by_id["x05_history_needle"]["prompt"]],
                    capture_output=True, text=True, cwd=str(EVALS.parent))
try:
    verdicts = json.loads(rc.stdout.strip().splitlines()[-1])
except (ValueError, IndexError):
    verdicts = []
check("x05: the 7 prior turns and the ask all route direct (Tier0 QUESTION, no web trigger)",
      len(verdicts) == 8 and all(v[0] == "QUESTION" and not v[1] for v in verdicts))

# 4 -- pressure arithmetic (gauge rule: chars / 3.5)
MAX_CALLS, RESULT_CHARS, PRIOR_CLIP = 12, 8000, 24000      # node_executor.py :199 :201 :619 (limit * 3)
BLOCK_HEAD = 2500                                           # node_executor.py :140
SYSTEM_TOK, TOOLS_TOK_MED, TOOLS_TOK_P95 = 1396, 1733, 5968  # T0.1 block sizes (p95 system; tools median / p95)
tok = lambda chars: math.ceil(chars / 3.5)                  # noqa: E731
node_tool_chars = MAX_CALLS * RESULT_CHARS
node_max = SYSTEM_TOK + TOOLS_TOK_P95 + tok(PRIOR_CLIP) + tok(node_tool_chars) + 600
print(f"\nper-node prompt ceiling = {node_max} tokens "
      f"(system p95 {SYSTEM_TOK} + tools p95 {TOOLS_TOK_P95} + prior <= {tok(PRIOR_CLIP)} + "
      f"{MAX_CALLS} x {RESULT_CHARS} chars = {tok(node_tool_chars)} + ~600 call messages)")
for w in (128000, 64000, 32000, 16000, 8192):
    print(f"  node ceiling / window {w:>6}: {node_max / w:5.2f}")
print("\ntask arithmetic (read_chars = what the task must read through read_file):")
for t in tasks:
    p = t["pressure"]
    nodes = max(1, math.ceil(p["reads"] / (MAX_CALLS - 1))) if p["reads"] else 0
    kept = min(p["reads"] * BLOCK_HEAD, PRIOR_CLIP) if p["reads"] else 0
    print(f"  {t['id']:<22} reads={p['reads']:>2} read_chars={p['read_chars']:>7} "
          f"= {tok(p['read_chars']):>6} tok, nodes>= {nodes}, "
          f"read tok / 128k = {tok(p['read_chars']) / 128000:4.2f}, / 32k = {tok(p['read_chars']) / 32000:4.2f}, "
          f"/ 16k = {tok(p['read_chars']) / 16000:4.2f}; "
          f"heads a later step can keep <= {kept} chars of {p['read_chars']}")
print("\nx05: ConversationMemory keeps 10 messages (agent_kernel.py:615) and the ask is added before the context is read "
      "(kernel/turn.py:1539 vs :1580): the record at the ask = [turn 3 reply, turns 4-7, the ask]. Turns 4-7 = 4 x 28,000 chars = "
      f"{4 * 28000 // 4} tokens (chars/4) vs about 22.8k tokens left of _DIRECT_CTX_BUDGET 24,000 for history "
      f"(system ~1.1k, current turn ~0) = {4 * 28000 // 4 / 22800:.2f}; the oldest user message (the needle, turn 4) is trimmed.")

print("\n" + ("ALL OK" if not failures else f"{len(failures)} FAILED: {failures}"))
sys.exit(1 if failures else 0)
