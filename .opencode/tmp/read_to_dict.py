import re
src = open(r'backend/iris_config.py', encoding='utf-8').read()
# IRISConfig.to_dict — the one containing swarm_roles
for m in re.finditer(r'def to_dict\(self\)[^:]*:\n', src):
    seg = src[m.start():m.start()+800]
    if 'swarm_roles' in seg:
        print(seg[:700])
        break
