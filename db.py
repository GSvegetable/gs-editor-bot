import psycopg2
from config import DATABASE_URL

def get_db():
    return psycopg2.connect(DATABASE_URL)

def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS bots (
            id SERIAL PRIMARY KEY,
            token TEXT UNIQUE NOT NULL,
            owner_id TEXT NOT NULL,
            welcome_text TEXT DEFAULT '欢迎使用！',
            bot_name TEXT,
            bot_username TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute("ALTER TABLE bots ADD COLUMN IF NOT EXISTS bot_name TEXT")
    cur.execute("ALTER TABLE bots ADD COLUMN IF NOT EXISTS bot_username TEXT")
    conn.commit()
    cur.close()
    conn.close()

def get_user_bots(owner_id):
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT id, token, bot_name, bot_username FROM bots WHERE owner_id = %s", (owner_id,))
    rows = cur.fetchall()
    cur.close(); conn.close()
    return rows

def count_user_bots(owner_id):
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM bots WHERE owner_id = %s", (owner_id,))
    count = cur.fetchone()[0]
    cur.close(); conn.close()
    return count

def insert_bot(token, owner_id, bot_name, bot_username):
    conn = get_db(); cur = conn.cursor()
    cur.execute("INSERT INTO bots (token, owner_id, bot_name, bot_username) VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING", (token, owner_id, bot_name, bot_username))
    conn.commit(); cur.close(); conn.close()

def get_bot_token_by_id(bid):
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT token FROM bots WHERE id = %s", (bid,))
    row = cur.fetchone()
    cur.close(); conn.close()
    return row[0] if row else None

def delete_bot_by_id(bid):
    conn = get_db(); cur = conn.cursor()
    cur.execute("DELETE FROM bots WHERE id = %s", (bid,))
    conn.commit(); cur.close(); conn.close()
