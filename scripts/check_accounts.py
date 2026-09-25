"""Check that every account in ACCOUNTS can log into IMAP. Read-only, no mail fetched.

Run: uv run python scripts/check_accounts.py
Exit code 1 if any account failed.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # readable output on capture

from imapclient import IMAPClient
from imapclient.exceptions import IMAPClientError

from main import Settings


def main() -> int:
    accounts = Settings().accounts
    if not accounts:
        print("No accounts configured (ACCOUNTS in .env).")
        return 1

    failed = 0
    for acc in accounts:
        try:
            with IMAPClient(acc.host, port=acc.port, ssl=True, timeout=30) as client:
                client.login(acc.user, acc.password)
                client.select_folder("INBOX")
                status = client.folder_status("INBOX", ["UIDVALIDITY", "UIDNEXT", "MESSAGES"])
                print(
                    f"[OK]   {acc.user} — {status[b'MESSAGES']} messages, "
                    f"uidnext={status[b'UIDNEXT']}, uidvalidity={status[b'UIDVALIDITY']}"
                )
        except (IMAPClientError, OSError) as e:
            failed += 1
            print(f"[FAIL] {acc.user} — {type(e).__name__}: {e}")
    print(f"\n{len(accounts) - failed}/{len(accounts)} ok")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
