import ssl, httpx, json, time, sys

def test(label, make_ctx):
    ctx = make_ctx()
    t0 = time.time()
    try:
        r = httpx.post('https://api.cerebras.ai/v1/chat/completions',
            json={'model':'gemma-4-31b','messages':[{'role':'user','content':'say hi'}],'max_tokens':10},
            headers={'Authorization':'Bearer csk-wn5m3wp3pkwjepye29vkv4ny68j3xkpwy2j24dy6vrrw35r5','Content-Type':'application/json'},
            timeout=15, verify=ctx)
        return f"{label}: OK {r.status_code} {r.text[:100]} ({round(time.time()-t0,1)}s)"
    except Exception as e:
        return f"{label}: ERR {repr(e)[:120]} ({round(time.time()-t0,1)}s)"

results = []
# 1) default context
results.append(test("default", lambda: ssl.create_default_context()))
# 2) default + disable revocation flags
def ctx_norev():
    c = ssl.create_default_context()
    try:
        c.verify_flags = ssl.VERIFY_DEFAULT & ~getattr(ssl, 'VERIFY_CRL_CHECK_CHAIN', 0)
    except Exception:
        pass
    return c
results.append(test("norev_flags", ctx_norev))
# 3) verify=False (insecure but tests connectivity)
try:
    t0=time.time()
    r = httpx.post('https://api.cerebras.ai/v1/chat/completions',
        json={'model':'gemma-4-31b','messages':[{'role':'user','content':'say hi'}],'max_tokens':10},
        headers={'Authorization':'Bearer csk-wn5m3wp3pkwjepye29vkv4ny68j3xkpwy2j24dy6vrrw35r5','Content-Type':'application/json'},
        timeout=15, verify=False)
    results.append(f"verifyFalse: OK {r.status_code} {r.text[:100]} ({round(time.time()-t0,1)}s)")
except Exception as e:
    results.append(f"verifyFalse: ERR {repr(e)[:120]} ({round(time.time()-t0,1)}s)")

open('C:/dev/IRISVOICE/logs/ssltest.log','w').write("\n".join(results))
