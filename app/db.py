import os
import shutil
import sqlite3
import threading
import time

DB_PATH = "tracker.db"
DATABASE_URL = os.environ.get("DATABASE_URL")

SQLITE_SCHEMA = [
    "CREATE TABLE IF NOT EXISTS patients (phone TEXT PRIMARY KEY, expected_name TEXT)",
    "CREATE TABLE IF NOT EXISTS documents (id INTEGER PRIMARY KEY AUTOINCREMENT, phone TEXT NOT NULL, "
    "doc_type TEXT NOT NULL, status TEXT NOT NULL, file_hash TEXT NOT NULL, "
    "created_at REAL NOT NULL, last_page_at REAL NOT NULL)",
    "CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, phone TEXT NOT NULL, "
    "doc_type TEXT, event TEXT NOT NULL, detail TEXT, created_at REAL NOT NULL)",
]
POSTGRES_SCHEMA = [
    "CREATE TABLE IF NOT EXISTS patients (phone TEXT PRIMARY KEY, expected_name TEXT)",
    "CREATE TABLE IF NOT EXISTS documents (id SERIAL PRIMARY KEY, phone TEXT NOT NULL, "
    "doc_type TEXT NOT NULL, status TEXT NOT NULL, file_hash TEXT NOT NULL, "
    "created_at DOUBLE PRECISION NOT NULL, last_page_at DOUBLE PRECISION NOT NULL)",
    "CREATE TABLE IF NOT EXISTS events (id SERIAL PRIMARY KEY, phone TEXT NOT NULL, "
    "doc_type TEXT, event TEXT NOT NULL, detail TEXT, created_at DOUBLE PRECISION NOT NULL)",
]

_local = threading.local()


class PgConn:
    """Reuses one autocommit Postgres connection per thread and reconnects if it was dropped."""

    def _connect(self):
        import psycopg
        from psycopg.rows import dict_row

        _local.conn = psycopg.connect(
            DATABASE_URL, row_factory=dict_row, autocommit=True, prepare_threshold=None
        )
        return _local.conn

    def execute(self, sql, params=()):
        import psycopg

        sql = sql.replace("?", "%s")
        conn = getattr(_local, "conn", None)
        if conn is None or conn.closed:
            conn = self._connect()
        try:
            return conn.execute(sql, params)
        except psycopg.OperationalError:
            return self._connect().execute(sql, params)

    def commit(self):
        pass

    def close(self):
        pass


def get_conn():
    if DATABASE_URL:
        return PgConn()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    for statement in POSTGRES_SCHEMA if DATABASE_URL else SQLITE_SCHEMA:
        try:
            conn.execute(statement)
        except Exception as exc:
            if not DATABASE_URL:
                raise
            print("init_db:", type(exc).__name__, exc)
    conn.commit()
    conn.close()


def get_expected_name(phone):
    conn = get_conn()
    row = conn.execute("SELECT expected_name FROM patients WHERE phone = ?", (phone,)).fetchone()
    conn.close()
    return row["expected_name"] if row else None


def set_expected_name(phone, name):
    conn = get_conn()
    conn.execute(
        "INSERT INTO patients (phone, expected_name) VALUES (?, ?) "
        "ON CONFLICT(phone) DO UPDATE SET expected_name = excluded.expected_name",
        (phone, name),
    )
    conn.commit()
    conn.close()


def is_duplicate(phone, doc_type, file_hash):
    conn = get_conn()
    row = conn.execute(
        "SELECT id FROM documents WHERE phone = ? AND doc_type = ? AND file_hash = ?",
        (phone, doc_type, file_hash),
    ).fetchone()
    conn.close()
    return row is not None


def has_file(phone, file_hash):
    conn = get_conn()
    row = conn.execute(
        "SELECT id FROM documents WHERE phone = ? AND file_hash = ?", (phone, file_hash)
    ).fetchone()
    conn.close()
    return row is not None


def add_document(phone, doc_type, status, file_hash):
    now = time.time()
    conn = get_conn()
    conn.execute(
        "INSERT INTO documents (phone, doc_type, status, file_hash, created_at, last_page_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (phone, doc_type, status, file_hash, now, now),
    )
    conn.commit()
    conn.close()


def log_event(phone, doc_type, event, detail=None):
    conn = get_conn()
    conn.execute(
        "INSERT INTO events (phone, doc_type, event, detail, created_at) VALUES (?, ?, ?, ?, ?)",
        (phone, doc_type, event, detail, time.time()),
    )
    conn.commit()
    conn.close()


def get_all_phones():
    conn = get_conn()
    rows = conn.execute("SELECT DISTINCT phone FROM documents").fetchall()
    conn.close()
    return [r["phone"] for r in rows]


def get_documents_for_phone(phone):
    conn = get_conn()
    rows = conn.execute(
        "SELECT doc_type, status FROM documents WHERE phone = ?", (phone,)
    ).fetchall()
    conn.close()
    rank = {"received": 3, "blurry": 2, "review": 1}
    best = {}
    for r in rows:
        if rank.get(r["status"], 0) > rank.get(best.get(r["doc_type"]), 0):
            best[r["doc_type"]] = r["status"]
    return best


def approve_documents(phone, doc_type):
    conn = get_conn()
    cur = conn.execute(
        "UPDATE documents SET status = 'received' "
        "WHERE phone = ? AND doc_type = ? AND status = 'review'",
        (phone, doc_type),
    )
    conn.commit()
    conn.close()
    return cur.rowcount


def clear_patient(phone):
    conn = get_conn()
    for table in ("documents", "events", "patients"):
        conn.execute(f"DELETE FROM {table} WHERE phone = ?", (phone,))
    conn.commit()
    conn.close()


def clear_all():
    if not DATABASE_URL and os.path.exists(DB_PATH):
        shutil.copy(DB_PATH, f"{DB_PATH}.backup-{time.strftime('%Y%m%d-%H%M%S')}")
    conn = get_conn()
    for table in ("documents", "events", "patients"):
        conn.execute(f"DELETE FROM {table}")
    conn.commit()
    conn.close()


def clear_expected_name(phone):
    conn = get_conn()
    conn.execute("UPDATE patients SET expected_name = NULL WHERE phone = ?", (phone,))
    conn.commit()
    conn.close()


def get_review_counts(phone):
    conn = get_conn()
    rows = conn.execute(
        "SELECT doc_type, COUNT(*) AS n FROM documents "
        "WHERE phone = ? AND status = 'review' GROUP BY doc_type",
        (phone,),
    ).fetchall()
    conn.close()
    return {r["doc_type"]: r["n"] for r in rows}


def get_page_counts(phone):
    conn = get_conn()
    rows = conn.execute(
        "SELECT doc_type, COUNT(*) AS n FROM documents WHERE phone = ? GROUP BY doc_type",
        (phone,),
    ).fetchall()
    conn.close()
    return {r["doc_type"]: r["n"] for r in rows}


def get_recent_events(limit=30):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM events ORDER BY created_at DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
