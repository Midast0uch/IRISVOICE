import subprocess, socket, time

# Find all PIDs on port 8090
r = subprocess.run(['netstat', '-ano'], capture_output=True, text=True, timeout=5)
pids = set()
for l in r.stdout.split('\n'):
    if '127.0.0.1:8090' in l or '0.0.0.0:8090' in l:
        parts = l.strip().split()
        if parts:
            try:
                pid = int(parts[-1])
                if pid > 0:
                    pids.add(pid)
            except:
                pass

print(f'Found PIDs: {pids}')
for pid in pids:
    r = subprocess.run(['taskkill', '/F', '/PID', str(pid)], capture_output=True, text=True, timeout=5)
    print(f'  kill {pid}: {r.stdout.strip() or r.stderr.strip()}')

time.sleep(2)
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.settimeout(3)
r = s.connect_ex(('localhost', 8090))
s.close()
print(f'Port 8090 after cleanup: {\"OPEN\" if r == 0 else \"FREE\"} (code={r})')
