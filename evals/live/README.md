# Live browser checks (HANDOFF 10, 2026-10-03)

Run against a backend started detached (`python -m compileall -q backend`, then
`$env:IRIS_STACK_DUMP_S='4'; npm run iris:start:backend`, wait for `/health` 200).

```
python evals/live/bind.py reasoning inceptionlabs mercury-2.5
python evals/live/bind.py tool_execution inceptionlabs mercury-2
python evals/live/web_on.py
python evals/live/live_browser_task.py developer   # the Kilimanjaro Wikipedia task
python evals/live/nav_probe2.py                     # the same goto OUTSIDE the backend
```

Before a run, note `stat -c %s logs/iris.log` and read the run with `tail -c +<bytes>`:
iris.log is > 2 GB. Reference: run A9 = 95 s reply, 13 model / 8 tool calls (PROGRESS S25-S28).

## Turn split (session 8161c922, 2026-10-04)

`bash evals/live/run_series.sh <tag> personal:chat developer:cli ...` runs one live task per
`mode:entry` and saves each run's log slice to `logs/live_runs/` (override: `IRIS_RUN_DIR`).
`python evals/live/turn_split.py logs/live_runs/<tag>_*.log` splits each turn into model wait,
tool wait and IRIS's own time (interval union of `[InferenceRouter] call done` and
`TOOL_DISPATCH`). `python evals/live/turn_gaps.py <run.log> 3` lists the stretches with no model
or tool call in flight - IRIS-side cost. Vary one variable at a time and interleave runs.
