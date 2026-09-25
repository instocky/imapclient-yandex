"""Spike v3: fetch Yandex Mail INBOX via IMAP for one or more accounts, persist new mail in SQLite.

Multi-tenant via ACCOUNTS list in .env (JSON). Dedup per account by IMAP uid
keeps re-runs clean.
"""

import email.header
import logging
import sqlite3
import sys
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from imapclient import IMAPClient
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # readable output on capture

DB_PATH = Path("data/mail.db")
LOG_PATH = Path("cron.log")
LOG = logging.getLogger("imapclient-yandex")


def _configure_logging() -> None:
    """File log with daily rotation + console mirror. App owns cron.log now."""
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    file_h = TimedRotatingFileHandler(
        LOG_PATH, when="midnight", interval=1, backupCount=7, encoding="utf-8"
    )
    file_h.setFormatter(fmt)
    LOG.addHandler(file_h)
    stream_h = logging.StreamHandler()
    stream_h.setFormatter(fmt)
    LOG.addHandler(stream_h)
    LOG.setLevel(logging.INFO)


class Account(BaseModel):
    """One IMAP account to monitor. `user` doubles as the account key in DB."""

    host: str = "imap.yandex.ru"
    port: int = 993
    user: str
    password: str


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", case_sensitive=False, extra="ignore"
    )

    accounts: list[Account] = Field(default_factory=list)


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
    """Create or migrate the emails table.

    v1 (single-tenant): uid was UNIQUE alone.
    v2 (multi-tenant): composite UNIQUE(account, uid) — uid collisions across
    accounts are allowed. Legacy rows are backfilled under account='legacy'.
    """
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    existing = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='emails'"
    ).fetchone()

    if existing is None:
        # Fresh DB
        conn.execute(
            """CREATE TABLE emails (
                id INTEGER PRIMARY KEY,
                account TEXT NOT NULL,
                uid INTEGER NOT NULL,
                message_id TEXT,
                sender TEXT,
                subject TEXT,
                date TEXT,
                body TEXT,
                received_at TEXT NOT NULL,
                UNIQUE(account, uid)
            )"""
        )
    elif "account" not in existing[0]:
        # Legacy single-tenant table — recreate with composite unique,
        # tagging all existing rows as 'legacy'.
        conn.executescript(
            """
            ALTER TABLE emails RENAME TO _emails_legacy;
            CREATE TABLE emails (
                id INTEGER PRIMARY KEY,
                account TEXT NOT NULL,
                uid INTEGER NOT NULL,
                message_id TEXT,
                sender TEXT,
                subject TEXT,
                date TEXT,
                body TEXT,
                received_at TEXT NOT NULL,
                UNIQUE(account, uid)
            );
            INSERT INTO emails (id, account, uid, message_id, sender, subject, date, body, received_at)
            SELECT id, 'legacy', uid, message_id, sender, subject, date, body, received_at
            FROM _emails_legacy;
            DROP TABLE _emails_legacy;
            """
        )
    conn.commit()
    return conn


def _store(conn: sqlite3.Connection, account: str, uid: int, msg: dict) -> bool:
    """Insert email; return True only when it was actually new."""
    env = msg[b"ENVELOPE"]
    cur = conn.execute(
        "INSERT OR IGNORE INTO emails "
        "(account, uid, message_id, sender, subject, date, body, received_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))",
        (
            account,
            uid,
            _decode(env.message_id),
            _format_sender(env),
            _decode(env.subject),
            str(env.date) if env.date else "",
            _decode(msg.get(b"BODY[TEXT]")),
        ),
    )
    return cur.rowcount == 1


def _stored_uids(conn: sqlite3.Connection, account: str) -> set:
    return {
        r[0]
        for r in conn.execute("SELECT uid FROM emails WHERE account = ?", (account,))
    }


def fetch_new_emails(client: IMAPClient, account: str, conn: sqlite3.Connection) -> None:
    client.select_folder("INBOX")
    # Fetch only uids first (cheap), then pull full data for those not
    # already stored. Keeps "mirror whole INBOX" invariant without
    # re-downloading bodies of old mail every run.
    uids = client.search("ALL")
    if not uids:
        LOG.info("No emails.")
        return
    missing = [u for u in uids if u not in _stored_uids(conn, account)]
    if not missing:
        LOG.info("No new emails.")
        return
    data = client.fetch(missing, ["ENVELOPE", "BODY[TEXT]"])
    for uid, msg in data.items():
        if not _store(conn, account, uid, msg):
            continue  # already processed in a previous run
        env = msg[b"ENVELOPE"]
        LOG.info(f"From: {_format_sender(env)}")
        LOG.info(f"Subject: {_decode(env.subject)}")
        LOG.info(f"Date: {env.date}")
        LOG.info(f"Body: {_decode(msg.get(b'BODY[TEXT]'))[:500]}")
        LOG.info("-" * 40)
    conn.commit()


def run_once(account: Account, conn: sqlite3.Connection) -> None:
    # Connection per run; context manager logs out and closes on exit.
    with IMAPClient(account.host, port=account.port, ssl=True) as client:
        client.login(account.user, account.password)
        fetch_new_emails(client, account.user, conn)


def main() -> None:
    _configure_logging()
    settings = Settings()
    if not settings.accounts:
        LOG.error(
            "No accounts configured. Set ACCOUNTS=[{...}] in .env (JSON list)."
        )
        sys.exit(1)
    conn = _init_db()
    try:
        for account in settings.accounts:
            LOG.info(f"=== account: {account.user} ({account.host}:{account.port}) ===")
            try:
                run_once(account, conn)
            except Exception:
                # Don't let one bad mailbox kill the rest of the run.
                LOG.exception(f"account {account.user} failed; continuing")
    finally:
        conn.close()


if __name__ == "__main__":
    main()