"""Spike v3: fetch Yandex Mail INBOX via IMAP for one or more accounts, persist new mail in SQLite.

Multi-tenant via ACCOUNTS list in .env (single-line JSON). Progress is tracked
per account as an IMAP uid cursor in the `state` table, so a run only ever asks
for the mail that arrived since the last one — the archive is never imported.
"""

import email.header
import logging
import sqlite3
import sys
from datetime import datetime, timedelta
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from imapclient import IMAPClient
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # readable output on capture

DB_PATH = Path("data/mail.db")
LOG_PATH = Path("cron.log")
LOG = logging.getLogger("imapclient-yandex")
# email.header.decode_header is O(n^2): one junky multi-MB header (a 23 MB body in
# this mailbox) is enough to hang a run for minutes. Headers get truncated.
HEADER_MAX = 1000
# Yandex answers BODY[TEXT] with the WHOLE message, PDF attachments included
# (23 MB where the text is 97 lines), so ask for a prefix: BODY[TEXT]<0.65536>
# returns 64 KB in 0.7 s. For small mail the server returns the mail in full.
BODY_PREFIX = 65536
BODY_SPEC = f"BODY[TEXT]<0.{BODY_PREFIX}>"


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
    """Decode an RFC 2047 header into a plain str. Truncated on purpose."""
    if not value:
        return ""
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    value = value[:HEADER_MAX]
    return "".join(
        chunk if isinstance(chunk, str)
        else chunk.decode(charset or "utf-8", errors="replace")
        for chunk, charset in email.header.decode_header(value)
    )


def _text(value) -> str:
    """Decode a message body. Not an encoded-word, so no header decoding."""
    if not value:
        return ""
    return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value


def _body(msg: dict) -> bytes:
    """Body bytes of a fetch response.

    Yandex answers the key as `BODY[TEXT]<0>` whatever partial spec was asked for,
    so take the one bytes-valued entry instead of looking BODY_SPEC up.
    """
    return next((v for v in msg.values() if isinstance(v, bytes)), b"")


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
    conn.execute(
        "CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )
    conn.commit()
    return conn


def _state(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM state WHERE key = ?", (key,)).fetchone()
    return row[0] if row else None


def _set_state(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO state (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


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
            _text(_body(msg)),
        ),
    )
    return cur.rowcount == 1


def _ingest(
    conn: sqlite3.Connection, account: str, client: IMAPClient, uids: list[int]
) -> None:
    """Store the given uids and log whatever is new. No commit — caller decides.

    Bodies are a bounded prefix of the message, not a parsed body: attachments are
    never downloaded and a 23 MB mail costs the same as a small one.
    """
    for uid, msg in client.fetch(uids, ["ENVELOPE", BODY_SPEC]).items():
        if not _store(conn, account, uid, msg):
            continue  # already processed in a previous run
        env = msg[b"ENVELOPE"]
        LOG.info(f"From: {_format_sender(env)}")
        LOG.info(f"Subject: {_decode(env.subject)}")
        LOG.info(f"Date: {env.date}")
        LOG.info(f"Body: {_text(_body(msg))[:500]}")
        LOG.info("-" * 40)


def sync_account(client: IMAPClient, account: str, conn: sqlite3.Connection) -> None:
    """Bring one account up to date.

    Uids are monotonic while UIDVALIDITY is unchanged, so the cursor is a uid, not
    a date: SINCE has day granularity and misses old-dated mail. A new (or
    recreated) mailbox is seeded with SINCE yesterday and its cursor pinned at
    UIDNEXT-1 — not at max(found), or mail that SINCE skipped but that has a
    higher uid would be lost forever.
    """
    client.select_folder("INBOX")
    status = client.folder_status("INBOX", ["UIDVALIDITY", "UIDNEXT"])
    uidvalidity, uidnext = int(status[b"UIDVALIDITY"]), int(status[b"UIDNEXT"])

    if _state(conn, f"uidvalidity:{account}") != str(uidvalidity):
        LOG.info(f"first run (uidvalidity={uidvalidity}), seeding with SINCE yesterday")
        # local date: INTERNALDATE is compared in the mailbox's own timezone
        yesterday = datetime.now().astimezone().date() - timedelta(days=1)
        _ingest(conn, account, client, list(client.search(["SINCE", yesterday])))
        _set_state(conn, f"uidvalidity:{account}", str(uidvalidity))
        _set_state(conn, f"last_uid:{account}", str(uidnext - 1))
    else:
        last = int(_state(conn, f"last_uid:{account}") or 0)
        # Servers may answer `UID n:*` with the mailbox's highest uid even when
        # n is past it, so drop anything at or below the cursor ourselves.
        found = [u for u in client.search([f"{last + 1}:*"]) if u > last]
        if not found:
            LOG.info(f"no new emails (uid > {last})")
            return
        _ingest(conn, account, client, found)
        _set_state(conn, f"last_uid:{account}", str(max(found)))

    # Emails and cursor land in the same transaction: a crash mid-fetch replays
    # the same uid range next run instead of skipping it.
    conn.commit()


def run_once(account: Account, conn: sqlite3.Connection) -> None:
    # Connection per run; context manager logs out and closes on exit.
    with IMAPClient(account.host, port=account.port, ssl=True) as client:
        client.login(account.user, account.password)
        sync_account(client, account.user, conn)


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