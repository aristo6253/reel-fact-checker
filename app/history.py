import json
import os
import sqlite3
from datetime import datetime, timezone


def _connect(db_path: str) -> sqlite3.Connection:
    dirname = os.path.dirname(db_path)
    if dirname:
        os.makedirs(dirname, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS checks (
            shortcode TEXT PRIMARY KEY,
            url TEXT NOT NULL,
            username TEXT,
            caption TEXT,
            product_type TEXT,
            thumbnail_url TEXT,
            transcript TEXT,
            result TEXT NOT NULL,
            checked_at TEXT NOT NULL
        )
        """
    )
    return conn


def get_cached(db_path: str, shortcode: str) -> dict | None:
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT url, transcript, result, checked_at FROM checks WHERE shortcode = ?", (shortcode,)
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    url, transcript, result_json, checked_at = row
    return {"url": url, "transcript": transcript, "result": json.loads(result_json), "checked_at": checked_at}


def save_check(
    db_path: str,
    shortcode: str,
    url: str,
    transcript: str | None,
    result_json: str,
    username: str = "",
    caption: str = "",
    product_type: str = "",
    thumbnail_url: str | None = None,
) -> None:
    conn = _connect(db_path)
    try:
        conn.execute(
            """
            INSERT OR REPLACE INTO checks
                (shortcode, url, username, caption, product_type, thumbnail_url, transcript, result, checked_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                shortcode,
                url,
                username,
                caption,
                product_type,
                thumbnail_url,
                transcript,
                result_json,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def list_all(db_path: str) -> list[dict]:
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            """
            SELECT shortcode, url, username, caption, product_type, thumbnail_url, result, checked_at
            FROM checks ORDER BY checked_at DESC
            """
        ).fetchall()
    finally:
        conn.close()
    entries = []
    for shortcode, url, username, caption, product_type, thumbnail_url, result_json, checked_at in rows:
        result = json.loads(result_json)
        entries.append(
            {
                "shortcode": shortcode,
                "url": url,
                "username": username,
                "caption": caption,
                "product_type": product_type,
                "thumbnail_url": thumbnail_url,
                "headline_verdict": result.get("headline_verdict"),
                "trustworthiness_score": result.get("trustworthiness_score"),
                "checked_at": checked_at,
            }
        )
    return entries
