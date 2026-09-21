import re, collections
path = '.iris-logs/backend-20260909-123105.log'
pat = re.compile(r'conv-98|f218d4b6|card_f914cfb1|DER completed|DER path error|DataExtractor|Empty response|synthes', re.IGNORECASE)
# cite pattern separate to avoid noise: match 'citat' or 'citation'
pat2 = re.compile(r'citat|_split_step|verify_failed|Found \d+ similar|memory_chain|task:(start|done|fail)|CARD_LIFECYCLE|TASK_CARD|steer', re.IGNORECASE)
hits = []
with open(path, encoding='utf-8', errors='replace') as f:
    for i, line in enumerate(f):
        if 'conv-98' in line or 'f218d4b6' in line or 'card_f914cfb1' in line or 'DER completed' in line or 'DER path error' in line or 'Empty response' in line or 'DataExtractor' in line:
            hits.append((i+1, line.rstrip()[:280]))
print('HITS:', len(hits))
for n, l in hits[-80:]:
    print(n, l)
