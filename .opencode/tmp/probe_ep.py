import sqlite3
con = sqlite3.connect('file:data/memory.db?mode=ro', uri=True, timeout=5)
con.execute('PRAGMA busy_timeout=5000')
con.row_factory = sqlite3.Row
cur = con.cursor()
cur.execute("SELECT id, session_id, task_summary, outcome_score, outcome_type, failure_reason, user_corrected, user_confirmed, duration_ms, tokens_used, model_id, tool_sequence, timestamp FROM episodes WHERE id='f218d4b6-f8fb-4298-bd7a-64231d2d197f'")
row = cur.fetchone()
if row:
    for k in row.keys():
        v = row[k]
        s = str(v)
        print(f'{k}: {s[:800]}')
else:
    print('NOT FOUND')
con.close()
print('DONE')
