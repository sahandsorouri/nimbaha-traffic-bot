"""
SQLite database layer (async via aiosqlite).

Schema
------
users
  telegram_id   INTEGER PRIMARY KEY
  enc_username  TEXT NOT NULL        -- Fernet-encrypted username
  enc_password  TEXT NOT NULL        -- Fernet-encrypted password
  enc_session   TEXT                 -- Fernet-encrypted session cookies JSON
                                     -- (refreshed each successful login so the
                                     --  raw password is used as rarely as possible)
  subscribed    INTEGER DEFAULT 0    -- 1 = wants daily 9 PM notifications
  created_at    TEXT DEFAULT (datetime('now'))

usage_log
  id            INTEGER PRIMARY KEY AUTOINCREMENT
  telegram_id   INTEGER NOT NULL
  checked_at    TEXT DEFAULT (datetime('now'))  -- UTC ISO timestamp
  remaining     TEXT
  total         TEXT
  used          TEXT

The usage_log table powers the "how much did I use yesterday?" feature.
"""

import aiosqlite
from pathlib import Path

DB_PATH = Path(__file__).parent / "data" / "bot.db"


async def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                telegram_id  INTEGER PRIMARY KEY,
                enc_username TEXT    NOT NULL,
                enc_password TEXT    NOT NULL,
                enc_session  TEXT,
                subscribed   INTEGER DEFAULT 0,
                created_at   TEXT    DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS usage_log (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER NOT NULL,
                checked_at  TEXT    DEFAULT (datetime('now')),
                remaining   TEXT,
                total       TEXT,
                used        TEXT
            );
            """
        )
        # Migrate: add enc_session column if it doesn't exist yet
        try:
            await db.execute("ALTER TABLE users ADD COLUMN enc_session TEXT")
            await db.commit()
        except Exception:
            pass  # column already exists


async def upsert_user(telegram_id: int, enc_username: str, enc_password: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO users (telegram_id, enc_username, enc_password)
            VALUES (?, ?, ?)
            ON CONFLICT(telegram_id) DO UPDATE SET
                enc_username = excluded.enc_username,
                enc_password = excluded.enc_password,
                enc_session  = NULL
            """,
            (telegram_id, enc_username, enc_password),
        )
        await db.commit()


async def get_user(telegram_id: int) -> tuple[str, str] | None:
    """Return (enc_username, enc_password) or None if not registered."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT enc_username, enc_password FROM users WHERE telegram_id = ?",
            (telegram_id,),
        ) as cur:
            row = await cur.fetchone()
    return row  # type: ignore[return-value]


async def get_session(telegram_id: int) -> str | None:
    """Return the encrypted session cookie JSON, or None."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT enc_session FROM users WHERE telegram_id = ?",
            (telegram_id,),
        ) as cur:
            row = await cur.fetchone()
    return row[0] if row else None


async def set_session(telegram_id: int, enc_session: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET enc_session = ? WHERE telegram_id = ?",
            (enc_session, telegram_id),
        )
        await db.commit()


async def clear_session(telegram_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET enc_session = NULL WHERE telegram_id = ?",
            (telegram_id,),
        )
        await db.commit()


async def delete_user(telegram_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM users WHERE telegram_id = ?", (telegram_id,))
        await db.execute("DELETE FROM usage_log WHERE telegram_id = ?", (telegram_id,))
        await db.commit()


async def set_subscription(telegram_id: int, subscribed: bool) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET subscribed = ? WHERE telegram_id = ?",
            (1 if subscribed else 0, telegram_id),
        )
        await db.commit()


async def get_subscribed_users() -> list[int]:
    """Return telegram_ids of all subscribed users."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT telegram_id FROM users WHERE subscribed = 1"
        ) as cur:
            rows = await cur.fetchall()
    return [r[0] for r in rows]


async def log_usage(telegram_id: int, remaining: str, total: str, used: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO usage_log (telegram_id, remaining, total, used)
            VALUES (?, ?, ?, ?)
            """,
            (telegram_id, remaining, total, used),
        )
        await db.commit()


async def get_yesterday_usage(telegram_id: int) -> tuple[str, str] | None:
    """
    Return (used_start_of_yesterday, used_end_of_yesterday).
    Tehran is UTC+3:30 (210 minutes ahead).
    """
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            """
            SELECT MIN(used), MAX(used)
            FROM usage_log
            WHERE telegram_id = ?
              AND date(datetime(checked_at, '+210 minutes')) =
                  date(datetime('now', '+210 minutes', '-1 day'))
            """,
            (telegram_id,),
        ) as cur:
            row = await cur.fetchone()
    if row and row[0] is not None:
        return row[0], row[1]
    return None
