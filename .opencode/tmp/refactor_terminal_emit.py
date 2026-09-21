# One-shot refactor: convert the terminal task:done emit block in
# _execute_plan_der into a deferred closure _emit_terminal_event().
import ast

path = r'backend/agent/agent_kernel.py'
src = open(path, encoding='utf-8').read()
lines = src.split('\n')

start = None
for i, l in enumerate(lines):
    if 'EventBus: emit task:done / task:fail' in l:
        start = i
        break
assert start is not None, 'start marker not found'
end = None
for j in range(start, start + 90):
    if 'EventBus is optional' in lines[j]:
        end = j
        break
assert end is not None, 'end marker not found'

block = lines[start:end + 1]

new_block = []
for idx, l in enumerate(block):
    if 'self._der_step_count = len(completed_items)' in l:
        new_block.append(l)
        new_block.append('        #')
        new_block.append('        # Session 247 (live conv-44): this emit used to run HERE, BEFORE')
        new_block.append('        # synthesis. The card flipped to done while the answer did not exist')
        new_block.append('        # yet, and the "Synthesizing answer" progress frame arrived ~43s')
        new_block.append('        # AFTER task:done with no working card to attach to - the frontend')
        new_block.append('        # fabricated a phantom second card (LEGACY_UNKNOWN, THK, timer')
        new_block.append('        # running). Done must mean "the answer was delivered": the emit is')
        new_block.append('        # now a closure fired by every outcome branch BELOW, right before')
        new_block.append('        # it returns its synthesized response.')
        new_block.append('        def _emit_terminal_event() -> None:')
        continue
    new_block.append(l)

def_start = None
for i, l in enumerate(new_block):
    if 'def _emit_terminal_event' in l:
        def_start = i
        break
out = new_block[:def_start + 1]
out.append('            # Never raises; EventBus failures must not block the user response.')
for l in new_block[def_start + 1:]:
    out.append(('    ' + l) if l.strip() else l)

lines[start:end + 1] = out
open(path, 'w', encoding='utf-8', newline='').write('\n'.join(lines))
ast.parse(open(path, encoding='utf-8').read())
print('closure created, syntax OK')
