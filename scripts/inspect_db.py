"""Inspect the Yandex Mail IMAP spike SQLite database."""

import sqlite3
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # readable output on capture

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "mail.db"


def main() -> None:
    if not DB_PATH.exists():
        print(f"No database at {DB_PATH} — run main.py first.")
        return

    conn = sqlite3.connect(DB_PATH)
    count = conn.execute("SELECT count(*) FROM emails").fetchone()[0]
    print(f"Database: {DB_PATH}")
    print(f"Total emails stored: {count}\n")

    rows = conn.execute(
        "SELECT uid, sender, subject, date, received_at FROM emails ORDER BY uid"
    )
    for uid, sender, subject, date, received_at in rows:
        print(f"uid={uid} | {received_at}")
        print(f"  From:    {sender}")
        print(f"  Subject: {subject}")
        print(f"  Date:    {date}")
        print("-" * 40)
    conn.close()


if __name__ == "__main__":
    main()
