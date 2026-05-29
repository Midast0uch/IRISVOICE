import json
import os
import urllib.request

API_KEY = os.environ.get("OPENCODE_API_KEY", "YOUR_API_KEY_HERE")

def test_url(url):
    print(f'\n--- Testing: {url} ---')
    data = json.dumps({
        'model': 'deepseek-4-flash',
        'messages': [{'role': 'user', 'content': 'Hello'}],
        'max_tokens': 50,
        'stream': False
    }).encode()

    req = urllib.request.Request(url, data=data, method='POST')
    req.add_header('Authorization', f'Bearer {API_KEY}')
    req.add_header('Content-Type', 'application/json')
    req.add_header('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')

    try:
        resp = urllib.request.urlopen(req, timeout=15)
        print('Status:', resp.status)
        print('Content-Type:', resp.headers.get('Content-Type'))
        body = resp.read()
        print('Body length:', len(body))
        print('Body preview:', body[:200])
        try:
            j = json.loads(body)
            print('JSON parsed OK')
            print('Content:', j['choices'][0]['message']['content'][:100])
        except Exception as e:
            print('JSON parse error:', e)
    except urllib.error.HTTPError as e:
        print('HTTPError:', e.code)
        print('Body:', e.read()[:200])
    except Exception as e:
        print('Error:', type(e).__name__, e)

urls = [
    'https://api.opencode.ai/zen/go/v1/chat/completions',
    'https://api.opencode.ai/v1/chat/completions',
    'https://api.opencode.ai/chat/completions',
    'https://api.opencode.ai/zen/go/chat/completions',
]

for url in urls:
    test_url(url)

