import httpx, json, time
t0 = time.time()
b = open(r'C:\dev\IRISVOICE\.opencode\tmp\lt_prompt.json', encoding='utf-8').read()
try:
    r = httpx.post('http://127.0.0.1:8090/api/chat', content=b,
                   headers={'Content-Type': 'application/json'}, timeout=420.0)
    out = {'status': r.status_code, 'elapsed_s': round(time.time() - t0, 1),
           'body': r.text}
except Exception as e:
    out = {'status': -1, 'elapsed_s': round(time.time() - t0, 1),
           'body': f'{type(e).__name__}: {e}'}
open(r'C:\dev\IRISVOICE\.opencode\tmp\lt_result.json', 'w',
     encoding='utf-8').write(json.dumps(out))
