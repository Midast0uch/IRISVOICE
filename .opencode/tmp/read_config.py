import re
src = open(r'backend/iris_config.py', encoding='utf-8').read()
# IRISConfig.from_dict + to_dict
for m in re.finditer(r'@classmethod\s*\n\s*def from_dict', src):
    seg = src[m.start():m.start()+900]
    if 'routing' in seg:
        print(seg[:800])
        print('======')
i = src.find('def to_dict')
print(src[i:i+600])
