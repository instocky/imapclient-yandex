"""Spike v2: poll Yandex Mail INBOX via IMAP, persist new mail in SQLite."""

import sqlite3
import time
from pathlib import Path

from imapclient import IMAPClient
from pydantic_settings import BaseSettings, SettingsConfigDict

DB_PATH = Path("data/mail.db")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", case_sensitive=False, extra="ignore"
    )

    imap_host: str = "imap.yandex.ru"
    imap_port: int = 993
    imap_user: str
    imap_password: str
    poll_sec: int = 1800


def _decode(value) -> str:
    return value.decode("utf-8", errors="replace") if value else ""


def _init_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS emails (
            id INTEGER PRIMARY KEY,
            uid INTEGER NOT NULL UNIQUE,
            message_id TEXT,
            sender TEXT,
            subject TEXT,
            date TEXT,
            body TEXT,
            received_at TEXT NOT NULL
        )"""
    )
    return conn


def _store(conn: sqlite3.Connection, uid: int, msg: dict) -> bool:
    """Insert email; return True only when it was actually new."""
    env = msg[b"ENVELOPE"]
    sender = ", ".join(str(a) for a in (env.from_ or []))
    cur = conn.execute(
        "INSERT OR IGNORE INTO emails "
        "(uid, message_id, sender, subject, date, body, received_at) "
        "VALUES (?, ?, ?, ?, ?, ?, datetime('now'))",
        (
            uid,
            _decode(env.message_id),
            sender,
            _decode(env.subject),
            str(env.date) if env.date else "",
            _decode(msg.get(b"BODY[TEXT]")),
        ),
    )
    return cur.rowcount == 1


def fetch_new_emails(client: IMAPClient, conn: sqlite3.Connection) -> None:
    client.select_folder("INBOX")
    # ponytail: fetch ALL so a fresh DB backfills the mailbox; dedup by uid
    # keeps re-runs clean. For large mailboxes, pre-filter uids by DB first.
    uids = client.search("ALL")
    if not uids:
        print("No new emails.")
        return
    data = client.fetch(uids, ["ENVELOPE", "BODY[TEXT]"])
    for uid, msg in data.items():
        if not _store(conn, uid, msg):
            continue  # already processed in a previous run
        env = msg[b"ENVELOPE"]
        sender = ", ".join(str(a) for a in (env.from_ or []))
        print(f"From: {sender}")
        print(f"Subject: {_decode(env.subject)}")
        print(f"Date: {env.date}")
        print(f"Body: {_decode(msg.get(b'BODY[TEXT]'))[:500]}")
        print("-" * 40)
    conn.commit()


def run_once(settings: Settings, conn: sqlite3.Connection) -> None:
    # Connection per cycle; context manager logs out and closes on exit,
    # so Ctrl+C during sleep leaves no dangling IMAP session.
    with IMAPClient(settings.imap_host, port=settings.imap_port, ssl=True) as client:
        client.login(settings.imap_user, settings.imap_password)
        fetch_new_emails(client, conn)


def main() -> None:
    settings = Settings()
    conn = _init_db()
    print("Connect -> authenticate -> INBOX -> find new emails -> persist -> print")
    try:
        while True:
            run_once(settings, conn)
            print(f"Sleeping {settings.poll_sec}s...\n")
            time.sleep(settings.poll_sec)
    except KeyboardInterrupt:
        print("\nShutting down.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
