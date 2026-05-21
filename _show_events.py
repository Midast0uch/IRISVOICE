import sqlite3
from datetime import datetime

db = r'c:\Users\midas\Desktop\IRISVOICE\bootstrap\coordinates.db'
conn = sqlite3.connect(db)
cur = conn.cursor()

cur.execute('''
    SELECT created_at, file_path, event_type, description, session_id
    FROM code_events
    ORDER BY created_at DESC
    LIMIT 15
''')
rows = cur.fetchall()
print('=== RECENT CODE EVENTS (last 15) ===')
print()
for r in rows:
    ts = datetime.fromtimestamp(r[0])
    file = r[1][:50] if r[1] else ''
    desc = (r[3] or '')[:60]
    print(ts.strftime('%Y-%m-%d %H:%M:%S') + ' | ' + r[2] + ' | ' + file)
    print('    ' + desc)
    print()

cur.execute('''
    SELECT updated_at, session_id, active_task, unverified_edits
    FROM checkpoints
    ORDER BY updated_at DESC
    LIMIT 5
''')
rows = cur.fetchall()
print('=== RECENT CHECKPOINTS (last 5) ===')
for r in rows:
    ts = datetime.fromtimestamp(r[0])
    task = (r[2] or '')[:50]
    print(ts.strftime('%Y-%m-%d %H:%M:%S') + ' | session=' + r[1] + ' | unverified=' + str(r[3]))
    print('    task: ' + task)
    print()

conn.close()
now = datetime.now()
print('Current time: ' + now.strftime('%Y-%m-%d %H:%M:%S'))
