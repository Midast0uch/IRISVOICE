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
