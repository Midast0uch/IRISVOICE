import re, os

# 1) who calls respond_to_permission
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
        for m in re.finditer(r'respond_to_permission', s):
            print('CALLER:', p, s.count('\n', 0, m.start()) + 1)

print('===WS HANDLERS===')
src = open(r'backend/gateway/iris_gateway.py', encoding='utf-8').read()
for m in re.finditer(r'msg_type == "([a-z_:]+)"', src):
    t = m.group(1)
    if 'permission' in t or 'notif' in t or 'question' in t:
        line_no = src.count('\n', 0, m.start()) + 1
        print(line_no, ':', t)
