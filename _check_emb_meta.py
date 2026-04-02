import sqlite3, struct

db = "data/chroma/chroma.sqlite3"
conn = sqlite3.connect(db)
cur = conn.cursor()

# embeddings 테이블 seq_id 상세 확인
print("=== embeddings (id, segment_id, seq_id typeof) ===")
cur.execute("SELECT id, segment_id, typeof(seq_id), seq_id FROM embeddings LIMIT 10")
for r in cur.fetchall():
    print(r)

# segments 테이블에서 현재 active segment ID 확인
print("\n=== segments (현재 활성) ===")
cur.execute("SELECT id, type, scope, collection FROM segments")
for r in cur.fetchall():
    print(r)

# embeddings에서 해당 segment의 seq_id 범위
print("\n=== segment별 seq_id 범위 ===")
cur.execute("""
    SELECT segment_id, COUNT(*), MIN(typeof(seq_id)), MAX(typeof(seq_id)), MIN(seq_id), MAX(seq_id)
    FROM embeddings GROUP BY segment_id
""")
for r in cur.fetchall():
    print(r)

conn.close()
