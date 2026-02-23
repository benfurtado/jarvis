"""
Jarvis Database Models — pure SQLite, no ORM.
"""
import sqlite3
import json
import uuid
import logging
from datetime import datetime

import bcrypt

logger = logging.getLogger("Jarvis")


class Database:
    """Lightweight SQLite database wrapper."""

    def __init__(self):
        self._path = None
        self._conn = None

    def init(self, db_path: str):
        self._path = db_path
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")

    @property
    def conn(self):
        return self._conn

    def create_tables(self):
        cur = self._conn.cursor()

        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                is_active INTEGER DEFAULT 1,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS tool_audit_logs (
                id TEXT PRIMARY KEY,
                user_id TEXT,
                tool_name TEXT NOT NULL,
                risk_level TEXT NOT NULL,
                args_json TEXT,
                result_summary TEXT,
                status TEXT NOT NULL,
                timestamp TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS pending_approvals (
                id TEXT PRIMARY KEY,
                user_id TEXT,
                tool_name TEXT NOT NULL,
                args_json TEXT,
                args_preview TEXT,
                status TEXT DEFAULT 'pending',
                created_at TEXT DEFAULT (datetime('now')),
                resolved_at TEXT,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS scheduled_tasks (
                id TEXT PRIMARY KEY,
                user_id TEXT,
                command TEXT NOT NULL,
                cron_expression TEXT NOT NULL,
                is_active INTEGER DEFAULT 1,
                last_run TEXT,
                next_run TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS episodic_memory (
                id TEXT PRIMARY KEY,
                event_type TEXT NOT NULL,
                content_json TEXT,
                timestamp TEXT DEFAULT (datetime('now'))
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS config (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT DEFAULT (datetime('now'))
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS chats (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                title TEXT DEFAULT 'New Chat',
                thread_id TEXT NOT NULL,
                cwd TEXT DEFAULT '/root/projects',
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                chat_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                tool_name TEXT,
                timestamp TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (chat_id) REFERENCES chats(id) ON DELETE CASCADE
            )
        """)

        self._conn.commit()
        logger.info("Database tables created/verified.")

    def ensure_admin_user(self, username: str, password: str):
        """Create admin user if not exists."""
        cur = self._conn.cursor()
        cur.execute("SELECT id FROM users WHERE username = ?", (username,))
        if cur.fetchone() is None:
            hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
            user_id = str(uuid.uuid4())
            cur.execute(
                "INSERT INTO users (id, username, password_hash) VALUES (?, ?, ?)",
                (user_id, username, hashed),
            )
            self._conn.commit()
            logger.info(f"Admin user '{username}' created.")
        else:
            logger.info(f"Admin user '{username}' already exists.")

    # --- User Operations ---
    def get_user_by_username(self, username: str):
        cur = self._conn.cursor()
        cur.execute("SELECT * FROM users WHERE username = ?", (username,))
        return cur.fetchone()

    def get_user_by_id(self, user_id: str):
        cur = self._conn.cursor()
        cur.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        return cur.fetchone()


    # --- Audit Logs ---
    def log_tool_call(self, user_id: str, tool_name: str, risk_level: str,
                      args: dict, result_summary: str, status: str):
        log_id = str(uuid.uuid4())
        cur = self._conn.cursor()
        cur.execute(
            """INSERT INTO tool_audit_logs (id, user_id, tool_name, risk_level, args_json, result_summary, status)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (log_id, user_id, tool_name, risk_level, json.dumps(args), result_summary[:500], status),
        )
        self._conn.commit()
        return log_id

    def get_audit_logs(self, limit: int = 50, offset: int = 0):
        cur = self._conn.cursor()
        cur.execute(
            "SELECT * FROM tool_audit_logs ORDER BY timestamp DESC LIMIT ? OFFSET ?",
            (limit, offset),
        )
        return [dict(row) for row in cur.fetchall()]

    # --- Pending Approvals ---
    def create_approval(self, user_id: str, tool_name: str, args: dict, args_preview: str) -> str:
        approval_id = str(uuid.uuid4())
        cur = self._conn.cursor()
        cur.execute(
            """INSERT INTO pending_approvals (id, user_id, tool_name, args_json, args_preview)
               VALUES (?, ?, ?, ?, ?)""",
            (approval_id, user_id, tool_name, json.dumps(args), args_preview),
        )
        self._conn.commit()
        return approval_id

    def get_pending_approvals(self):
        cur = self._conn.cursor()
        cur.execute(
            "SELECT * FROM pending_approvals WHERE status = 'pending' ORDER BY created_at DESC"
        )
        return [dict(row) for row in cur.fetchall()]

    def resolve_approval(self, approval_id: str, status: str):
        """status should be 'approved' or 'denied'."""
        cur = self._conn.cursor()
        cur.execute(
            "UPDATE pending_approvals SET status = ?, resolved_at = ? WHERE id = ?",
            (status, datetime.utcnow().isoformat(), approval_id),
        )
        self._conn.commit()

    def get_approval(self, approval_id: str):
        cur = self._conn.cursor()
        cur.execute("SELECT * FROM pending_approvals WHERE id = ?", (approval_id,))
        row = cur.fetchone()
        return dict(row) if row else None

    # --- Scheduled Tasks ---
    def create_scheduled_task(self, user_id: str, command: str, cron_expression: str) -> str:
        task_id = str(uuid.uuid4())
        cur = self._conn.cursor()
        cur.execute(
            """INSERT INTO scheduled_tasks (id, user_id, command, cron_expression)
               VALUES (?, ?, ?, ?)""",
            (task_id, user_id, command, cron_expression),
        )
        self._conn.commit()
        return task_id

    def get_scheduled_tasks(self, active_only: bool = True):
        cur = self._conn.cursor()
        if active_only:
            cur.execute("SELECT * FROM scheduled_tasks WHERE is_active = 1 ORDER BY created_at DESC")
        else:
            cur.execute("SELECT * FROM scheduled_tasks ORDER BY created_at DESC")
        return [dict(row) for row in cur.fetchall()]

    def deactivate_scheduled_task(self, task_id: str):
        cur = self._conn.cursor()
        cur.execute("UPDATE scheduled_tasks SET is_active = 0 WHERE id = ?", (task_id,))
        self._conn.commit()

    def update_task_last_run(self, task_id: str):
        cur = self._conn.cursor()
        cur.execute(
            "UPDATE scheduled_tasks SET last_run = ? WHERE id = ?",
            (datetime.utcnow().isoformat(), task_id),
        )
        self._conn.commit()

    # --- Episodic Memory ---
    def save_episodic_event(self, event_type: str, content: dict):
        event_id = str(uuid.uuid4())
        cur = self._conn.cursor()
        cur.execute(
            "INSERT INTO episodic_memory (id, event_type, content_json) VALUES (?, ?, ?)",
            (event_id, event_type, json.dumps(content)),
        )
        self._conn.commit()
        return event_id

    def get_episodic_events(self, event_type: str = None, limit: int = 50):
        cur = self._conn.cursor()
        if event_type:
            cur.execute(
                "SELECT * FROM episodic_memory WHERE event_type = ? ORDER BY timestamp DESC LIMIT ?",
                (event_type, limit),
            )
        else:
            cur.execute(
                "SELECT * FROM episodic_memory ORDER BY timestamp DESC LIMIT ?", (limit,)
            )
        return [dict(row) for row in cur.fetchall()]

    # --- Config / Settings ---
    def get_config(self, key: str, default=None):
        cur = self._conn.cursor()
        cur.execute("SELECT value FROM config WHERE key = ?", (key,))
        row = cur.fetchone()
        if row:
            try:
                return json.loads(row["value"])
            except:
                return row["value"]
        return default

    def set_config(self, key: str, value):
        cur = self._conn.cursor()
        val_str = json.dumps(value) if not isinstance(value, str) else value
        cur.execute(
            "INSERT INTO config (key, value, updated_at) VALUES (?, ?, datetime('now')) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = datetime('now')",
            (key, val_str)
        )
        self._conn.commit()

    def get_all_config(self):
        cur = self._conn.cursor()
        cur.execute("SELECT key, value FROM config")
        res = {}
        for row in cur.fetchall():
            try:
                res[row["key"]] = json.loads(row["value"])
            except:
                res[row["key"]] = row["value"]
        return res

    # --- Chats (Multi-Chat System) ---
    def create_chat(self, user_id: str, title: str = "New Chat",
                    cwd: str = "/root/projects") -> dict:
        chat_id = str(uuid.uuid4())
        thread_id = f"thread_{chat_id}"
        cur = self._conn.cursor()
        cur.execute(
            """INSERT INTO chats (id, user_id, title, thread_id, cwd)
               VALUES (?, ?, ?, ?, ?)""",
            (chat_id, user_id, title, thread_id, cwd),
        )
        self._conn.commit()
        return {
            "id": chat_id, "user_id": user_id, "title": title,
            "thread_id": thread_id, "cwd": cwd,
            "created_at": datetime.utcnow().isoformat(),
        }

    def get_chats(self, user_id: str) -> list:
        cur = self._conn.cursor()
        cur.execute(
            "SELECT * FROM chats WHERE user_id = ? ORDER BY updated_at DESC",
            (user_id,),
        )
        return [dict(row) for row in cur.fetchall()]

    def get_chat(self, chat_id: str) -> dict | None:
        cur = self._conn.cursor()
        cur.execute("SELECT * FROM chats WHERE id = ?", (chat_id,))
        row = cur.fetchone()
        return dict(row) if row else None

    def delete_chat(self, chat_id: str):
        cur = self._conn.cursor()
        cur.execute("DELETE FROM messages WHERE chat_id = ?", (chat_id,))
        cur.execute("DELETE FROM chats WHERE id = ?", (chat_id,))
        self._conn.commit()

    def update_chat_title(self, chat_id: str, title: str):
        cur = self._conn.cursor()
        cur.execute(
            "UPDATE chats SET title = ?, updated_at = datetime('now') WHERE id = ?",
            (title, chat_id),
        )
        self._conn.commit()

    def update_chat_cwd(self, chat_id: str, cwd: str):
        cur = self._conn.cursor()
        cur.execute(
            "UPDATE chats SET cwd = ?, updated_at = datetime('now') WHERE id = ?",
            (cwd, chat_id),
        )
        self._conn.commit()

    def touch_chat(self, chat_id: str):
        cur = self._conn.cursor()
        cur.execute(
            "UPDATE chats SET updated_at = datetime('now') WHERE id = ?",
            (chat_id,),
        )
        self._conn.commit()

    # --- Messages ---
    def save_message(self, chat_id: str, role: str, content: str,
                     tool_name: str = "") -> str:
        msg_id = str(uuid.uuid4())
        cur = self._conn.cursor()
        cur.execute(
            """INSERT INTO messages (id, chat_id, role, content, tool_name)
               VALUES (?, ?, ?, ?, ?)""",
            (msg_id, chat_id, role, content, tool_name or None),
        )
        self._conn.commit()
        return msg_id

    def get_messages(self, chat_id: str, limit: int = 200) -> list:
        cur = self._conn.cursor()
        cur.execute(
            "SELECT * FROM messages WHERE chat_id = ? ORDER BY timestamp ASC LIMIT ?",
            (chat_id, limit),
        )
        return [dict(row) for row in cur.fetchall()]
