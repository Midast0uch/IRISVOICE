import re
path = '.iris-logs/backend-20260909-173121-pid11020.log'
pat = re.compile(
    r"Processing text message|TASK_CARD|TOOL_DECISION|TOOL_DISPATCH|TOOL_DECISION_FAIL|"
    r"crawler|Crawler|CRAWLER|DER completed|DER path error|\[DER\]|Empty response|"
    r"DataExtractor|batch|Batch|synthes|Synthes|subset|fetch|Fetch|page|PAGE|"
    r"DER response|task:start|task:done|task:fail|step-direct infer empty"
)
out = []
with open(path, encoding='utf-8', errors='replace') as f:
    for i, line in enumerate(f):
        if pat.search(line):
            out.append(f"{i+1}: {line.rstrip()[:240]}")
print("TOTAL", len(out))
# print the last 120 hits (the live turn is the tail of the log)
for l in out[-120:]:
    print(l)
