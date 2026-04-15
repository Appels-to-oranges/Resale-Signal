import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scraper.db")


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS alerts (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT NOT NULL,
            region      TEXT NOT NULL,
            category    TEXT NOT NULL DEFAULT 'sss',
            query       TEXT NOT NULL,
            min_price   INTEGER,
            max_price   INTEGER,
            active      INTEGER NOT NULL DEFAULT 1,
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_checked TIMESTAMP
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


# --------------- Alert CRUD ---------------

def get_alerts(active_only=False):
    conn = get_connection()
    sql = "SELECT * FROM alerts"
    if active_only:
        sql += " WHERE active = 1"
    sql += " ORDER BY created_at DESC"
    rows = conn.execute(sql).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_alert(alert_id: int):
    conn = get_connection()
    row = conn.execute("SELECT * FROM alerts WHERE id = ?", (alert_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def add_alert(name: str, region: str, category: str, query: str,
              min_price: int | None = None, max_price: int | None = None) -> int:
    conn = get_connection()
    cur = conn.execute(
        "INSERT INTO alerts (name, region, category, query, min_price, max_price) VALUES (?, ?, ?, ?, ?, ?)",
        (name, region, category, query, min_price, max_price),
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


def delete_alert(alert_id: int):
    conn = get_connection()
    conn.execute("DELETE FROM alerts WHERE id = ?", (alert_id,))
    conn.commit()
    conn.close()


def toggle_alert(alert_id: int):
    conn = get_connection()
    conn.execute("UPDATE alerts SET active = CASE WHEN active = 1 THEN 0 ELSE 1 END WHERE id = ?", (alert_id,))
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


def get_notifications(limit: int = 30):
    conn = get_connection()
    rows = conn.execute("""
        SELECT n.*, a.name as alert_name
        FROM notifications n
        LEFT JOIN alerts a ON n.alert_id = a.id
        ORDER BY n.created_at DESC LIMIT ?
    """, (limit,)).fetchall()
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

def get_new_posts_since(since: str) -> list[dict]:
    """Get all posts found after a given timestamp, grouped-ready."""
    conn = get_connection()
    rows = conn.execute("""
        SELECT p.*, a.name as alert_name
        FROM seen_posts p
        LEFT JOIN alerts a ON p.alert_id = a.id
        WHERE p.first_seen > ?
        ORDER BY a.name, p.first_seen DESC
    """, (since,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_digest_results_since(since: str) -> dict[str, list[dict]]:
    """Get new posts since a timestamp, grouped by alert name."""
    posts = get_new_posts_since(since)
    results: dict[str, list[dict]] = {}
    for p in posts:
        name = p.get("alert_name") or "Unknown Alert"
        results.setdefault(name, []).append({
            "title": p["title"],
            "price": p["price"],
            "url": p["url"],
            "neighborhood": p.get("neighborhood", ""),
        })
    return results
