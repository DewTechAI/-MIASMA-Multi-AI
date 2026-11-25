"""SQLite persistence: chat history, settings, and the encrypted key vault."""
import json
import sqlite3
import threading

from . import config

_lock = threading.Lock()


def _conn() -> sqlite3.Connection:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(config.DB_PATH, check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c


def init_db() -> None:
    with _lock, _conn() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                provider TEXT,
                model TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS vault (
                provider TEXT PRIMARY KEY,
                ciphertext BLOB NOT NULL
            );
            CREATE TABLE IF NOT EXISTS files (
                path TEXT PRIMARY KEY,
                content TEXT NOT NULL,
                updated_at TEXT DEFAULT (datetime('now'))
            );
            """
        )


# ---------- settings ----------

def get_setting(key: str, default=None):
    with _lock, _conn() as c:
        row = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    if row is None:
        return default
    try:
        return json.loads(row["value"])
    except (json.JSONDecodeError, TypeError):
        return row["value"]


def set_setting(key: str, value) -> None:
    with _lock, _conn() as c:
        c.execute(
            "INSERT INTO settings(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, json.dumps(value)),
        )


# ---------- chat history ----------

def save_message(session_id: str, role: str, content: str,
                 provider: str | None = None, model: str | None = None) -> None:
    with _lock, _conn() as c:
        c.execute(
            "INSERT INTO messages(session_id,role,content,provider,model) VALUES(?,?,?,?,?)",
            (session_id, role, content, provider, model),
        )


def get_history(session_id: str, limit: int = 100):
    with _lock, _conn() as c:
        rows = c.execute(
            "SELECT role,content,provider,model,created_at FROM messages "
            "WHERE session_id=? ORDER BY id DESC LIMIT ?",
            (session_id, limit),
        ).fetchall()
    return [dict(r) for r in reversed(rows)]


def clear_history(session_id: str) -> None:
    with _lock, _conn() as c:
        c.execute("DELETE FROM messages WHERE session_id=?", (session_id,))


def list_sessions(limit: int = 50) -> list[dict]:
    """All chat sessions, newest first, with a title preview."""
    with _lock, _conn() as c:
        rows = c.execute(
            """
            SELECT m.session_id,
                   MAX(m.created_at) AS last_at,
                   COUNT(*) AS msg_count,
                   (SELECT m2.content FROM messages m2
                    WHERE m2.session_id = m.session_id AND m2.role = 'user'
                    ORDER BY m2.id LIMIT 1) AS title
            FROM messages m
            GROUP BY m.session_id
            ORDER BY last_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


# ---------- vault (encrypted API keys) ----------

def _fernet():
    from cryptography.fernet import Fernet

    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    if config.VAULT_KEY_PATH.exists():
        key = config.VAULT_KEY_PATH.read_bytes().strip()
    else:
        key = Fernet.generate_key()
        config.VAULT_KEY_PATH.write_bytes(key + b"\n")
        config.VAULT_KEY_PATH.chmod(0o600)
    return Fernet(key)


def vault_set(provider: str, api_key: str) -> None:
    ct = _fernet().encrypt(api_key.encode())
    with _lock, _conn() as c:
        c.execute(
            "INSERT INTO vault(provider,ciphertext) VALUES(?,?) "
            "ON CONFLICT(provider) DO UPDATE SET ciphertext=excluded.ciphertext",
            (provider, ct),
        )


def vault_get(provider: str) -> str | None:
    with _lock, _conn() as c:
        row = c.execute("SELECT ciphertext FROM vault WHERE provider=?", (provider,)).fetchone()
    if not row:
        return None
    return _fernet().decrypt(row["ciphertext"]).decode()


def vault_delete(provider: str) -> None:
    with _lock, _conn() as c:
        c.execute("DELETE FROM vault WHERE provider=?", (provider,))


def vault_list() -> list[str]:
    with _lock, _conn() as c:
        return [r["provider"] for r in c.execute("SELECT provider FROM vault").fetchall()]


# ---------- workspace file index ----------

def index_file(path: str, content: str) -> None:
    with _lock, _conn() as c:
        c.execute(
            "INSERT INTO files(path,content) VALUES(?,?) "
            "ON CONFLICT(path) DO UPDATE SET content=excluded.content, "
            "updated_at=datetime('now')",
            (path, content),
        )


def list_files():
    with _lock, _conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT path,updated_at FROM files ORDER BY path").fetchall()]
