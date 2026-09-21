"""Map the terminal paths: does every grade-reporting path also emit a card event?"""
import io, re

p = r"C:\dev\IRISVOICE\backend\agent\agent_kernel.py"
lines = io.open(p, encoding="utf-8", errors="replace").readlines()

def owner(n):
    for i in range(n - 1, -1, -1):
        if re.match(r"^(    (async )?def |def |class )", lines[i]):
            return i + 1, lines[i].strip()[:60]
    return (None, None)

# Extent of _execute_plan_der
start = 8160
end = None
for i in range(start, len(lines)):
    if re.match(r"^    (async )?def ", lines[i]) or re.match(r"^class ", lines[i]):
        end = i
        break
print(f"_execute_plan_der: lines {start}..{end}")
print()

# Every function-level return (indent <= 8) inside _execute_plan_der
print("=== function-level exits inside _execute_plan_der (indent<=8) ===")
for i in range(start - 1, end):
    s = lines[i]
    m = re.match(r"^( {4,8})(return|raise)\b", s)
    if m:
        print(f"  {i+1}: {s.strip()[:100]}")
print()

print("=== _der_report_run_grade call sites ===")
for i, s in enumerate(lines):
    if "_der_report_run_grade(" in s and "def " not in s:
        print(f"  {i+1} -> owner {owner(i+1)}")
print()

print("=== _emit_terminal_event references ===")
for i, s in enumerate(lines):
    if "_emit_terminal_event" in s:
        print(f"  {i+1} -> owner {owner(i+1)} | {s.strip()[:60]}")
