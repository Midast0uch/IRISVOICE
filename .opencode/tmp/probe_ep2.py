import sqlite3
con = sqlite3.connect('file:data/memory.db?mode=ro', uri=True, timeout=5)
con.execute('PRAGMA busy_timeout=5000')
cur = con.cursor()
cur.execute("SELECT length(full_content), length(tool_sequence), tool_sequence FROM episodes WHERE id='f218d4b6-f8fb-4298-bd7a-64231d2d197f'")
ln, lt, ts = cur.fetchone()
print('full_content_len:', ln, 'toolseq_len:', lt)
open('.opencode/tmp/probe_ts.json', 'w', encoding='utf-8').write(ts or '')
cur.execute("SELECT full_content FROM episodes WHERE id='f218d4b6-f8fb-4298-bd7a-64231d2d197f'")
fc = cur.fetchone()[0] or ''
open('.opencode/tmp/probe_fc.txt', 'w', encoding='utf-8').write(fc)
print('fc_head:', fc[:1500])
con.close()
print('DONE')
