import sqlite3, os
from datetime import datetime

db = r'c:\Users\midas\Desktop\IRISVOICE\bootstrap\coordinates.db'
if not os.path.exists(db):
    print('DB not found')
    exit(1)

conn = sqlite3.connect(db)
cur = conn.cursor()

cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [t[0] for t in cur.fetchall()]
print('Tables:', tables)
print()

now = datetime.now()

if 'event_log' in tables:
    cur.execute('''
        SELECT id, timestamp, event_type, source, summary
        FROM event_log
        ORDER BY timestamp DESC
        LIMIT 10
    ''')
    rows = cur.fetchall()
    print('=== Recent Event Log (last 10) ===')
    for r in rows:
        print(f'  {r[1]} | {r[2]:20} | {r[3]:15} | {str(r[4])[:80]}')
    print()

if 'pins' in tables:
    cur.execute('''
        SELECT id, timestamp, title, type
        FROM pins
        ORDER BY timestamp DESC
        LIMIT 10
    ''')
    rows = cur.fetchall()
    print('=== Recent Pins (last 10) ===')
    for r in rows:
        print(f'  {r[1]} | {r[3]:10} | {str(r[2])[:60]}')
    print()

if 'session_archive' in tables:
    cur.execute('''
        SELECT id, timestamp, session_id
        FROM session_archive
        ORDER BY timestamp DESC
        LIMIT 5
    ''')
    rows = cur.fetchall()
    print('=== Recent Session Archives (last 5) ===')
    for r in rows:
        print(f'  {r[1]} | session={r[2]}')
    print()

if 'landmarks' in tables:
    cur.execute('''
        SELECT id, timestamp, name, activation_count
        FROM landmarks
        ORDER BY timestamp DESC
        LIMIT 10
    ''')
    rows = cur.fetchall()
    print('=== Recent Landmarks (last 10) ===')
    for r in rows:
        print(f'  {r[1]} | {r[2]:30} | activations={r[3]}')
    print()

conn.close()
print(f'DB queried at: {now.strftime("%Y-%m-%d %H:%M:%S")}')
