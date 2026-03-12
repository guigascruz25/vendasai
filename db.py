import sqlite3
import os
from datetime import datetime
from werkzeug.security import generate_password_hash

DB_PATH = os.path.join(os.path.dirname(__file__), "vendasai.db")


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                username   TEXT NOT NULL UNIQUE,
                password   TEXT NOT NULL,
                role       TEXT NOT NULL DEFAULT 'member',
                created_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS documents (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                filename       TEXT NOT NULL,
                stored_name    TEXT NOT NULL,
                file_size      INTEGER,
                page_count     INTEGER,
                extracted_text TEXT,
                category       TEXT DEFAULT 'geral',
                active         INTEGER DEFAULT 1,
                uploaded_by    INTEGER REFERENCES users(id),
                uploaded_at    TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS chat_history (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id),
                role    TEXT NOT NULL,
                content TEXT NOT NULL,
                ts      TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS config (
                key   TEXT PRIMARY KEY,
                value TEXT
            );
        """)
        # Seed admin user on first boot
        count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        if count == 0:
            conn.execute(
                "INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
                ("admin", generate_password_hash("admin123"), "admin")
            )


# ── Users ─────────────────────────────────────────────────────────────
def get_user_by_username(username):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        return dict(row) if row else None


def get_all_users():
    with get_conn() as conn:
        rows = conn.execute("SELECT id, username, role, created_at FROM users ORDER BY id").fetchall()
        return [dict(r) for r in rows]


def create_user(username, password, role="member"):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
            (username, generate_password_hash(password), role)
        )


def delete_user(user_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))


def update_user_password(user_id, new_password):
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET password = ? WHERE id = ?",
            (generate_password_hash(new_password), user_id)
        )


# ── Documents ─────────────────────────────────────────────────────────
def save_document(filename, stored_name, file_size, page_count, extracted_text, category, uploaded_by):
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO documents
               (filename, stored_name, file_size, page_count, extracted_text, category, uploaded_by)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (filename, stored_name, file_size, page_count, extracted_text, category, uploaded_by)
        )


def get_all_documents():
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM documents ORDER BY uploaded_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def toggle_document(doc_id):
    with get_conn() as conn:
        conn.execute(
            "UPDATE documents SET active = CASE WHEN active = 1 THEN 0 ELSE 1 END WHERE id = ?",
            (doc_id,)
        )


def delete_document(doc_id):
    with get_conn() as conn:
        row = conn.execute("SELECT stored_name FROM documents WHERE id = ?", (doc_id,)).fetchone()
        conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
        return row["stored_name"] if row else None


def get_active_documents():
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT filename, category, extracted_text FROM documents
               WHERE active = 1 AND extracted_text IS NOT NULL
               ORDER BY
                   CASE category
                       WHEN 'scripts'   THEN 1
                       WHEN 'faq'       THEN 2
                       WHEN 'objecoes'  THEN 3
                       WHEN 'produto'   THEN 4
                       ELSE 5
                   END, uploaded_at DESC"""
        ).fetchall()
        return [dict(r) for r in rows]


# ── Chat History ──────────────────────────────────────────────────────
def save_chat_message(user_id, role, content):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO chat_history (user_id, role, content) VALUES (?, ?, ?)",
            (user_id, role, content)
        )


def get_chat_history(user_id, limit=20):
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT role, content, ts FROM chat_history
               WHERE user_id = ? ORDER BY id DESC LIMIT ?""",
            (user_id, limit)
        ).fetchall()
        return list(reversed([dict(r) for r in rows]))


def clear_chat_history(user_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM chat_history WHERE user_id = ?", (user_id,))


# ── Config ────────────────────────────────────────────────────────────
def get_config():
    with get_conn() as conn:
        rows = conn.execute("SELECT key, value FROM config").fetchall()
        return {r["key"]: r["value"] for r in rows}


def save_config(data: dict):
    with get_conn() as conn:
        for k, v in data.items():
            conn.execute(
                "INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)",
                (k, str(v))
            )
