import sqlite3
import os
import uuid
from datetime import datetime, timedelta

DB_PATH = os.getenv("DATABASE_PATH",
                     os.path.join(os.path.dirname(os.path.abspath(__file__)), "scraper.db"))

os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            email           TEXT NOT NULL UNIQUE,
            token           TEXT,
            token_expires   TIMESTAMP,
            last_digest_sent TIMESTAMP DEFAULT '2000-01-01 00:00:00',
            created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS alerts (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL,
            name        TEXT NOT NULL,
            region      TEXT NOT NULL,
            category    TEXT NOT NULL DEFAULT 'sss',
            query       TEXT NOT NULL,
            min_price   INTEGER,
            max_price   INTEGER,
            active      INTEGER NOT NULL DEFAULT 1,
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_checked TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS seen_posts (
            post_id     TEXT PRIMARY KEY,
            title       TEXT,
            price       TEXT,
            url         TEXT,
            neighborhood TEXT DEFAULT '',
            alert_id    INTEGER,
            first_seen  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (alert_id) REFERENCES alerts(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS notifications (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            alert_id    INTEGER,
            message     TEXT,
            post_count  INTEGER DEFAULT 0,
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (alert_id) REFERENCES alerts(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS settings (
            key   TEXT PRIMARY KEY,
            value TEXT
        );

        INSERT OR IGNORE INTO settings (key, value) VALUES ('poll_interval_minutes', '10');
    """)
    conn.commit()
    conn.close()


# --------------- Users ---------------

def create_user(email: str) -> int:
    conn = get_connection()
    cur = conn.execute("INSERT OR IGNORE INTO users (email) VALUES (?)", (email.lower().strip(),))
    conn.commit()
    if cur.lastrowid:
        uid = cur.lastrowid
    else:
        row = conn.execute("SELECT id FROM users WHERE email = ?", (email.lower().strip(),)).fetchone()
        uid = row["id"]
    conn.close()
    return uid


def get_user_by_email(email: str):
    conn = get_connection()
    row = conn.execute("SELECT * FROM users WHERE email = ?", (email.lower().strip(),)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_user_by_id(user_id: int):
    conn = get_connection()
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def set_magic_token(user_id: int, token: str, expires: datetime):
    conn = get_connection()
    conn.execute(
        "UPDATE users SET token = ?, token_expires = ? WHERE id = ?",
        (token, expires.strftime("%Y-%m-%d %H:%M:%S"), user_id),
    )
    conn.commit()
    conn.close()


def verify_magic_token(token: str):
    """Returns user dict if token is valid and not expired, else None."""
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM users WHERE token = ? AND token_expires > ?",
        (token, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
    ).fetchone()
    if row:
        conn.execute("UPDATE users SET token = NULL, token_expires = NULL WHERE id = ?", (row["id"],))
        conn.commit()
    conn.close()
    return dict(row) if row else None


def generate_magic_token(user_id: int) -> str:
    token = uuid.uuid4().hex
    expires = datetime.now() + timedelta(hours=1)
    set_magic_token(user_id, token, expires)
    return token


def get_users_with_alerts():
    conn = get_connection()
    rows = conn.execute("""
        SELECT DISTINCT u.*
        FROM users u
        INNER JOIN alerts a ON a.user_id = u.id AND a.active = 1
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_user_digest_sent(user_id: int):
    conn = get_connection()
    conn.execute(
        "UPDATE users SET last_digest_sent = ? WHERE id = ?",
        (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), user_id),
    )
    conn.commit()
    conn.close()


# --------------- Alert CRUD ---------------

def get_alerts_for_user(user_id: int, active_only=False):
    conn = get_connection()
    sql = "SELECT * FROM alerts WHERE user_id = ?"
    if active_only:
        sql += " AND active = 1"
    sql += " ORDER BY created_at DESC"
    rows = conn.execute(sql, (user_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_all_active_alerts():
    conn = get_connection()
    rows = conn.execute("SELECT * FROM alerts WHERE active = 1 ORDER BY created_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_alert(alert_id: int, user_id: int | None = None):
    conn = get_connection()
    if user_id is not None:
        row = conn.execute("SELECT * FROM alerts WHERE id = ? AND user_id = ?", (alert_id, user_id)).fetchone()
    else:
        row = conn.execute("SELECT * FROM alerts WHERE id = ?", (alert_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def add_alert(user_id: int, name: str, region: str, category: str, query: str,
              min_price: int | None = None, max_price: int | None = None) -> int:
    conn = get_connection()
    cur = conn.execute(
        "INSERT INTO alerts (user_id, name, region, category, query, min_price, max_price) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (user_id, name, region, category, query, min_price, max_price),
    )
    conn.commit()
    alert_id = cur.lastrowid
    conn.close()
    return alert_id


def update_alert(alert_id: int, **kwargs):
    allowed = {"name", "region", "category", "query", "min_price", "max_price", "active", "last_checked"}
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        return
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [alert_id]
    conn = get_connection()
    conn.execute(f"UPDATE alerts SET {set_clause} WHERE id = ?", values)
    conn.commit()
    conn.close()


def delete_alert(alert_id: int, user_id: int):
    conn = get_connection()
    conn.execute("DELETE FROM alerts WHERE id = ? AND user_id = ?", (alert_id, user_id))
    conn.commit()
    conn.close()


def toggle_alert(alert_id: int, user_id: int):
    conn = get_connection()
    conn.execute(
        "UPDATE alerts SET active = CASE WHEN active = 1 THEN 0 ELSE 1 END WHERE id = ? AND user_id = ?",
        (alert_id, user_id),
    )
    conn.commit()
    conn.close()


# --------------- Seen Posts ---------------

def is_new_post(post_id: str) -> bool:
    conn = get_connection()
    row = conn.execute("SELECT 1 FROM seen_posts WHERE post_id = ?", (post_id,)).fetchone()
    conn.close()
    return row is None


def save_post(post_id: str, title: str, price: str, url: str, alert_id: int, neighborhood: str = ""):
    conn = get_connection()
    conn.execute(
        "INSERT OR IGNORE INTO seen_posts (post_id, title, price, url, alert_id, neighborhood) VALUES (?, ?, ?, ?, ?, ?)",
        (post_id, title, price, url, alert_id, neighborhood),
    )
    conn.commit()
    conn.close()


def get_posts_for_alert(alert_id: int, limit: int = 100):
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM seen_posts WHERE alert_id = ? ORDER BY first_seen DESC LIMIT ?",
        (alert_id, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_post_count(alert_id: int) -> int:
    conn = get_connection()
    row = conn.execute("SELECT COUNT(*) as cnt FROM seen_posts WHERE alert_id = ?", (alert_id,)).fetchone()
    conn.close()
    return row["cnt"] if row else 0


# --------------- Notifications ---------------

def add_notification(alert_id: int, message: str, post_count: int):
    conn = get_connection()
    conn.execute(
        "INSERT INTO notifications (alert_id, message, post_count) VALUES (?, ?, ?)",
        (alert_id, message, post_count),
    )
    conn.commit()
    conn.close()


def get_notifications_for_user(user_id: int, limit: int = 20):
    conn = get_connection()
    rows = conn.execute("""
        SELECT n.*, a.name as alert_name
        FROM notifications n
        INNER JOIN alerts a ON n.alert_id = a.id
        WHERE a.user_id = ?
        ORDER BY n.created_at DESC LIMIT ?
    """, (user_id, limit)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# --------------- Settings ---------------

def get_setting(key: str, default: str = "") -> str:
    conn = get_connection()
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else default


def set_setting(key: str, value: str):
    conn = get_connection()
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()


# --------------- Digest helpers ---------------

def get_digest_results_for_user(user_id: int, since: str) -> dict[str, list[dict]]:
    """Get new posts since a timestamp for a specific user, grouped by alert name."""
    conn = get_connection()
    rows = conn.execute("""
        SELECT p.*, a.name as alert_name
        FROM seen_posts p
        INNER JOIN alerts a ON p.alert_id = a.id
        WHERE a.user_id = ? AND p.first_seen > ?
        ORDER BY a.name, p.first_seen DESC
    """, (user_id, since)).fetchall()
    conn.close()

    results: dict[str, list[dict]] = {}
    for p in [dict(r) for r in rows]:
        name = p.get("alert_name") or "Unknown Alert"
        results.setdefault(name, []).append({
            "title": p["title"],
            "price": p["price"],
            "url": p["url"],
            "neighborhood": p.get("neighborhood", ""),
        })
    return results
