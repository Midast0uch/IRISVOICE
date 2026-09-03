import os
import urllib.request
import json

API_KEY = os.environ.get("OPENCODE_API_KEY", "YOUR_API_KEY_HERE")

models = ['deepseek-4-flash', 'deepseek', 'deepseek-chat', 'command-a-03-2025', 'gpt-4', 'claude-3-5-sonnet', 'default']

for model in models:
    url = 'https://opencode.ai/zen/go/v1/chat/completions'
    data = json.dumps({
        'model': model,
        'messages': [{'role': 'user', 'content': 'Hello, say hi in one word'}],
        'max_tokens': 10,
        'stream': False
    }).encode()
    req = urllib.request.Request(url, data=data, method='POST')
    req.add_header('Authorization', f'Bearer {API_KEY}')
    req.add_header('Content-Type', 'application/json')
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        body = json.loads(resp.read())
        content = body['choices'][0]['message']['content']
        print(f'{model}: SUCCESS -> {content[:50]}')
        break
    except urllib.error.HTTPError as e:
        try:
            err = json.loads(e.read())
            print(f'{model}: HTTPError {e.code} -> {err}')
        except:
            print(f'{model}: HTTPError {e.code}')
    except Exception as e:
        print(f'{model}: {type(e).__name__}: {e}')
