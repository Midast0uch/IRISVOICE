import sqlite3
CARD = '%card_f914cfb1-fd5%'
con = sqlite3.connect('file:data/memory.db?mode=ro', uri=True, timeout=5)
con.execute('PRAGMA busy_timeout=5000')
cur = con.cursor()
for q in [
    "SELECT id, substr(task_summary,1,120) FROM episodes WHERE task_summary LIKE ? OR full_content LIKE ? LIMIT 5",
]:
    try:
        cur.execute(q, (CARD, CARD))
        rows = cur.fetchall()
        print('EPISODES-CARD-HITS:', len(rows))
        for r in rows:
            print(' ', r)
    except Exception as e:
        print('EPISODES ERR', e)
for w in ['whisper', 'speech-to-text', 'stt', 'transcription']:
    try:
        cur.execute("SELECT COUNT(*) FROM episodes WHERE task_summary LIKE ? OR full_content LIKE ?",
                    (f'%{w}%', f'%{w}%'))
        print(f'EPISODES ~{w}:', cur.fetchone()[0])
    except Exception as e:
        print('EPISODES', w, 'ERR', e)
    try:
        cur.execute("SELECT COUNT(*) FROM memory_chain WHERE content LIKE ?", (f'%{w}%',))
        print(f'MEMCHAIN ~{w}:', cur.fetchone()[0])
    except Exception as e:
        print('MEMCHAIN', w, 'ERR', e)
try:
    cur.execute("SELECT COUNT(*) FROM memory_chain WHERE content LIKE ?", (CARD,))
    print('MEMCHAIN-CARD-HITS:', cur.fetchone()[0])
except Exception as e:
    print('MEMCHAIN CARD ERR', e)
con.close()
con2 = sqlite3.connect('file:data/conversations.db?mode=ro', uri=True, timeout=5)
con2.execute('PRAGMA busy_timeout=5000')
cur2 = con2.cursor()
try:
    cur2.execute("SELECT name FROM sqlite_master WHERE type='table'")
    print('CONV TABLES:', cur2.fetchall())
except Exception as e:
    print('CONV TABLES ERR', e)
con2.close()
print('DONE')
