import subprocess, time

out = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True).stdout
pid = None
for line in out.splitlines():
    if ":8090" in line and "LISTENING" in line:
        pid = line.split()[-1].strip()
        break
if pid:
    print("killing", pid)
    subprocess.run(["taskkill", "/F", "/T", "/PID", pid])
    time.sleep(2)

subprocess.Popen(
    ["python", "start-backend.py"],
    stdout=open("backend_run.log", "w"),
    stderr=open("backend_err.log", "w"),
    cwd=r"C:\dev\IRISVOICE",
)
print("relaunched")
