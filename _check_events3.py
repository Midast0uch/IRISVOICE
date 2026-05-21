import sqlite3
from datetime import datetime

db = r'c:\Users\midas\Desktop\IRISVOICE\bootstrap\coordinates.db'
conn = sqlite3.connect(db)
cur = conn.cursor()

# Query recent code_events
cur.execute('''
    SELECT created_at, file_path, event_type, description, outcome, session_id
    FROM code_events
    ORDER BY created_at DESC
    LIMIT 20
''')
rows = cur.fetchall()
print('=== Recent Code Events (last 20) ===')
for r in rows:
    desc = (r[3] or '')[:50]
    outcome = (r[4] or '')[:20]
    print(f'  {r[0]} | {r[2]:12} | {r[1][:40]:40} | {desc} | {outcome}')
print()

# Query recent checkpoints
cur.execute('''
    SELECT created_at, updated_at, session_id, active_task, unverified_edits, warnings
    FROM checkpoints
    ORDER BY updated_at DESC
    LIMIT 10
''')
rows = cur.fetchall()
print('=== Recent Checkpoints (last 10) ===')
for r in rows:
    task = (r[3] or '')[:40]
    print(f'  created={r[0]} | updated={r[1]} | session={r[2]} | unverified={r[4]} | warnings={r[5]}')
    print(f'    task: {task}')
print()

# Query recent sessions
cur.execute('''
    SELECT started_at, ended_at, session_id, session_number, objective, tasks_completed, graph_maturity
    FROM sessions
    ORDER BY started_at DESC
    LIMIT 10
''')
rows = cur.fetchall()
print('=== Recent Sessions (last 10) ===')
for r in rows:
    obj = (r[4] or '')[:40]
    print(f'  start={r[0]} | end={r[1] or "active":8} | #{r[5]} | maturity={r[6]}')
    print(f'    objective: {obj}')
print()

# Query recent eml_trees
cur.execute('''
    SELECT created_at, session_id, depth, total_nodes, file_path
    FROM eml_trees
    ORDER BY created_at DESC
    LIMIT 10
''')
rows = cur.fetchall()
print('=== Recent EML Trees (last 10) ===')
for r in rows:
    print(f'  {r[0]} | session={r[1]} | depth={r[2]} | nodes={r[3]} | {r[4]}')
print()

conn.close()
print(f'Queried at: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
