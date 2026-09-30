# Execution audit — 2026-09-29

Start here when continuing the agent-execution work.

| What | Where |
|---|---|
| **Latest progress + next steps (read first)** | `PROGRESS.md` ("START HERE") — also MCM pin `pin_afa4442771d1` |
| Execution audit (blockers B1–B17, one-engine design, roadmap) | `execution-audit.html` — also https://claude.ai/artifact/HC1UMxkoe1KuPjfZML54UW |
| Reply surface audit (card rules, `create_artifact`, page artifacts, compact cards) | `reply-surface.html` — also https://claude.ai/artifact/M72Nhc7FcxG8Zad69PReS8 |
| Full handoff: owner decisions, fixes done, stale tests, next steps | MCM pin `pin_dc96cc9c9681` (`pin_search("HANDOFF execution audit")`) |
| Pass-rate harness | `evals/run_evals.py`, `evals/tasks.json`, `evals/fixtures/` |
| Baseline (before the Phase 1 fixes) | `evals/baseline.json` — coding 0/15, research 1/6 |

The HTML files are self-contained; open them in a browser.

## Owner decisions (short form)

- Model-agnostic. Split roles stay: local 2.6B tool model = hands, API Brain = pen (Brain writes large fields such as file bodies).
- One engine: DER-DAG plans and branches; each node runs a bounded work loop (`run_node`, new module). Developer mode first.
- Oracle advises and records shadow rows inside node loops.
- Ripgrep (`grep_files` / `glob_files`) is first-class in developer mode.
- Developer view: a live execution matrix grown from `app/cli-preview`.
- Reply surface: one `create_artifact` tool; HTML pages in a sandboxed iframe; compact titled cards; permission/question cards anchored in their turn.

## Running the harness

A full run is heavy (research turns take 5–10 minutes each) and crashed Claude Code twice. Run small subsets from your own terminal, with the backend (:8090) and the tool model (:8082) running:

```
python evals/run_evals.py --task c01_fix_off_by_one --task c04_implement_from_tests --task c15_iterate_until_green
```

After any crash, check `data/iris_config.json` for a leftover `projects` entry named `iris-evals` and remove it.
