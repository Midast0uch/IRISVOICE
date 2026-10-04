#!/bin/bash
# Usage: run_series.sh <tag> <mode:entry> [<mode:entry> ...]   entry = chat | cli
cd /c/dev/IRISVOICE
S="${IRIS_RUN_DIR:-logs/live_runs}"; mkdir -p "$S"
tag=$1; shift
i=0
for spec in "$@"; do
  i=$((i+1)); mode=${spec%%:*}; entry=${spec##*:}; name="${tag}_${i}_${mode}_${entry}"
  start=$(stat -c %s logs/iris.log)
  timeout 640 python evals/live/live_browser_task.py "$mode" "$entry" > "$S/$name.txt" 2>&1
  sleep 3
  tail -c +$start logs/iris.log > "$S/$name.log"
  reply=$(grep -E "REPLY" "$S/$name.txt" | cut -c1-150)
  echo "$name | ${reply:-NO REPLY}"
done
