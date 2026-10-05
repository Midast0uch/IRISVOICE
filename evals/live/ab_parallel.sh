#!/usr/bin/env bash
# A/B of the parallel DAG scheduler (IRIS_DER_PARALLEL=1 vs 0), interleaved so
# provider speed drift hits both arms. Usage: bash evals/live/ab_parallel.sh <task> <runs-per-arm> <arms...>
# e.g. bash evals/live/ab_parallel.sh r09_three_facts,r06_tokyo_osaka 2 1 0 1 0 (comma = several tasks)
cd "$(dirname "$0")/../.." || exit 1
TASK=$1; RUNS=$2; shift 2
for ARM in "$@"; do
  python scripts/iris_process_manager.py stop >/dev/null 2>&1
  export IRIS_DER_PARALLEL=$ARM IRIS_STACK_DUMP_S=4
  python scripts/iris_process_manager.py start --detach backend -- python start-backend.py >/dev/null 2>&1
  for i in $(seq 1 150); do
    [ "$(curl -s -m 3 -o /dev/null -w '%{http_code}' http://127.0.0.1:8090/health)" = "200" ] && break; sleep 5
  done
  L=$(ls -t .iris-logs/backend-*.log | head -1)
  until grep -aq "Whisper warm-up complete" "$L"; do sleep 5; done
  python evals/live/bind.py reasoning inceptionlabs mercury-2.5 >/dev/null
  python evals/live/bind.py tool_execution inceptionlabs mercury-2 >/dev/null
  python evals/live/web_on.py >/dev/null
  for r in $(seq 1 "$RUNS"); do
    TASKARGS=""; for t in ${TASK//,/ }; do TASKARGS="$TASKARGS --task $t"; done
    LOG="logs/ab_$(echo "$TASK" | tr ',' '+' | cut -c1-60)_${ARM}_$r.log"
    python evals/run_evals.py $TASKARGS --no-model-check > "$LOG" 2>&1
    grep -E '^(PASS|FAIL)' "$LOG" | sed "s/^/ARM parallel=$ARM run $r: /"
  done
done
echo ABDONE
