"""Spike v2: fetch Yandex Mail INBOX via IMAP once, persist new mail in SQLite.

Run via cron (or manually). Dedup by IMAP uid keeps re-runs clean.
"""

import email.header
import sqlite3
import sys
from pathlib import Path

from imapclient import IMAPClient
from pydantic_settings import BaseSettings, SettingsConfigDict

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # readable output on capture

DB_PATH = Path("data/mail.db")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", case_sensitive=False, extra="ignore"
    )

    imap_host: str = "imap.yandex.ru"
    imap_port: int = 993
    imap_user: str
    imap_password: str


def _decode(value) -> str:
    """Decode RFC 2047 encoded-words and raw bytes to a plain str."""
    if not value:
        return ""
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    return "".join(
        chunk if isinstance(chunk, str)
        else chunk.decode(charset or "utf-8", errors="replace")
        for chunk, charset in email.header.decode_header(value)
    )


def _format_sender(env) -> str:
    parts = []
    for addr in (env.from_ or []):
        name = _decode(addr.name) if addr.name else ""
        mailbox = addr.mailbox or ""
        host = addr.host or ""
        email_addr = f"{mailbox}@{host}" if mailbox and host else (mailbox or host or "")
        parts.append(f"{name} <{email_addr}>" if name else email_addr)
    return ", ".join(parts)


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
    cur = conn.execute(
        "INSERT OR IGNORE INTO emails "
        "(uid, message_id, sender, subject, date, body, received_at) "
        "VALUES (?, ?, ?, ?, ?, ?, datetime('now'))",
        (
            uid,
            _decode(env.message_id),
            _format_sender(env),
            _decode(env.subject),
            str(env.date) if env.date else "",
            _decode(msg.get(b"BODY[TEXT]")),
        ),
    )
    return cur.rowcount == 1


def _stored_uids(conn: sqlite3.Connection) -> set:
    return {r[0] for r in conn.execute("SELECT uid FROM emails")}


def fetch_new_emails(client: IMAPClient, conn: sqlite3.Connection) -> None:
    client.select_folder("INBOX")
    # Fetch only uids first (cheap), then pull full data for those not
    # already stored. Keeps "mirror whole INBOX" invariant without
    # re-downloading bodies of old mail every run.
    uids = client.search("ALL")
    if not uids:
        print("No emails.")
        return
    missing = [u for u in uids if u not in _stored_uids(conn)]
    if not missing:
        print("No new emails.")
        return
    data = client.fetch(missing, ["ENVELOPE", "BODY[TEXT]"])
    for uid, msg in data.items():
        if not _store(conn, uid, msg):
            continue  # already processed in a previous run
        env = msg[b"ENVELOPE"]
        print(f"From: {_format_sender(env)}")
        print(f"Subject: {_decode(env.subject)}")
        print(f"Date: {env.date}")
        print(f"Body: {_decode(msg.get(b'BODY[TEXT]'))[:500]}")
        print("-" * 40)
    conn.commit()


def run_once(settings: Settings, conn: sqlite3.Connection) -> None:
    # Connection per run; context manager logs out and closes on exit.
    with IMAPClient(settings.imap_host, port=settings.imap_port, ssl=True) as client:
        client.login(settings.imap_user, settings.imap_password)
        fetch_new_emails(client, conn)


def main() -> None:
    settings = Settings()
    conn = _init_db()
    print("Connect -> authenticate -> INBOX -> find new emails -> persist -> print")
    try:
        run_once(settings, conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
