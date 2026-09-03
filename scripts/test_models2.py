import os
import urllib.request
import json
import time

API_KEY = os.environ.get("OPENCODE_API_KEY", "YOUR_API_KEY_HERE")

time.sleep(2)
url = 'https://opencode.ai/zen/go/v1/chat/completions'
models = ['deepseek-4-flash', 'deepseek-chat', 'gpt-4', 'gpt-4o', 'claude-3-opus', 'command-r', 'command-a']

for model in models:
    data = json.dumps({
        'model': model,
        'messages': [{'role': 'user', 'content': 'Hi'}],
        'max_tokens': 5,
        'stream': False
    }).encode()
    req = urllib.request.Request(url, data=data, method='POST')
    req.add_header('Authorization', f'Bearer {API_KEY}')
    req.add_header('Content-Type', 'application/json')
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        body = json.loads(resp.read())
        content = body['choices'][0]['message']['content']
        print(f'{model}: OK -> {content[:30]}')
        break
    except urllib.error.HTTPError as e:
        err = e.read()[:200]
        print(f'{model}: HTTP {e.code} -> {err}')
    except Exception as ex:
        print(f'{model}: {type(ex).__name__}: {ex}')
