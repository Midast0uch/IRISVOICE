import sqlite3, os
from datetime import datetime

db = r'c:\Users\midas\Desktop\IRISVOICE\bootstrap\coordinates.db'
conn = sqlite3.connect(db)
cur = conn.cursor()

# Check schema of key tables
for table in ['pins', 'code_events', 'sessions', 'checkpoints', 'eml_trees']:
    cur.execute(f"PRAGMA table_info({table})")
    cols = [c[1] for c in cur.fetchall()]
    print(f'{table} columns: {cols}')
print()

# Query recent code_events
cur.execute('''
    SELECT timestamp, file_path, event_type, line_start, line_end
    FROM code_events
    ORDER BY timestamp DESC
    LIMIT 15
''')
rows = cur.fetchall()
print('=== Recent Code Events (last 15) ===')
for r in rows:
    print(f'  {r[0]} | {r[2]:15} | {r[1][:50]}:{r[3]}-{r[4]}')
print()

# Query recent sessions
cur.execute('''
    SELECT timestamp, session_id, corpus, status
    FROM sessions
    ORDER BY timestamp DESC
    LIMIT 10
''')
rows = cur.fetchall()
print('=== Recent Sessions (last 10) ===')
for r in rows:
    print(f'  {r[0]} | session={r[1]} | corpus={r[2]} | status={r[3]}')
print()

# Query recent checkpoints
cur.execute('''
    SELECT timestamp, session_id, tag
    FROM checkpoints
    ORDER BY timestamp DESC
    LIMIT 10
''')
rows = cur.fetchall()
print('=== Recent Checkpoints (last 10) ===')
for r in rows:
    print(f'  {r[0]} | session={r[1]} | tag={r[2]}')
print()

# Query recent eml_trees
cur.execute('''
    SELECT timestamp, session_id, tree_depth, compressed_size
    FROM eml_trees
    ORDER BY timestamp DESC
    LIMIT 10
''')
rows = cur.fetchall()
print('=== Recent EML Trees (last 10) ===')
for r in rows:
    print(f'  {r[0]} | session={r[1]} | depth={r[2]} | size={r[3]} bytes')
print()

conn.close()
print(f'Queried at: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
