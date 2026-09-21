import re, os
for root, dirs, files in os.walk(r'backend'):
    if '__pycache__' in root or 'tests' in root:
        continue
    for f in files:
        if not f.endswith('.py'):
            continue
        p = os.path.join(root, f)
        try:
            s = open(p, encoding='utf-8').read()
        except Exception:
            continue
        for m in re.finditer(r'["\']phase["\']\s*:', s):
            line_no = s.count('\n', 0, m.start()) + 1
            seg = s[max(0, m.start() - 130):m.start() + 150].replace('\n', ' | ')
            print(p.replace('\\', '/'), line_no, ':', seg[:190])
