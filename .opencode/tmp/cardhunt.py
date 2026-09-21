import sqlite3
CARD = 'card_f914cfb1-fd5'
for db in ['data/memory.db', 'data/conversations.db', 'backend/data/memory.db']:
    try:
        con = sqlite3.connect(db)
        cur = con.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [r[0] for r in cur.fetchall()]
        print('===', db, len(tables), 'tables')
        for tbl in tables:
            try:
                cols = [r[1] for r in cur.execute(f"PRAGMA table_info({tbl})")]
            except Exception:
                continue
            # only text-ish tables: check each text column for the card id
            for c in cols:
                try:
                    cur.execute(f"SELECT COUNT(*) FROM {tbl} WHERE CAST({c} AS TEXT) LIKE '%{CARD}%'")
                    n = cur.fetchone()[0]
                    if n:
                        print(f'HIT {tbl}.{c}: {n} rows')
                        cur.execute(f"SELECT rowid FROM {tbl} WHERE CAST({c} AS TEXT) LIKE '%{CARD}%' LIMIT 5")
                        print('  rowids:', cur.fetchall())
                except Exception:
                    pass
        # whisper mentions in episodes / document tables
        for tbl in ['episodes', 'document_data', 'document_blobs', 'semantic_entries', 'context_chunks', 'memory_chain', 'messages', 'conversations']:
            if tbl in tables:
                try:
                    cur.execute(f"SELECT COUNT(*) FROM {tbl}")
                    print(f'COUNT {tbl}: {cur.fetchone()[0]}')
                except Exception as e:
                    print(f'COUNT {tbl} ERR {e}')
        con.close()
    except Exception as e:
        print(db, 'ERR', e)
# whisper rows specifically
try:
    con = sqlite3.connect('data/memory.db')
    cur = con.cursor()
    for tbl in ['episodes', 'document_data', 'semantic_entries']:
        try:
            cols = [r[1] for r in cur.execute(f"PRAGMA table_info({tbl})")]
            txtcols = [c for c in cols]
            cond = ' OR '.join([f"CAST({c} AS TEXT) LIKE '%whisper%' COLLATE NOCASE" for c in txtcols])
            cur.execute(f"SELECT COUNT(*) FROM {tbl} WHERE {cond}")
            print(f'WHISPER-ROWS {tbl}: {cur.fetchone()[0]}')
        except Exception as e:
            print(f'WHISPER {tbl} ERR {e}')
    con.close()
except Exception as e:
    print('WHISPER ERR', e)
