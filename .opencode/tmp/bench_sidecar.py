import httpx, time
texts = [
    'latest nuclear fusion developments',
    'commercial fusion power timeline',
    'find similar past tasks about fusion energy',
]
for t in texts:
    t0 = time.time()
    r = httpx.post('http://127.0.0.1:18183/v1/embeddings', json={'input': t}, timeout=60)
    dt = time.time() - t0
    dim = len(r.json()['data'][0]['embedding'])
    print(f'{dt:.2f}s dim={dim}')
