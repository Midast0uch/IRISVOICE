import subprocess
import sys
import os

os.chdir(r'c:\Users\midas\Desktop\IRISVOICE\iris-launcher')
print('Starting Vite dev server from:', os.getcwd())
subprocess.run([sys.executable, '-m', 'http.server', '8080'], cwd=r'c:\Users\midas\Desktop\IRISVOICE\iris-launcher')
