import re
txt = open('.opencode/tmp/probe_fc.txt', encoding='utf-8', errors='replace').read()
print('TOTAL:', len(txt))
print('=== TAIL 4000 ===')
print(txt[-4000:])
